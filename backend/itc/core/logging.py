"""
Structured JSON logging for the ITC backend.

Features
--------
* Every log line is a JSON object — machine-parseable by any log aggregator.
* ``tenant_id`` and ``trace_id`` are injected automatically via
  ``contextvars`` (set once per request, propagated to all log calls).
* A ``RedactionFilter`` attached to the root logger replaces sensitive values
  **at the filter layer** — callers never need to redact manually.

Redaction rules (applied at DEBUG level only)
---------------------------------------------
* **GSTIN** — 15-character alphanumeric GST Identification Numbers matching
  the official pattern ``[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}``
* **Invoice amounts** — bare numeric strings that look like currency values
  (digits with optional decimal, optionally preceded by a currency symbol ₹/Rs)

Usage
-----
::

    from itc.core.logging import configure_logging, get_logger, bind_context

    configure_logging(level="DEBUG")       # call once at startup
    bind_context(tenant_id="T1", trace_id="abc-123")

    logger = get_logger(__name__)
    logger.debug(
        "Processing invoice",
        extra={"gstin": "29ABCDE1234F1Z5", "amount": "1500.00"},
    )
    # → {"level":"DEBUG","logger":"...","message":"Processing invoice",
    #    "gstin":"[REDACTED]","amount":"[REDACTED]",
    #    "tenant_id":"T1","trace_id":"abc-123",...}
"""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Final

# ---------------------------------------------------------------------------
# Context variables — set once per request/task, read by the formatter
# ---------------------------------------------------------------------------

_tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="")
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def bind_context(*, tenant_id: str = "", trace_id: str = "") -> None:
    """Bind per-request context that will appear on every subsequent log line."""
    _tenant_id_var.set(tenant_id)
    _trace_id_var.set(trace_id)


def clear_context() -> None:
    """Reset context vars to their defaults (useful in tests)."""
    _tenant_id_var.set("")
    _trace_id_var.set("")


# ---------------------------------------------------------------------------
# Redaction patterns
# ---------------------------------------------------------------------------

# Official GSTIN format:
#   2-digit state code + 5-letter PAN prefix + 4-digit year + letter + check
#   e.g. 29ABCDE1234F1Z5
_GSTIN_RE: Final[re.Pattern[str]] = re.compile(
    r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b"
)

# Invoice amount: optional ₹/Rs prefix, digits, optional decimal part.
#   Uses \d+ for the integer part (covers 4-digit+ amounts like 1500.00)
#   and a negative lookahead (?!\d) to prevent partial matches mid-number.
#   Examples matched:  ₹1500.00  Rs 250  1500  1,23,456.78  ₹99
_AMOUNT_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:₹|Rs\.?\s*)?\b\d+(?:,\d{2,3})*(?:\.\d+)?(?!\d)"
)

REDACTED: Final[str] = "[REDACTED]"


def _redact_value(value: Any) -> Any:
    """
    Redact GSTIN and amount patterns inside a string value.
    Non-string values are returned unchanged.
    """
    if not isinstance(value, str):
        return value
    value = _GSTIN_RE.sub(REDACTED, value)
    value = _AMOUNT_RE.sub(REDACTED, value)
    return value


def _redact_record_fields(record_dict: dict[str, Any]) -> dict[str, Any]:
    """Walk all string fields of a log record dict and redact sensitive data."""
    return {k: _redact_value(v) for k, v in record_dict.items()}


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """
    Serialises every ``LogRecord`` as a single-line JSON object.

    Standard fields always present:
        timestamp, level, logger, message

    Context fields (when set via ``bind_context``):
        tenant_id, trace_id

    Any ``extra`` keys passed to the logger call are promoted to top-level
    JSON fields.
    """

    # Fields that exist on every LogRecord but are not useful in JSON output
    _SKIP: Final[frozenset[str]] = frozenset(
        {
            "args",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "message",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "taskName",
            "thread",
            "threadName",
        }
    )

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        if record.exc_info:
            record.exc_text = self.formatException(record.exc_info)

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
            "tenant_id": _tenant_id_var.get(),
            "trace_id": _trace_id_var.get(),
        }

        # Merge any extra fields the caller supplied
        for key, value in record.__dict__.items():
            if key not in self._SKIP and not key.startswith("_"):
                payload[key] = value

        if record.exc_text:
            payload["exception"] = record.exc_text

        return json.dumps(payload, default=str)


# ---------------------------------------------------------------------------
# Redaction filter
# ---------------------------------------------------------------------------


class RedactionFilter(logging.Filter):
    """
    Scrubs GSTIN values and invoice amounts from log records **at DEBUG level**.

    Applied as a filter on the handler (not the logger) so it runs after
    level checks and before serialisation.  Callers never touch redaction.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno == logging.DEBUG:
            # Redact the main message
            record.msg = _redact_value(str(record.getMessage()))
            record.args = ()  # args already merged into msg above

            # Redact any extra fields attached to the record
            skip = {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "taskName",
                "message",
            }
            for key in list(record.__dict__):
                if key not in skip and not key.startswith("_"):
                    setattr(record, key, _redact_value(getattr(record, key)))

        return True  # always allow the record through (level still applies)


# ---------------------------------------------------------------------------
# Public configuration helper
# ---------------------------------------------------------------------------


def configure_logging(level: str = "INFO") -> None:
    """
    Configure the root logger with JSON output and redaction.

    Call once at application startup, e.g. inside ``create_app()``.

    Parameters
    ----------
    level:
        Root log level as a string (``"DEBUG"``, ``"INFO"``, etc.).
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger (thin wrapper kept for API consistency)."""
    return logging.getLogger(name)
