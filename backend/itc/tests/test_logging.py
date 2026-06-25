"""
Tests for itc/core/logging.py (Issue #6).

Acceptance criteria
-------------------
1. A DEBUG log of a record containing a real GSTIN contains NO raw GSTIN string.
2. Invoice amounts are also redacted at DEBUG level.
3. At INFO level and above, sensitive data is NOT redacted.
4. Log output is valid JSON with tenant_id and trace_id on every line.
5. Context binding (bind_context) propagates to every log call.
6. The redaction filter is transparent — the record still reaches the handler.
"""

from __future__ import annotations

import json
import logging
from io import StringIO
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

import pytest

from itc.core.logging import (
    REDACTED,
    JsonFormatter,
    RedactionFilter,
    bind_context,
    clear_context,
    configure_logging,
    get_logger,
)

# ---------------------------------------------------------------------------
# Sample sensitive data
# ---------------------------------------------------------------------------

VALID_GSTIN = "29ABCDE1234F1Z5"  # real-format GSTIN
VALID_GSTIN_2 = "07AAGCM8702N1Z3"  # another real-format GSTIN
AMOUNT_PLAIN = "1500.00"
AMOUNT_SYMBOL = "₹1500.00"
AMOUNT_RS = "Rs 250"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_context() -> Generator[None]:
    """Ensure context vars are clean before and after every test."""
    clear_context()
    yield
    clear_context()


@pytest.fixture
def log_stream() -> StringIO:
    return StringIO()


@pytest.fixture
def debug_logger(log_stream: StringIO) -> logging.Logger:
    """
    Returns a fresh logger wired with JsonFormatter + RedactionFilter at DEBUG.
    Isolated from the root logger to avoid test pollution.
    """
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())

    logger = logging.getLogger(f"test_debug_{id(log_stream)}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
    return logger


@pytest.fixture
def info_logger(log_stream: StringIO) -> logging.Logger:
    """Same setup but at INFO level — redaction should NOT fire at INFO."""
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactionFilter())

    logger = logging.getLogger(f"test_info_{id(log_stream)}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def _parse(stream: StringIO) -> dict[str, Any]:
    """Return the first JSON object written to stream."""
    stream.seek(0)
    result: dict[str, Any] = json.loads(stream.readline())
    return result


# ===========================================================================
# 1. GSTIN redaction at DEBUG level
# ===========================================================================


class TestGstinRedactionAtDebug:
    def test_gstin_in_message_is_redacted(
        self, debug_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        """Core acceptance test: raw GSTIN must not appear in DEBUG output."""
        debug_logger.debug("Processing GSTIN %s", VALID_GSTIN)

        raw = log_stream.getvalue()
        assert VALID_GSTIN not in raw, "Raw GSTIN leaked into DEBUG log"
        assert REDACTED in raw

    def test_gstin_in_extra_field_is_redacted(
        self, debug_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        debug_logger.debug("Invoice", extra={"gstin": VALID_GSTIN})

        payload = _parse(log_stream)
        assert payload["gstin"] == REDACTED
        assert VALID_GSTIN not in json.dumps(payload)

    def test_multiple_gstins_all_redacted(
        self, debug_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        msg = f"From {VALID_GSTIN} to {VALID_GSTIN_2}"
        debug_logger.debug(msg)

        raw = log_stream.getvalue()
        assert VALID_GSTIN not in raw
        assert VALID_GSTIN_2 not in raw
        assert raw.count(REDACTED) >= 2

    def test_output_is_valid_json_after_redaction(
        self, debug_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        debug_logger.debug("GSTIN: %s", VALID_GSTIN)
        payload = _parse(log_stream)  # must not raise
        assert payload["level"] == "DEBUG"


# ===========================================================================
# 2. Amount redaction at DEBUG level
# ===========================================================================


class TestAmountRedactionAtDebug:
    def test_plain_amount_redacted(
        self, debug_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        debug_logger.debug("Amount due: %s", AMOUNT_PLAIN)
        assert AMOUNT_PLAIN not in log_stream.getvalue()

    def test_rupee_symbol_amount_redacted(
        self, debug_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        debug_logger.debug("Total: %s", AMOUNT_SYMBOL)
        assert "1500.00" not in log_stream.getvalue()

    def test_rs_amount_redacted(
        self, debug_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        debug_logger.debug("Amount: %s", AMOUNT_RS)
        assert "250" not in log_stream.getvalue()

    def test_amount_in_extra_field_redacted(
        self, debug_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        debug_logger.debug("Invoice", extra={"amount": AMOUNT_PLAIN})
        payload = _parse(log_stream)
        assert payload["amount"] == REDACTED


# ===========================================================================
# 3. No redaction above DEBUG
# ===========================================================================


class TestNoRedactionAboveDebug:
    def test_gstin_survives_at_info(
        self, info_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        info_logger.info("GSTIN: %s", VALID_GSTIN)
        raw = log_stream.getvalue()
        assert VALID_GSTIN in raw, "GSTIN should NOT be redacted at INFO level"

    def test_amount_survives_at_info(
        self, info_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        info_logger.info("Amount: %s", AMOUNT_PLAIN)
        assert AMOUNT_PLAIN in log_stream.getvalue()


# ===========================================================================
# 4. JSON structure and mandatory fields
# ===========================================================================


class TestJsonStructure:
    def test_output_has_mandatory_fields(
        self, debug_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        debug_logger.debug("hello")
        payload = _parse(log_stream)

        for field in (
            "timestamp",
            "level",
            "logger",
            "message",
            "tenant_id",
            "trace_id",
        ):
            assert field in payload, f"Missing mandatory field: {field}"

    def test_level_field_is_correct(
        self, debug_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        debug_logger.debug("test")
        assert _parse(log_stream)["level"] == "DEBUG"

    def test_message_field_matches(
        self, debug_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        debug_logger.debug("specific message here")
        assert "specific message here" in _parse(log_stream)["message"]


# ===========================================================================
# 5. Context binding (tenant_id / trace_id)
# ===========================================================================


class TestContextBinding:
    def test_tenant_id_appears_in_log(
        self, debug_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        bind_context(tenant_id="tenant-abc")
        debug_logger.debug("hello")
        assert _parse(log_stream)["tenant_id"] == "tenant-abc"

    def test_trace_id_appears_in_log(
        self, debug_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        bind_context(trace_id="trace-xyz-999")
        debug_logger.debug("hello")
        assert _parse(log_stream)["trace_id"] == "trace-xyz-999"

    def test_both_context_vars_appear_together(
        self, debug_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        bind_context(tenant_id="T1", trace_id="R1")
        debug_logger.debug("hello")
        payload = _parse(log_stream)
        assert payload["tenant_id"] == "T1"
        assert payload["trace_id"] == "R1"

    def test_clear_context_resets_to_empty(
        self, debug_logger: logging.Logger, log_stream: StringIO
    ) -> None:
        bind_context(tenant_id="T1", trace_id="R1")
        clear_context()
        debug_logger.debug("hello")
        payload = _parse(log_stream)
        assert payload["tenant_id"] == ""
        assert payload["trace_id"] == ""


# ===========================================================================
# 6. configure_logging + get_logger integration
# ===========================================================================


class TestConfigureLogging:
    def test_configure_logging_does_not_raise(self) -> None:
        configure_logging(level="DEBUG")  # must not raise
        configure_logging(level="INFO")  # reset to INFO

    def test_get_logger_returns_logger_instance(self) -> None:
        logger = get_logger("itc.test")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "itc.test"

    def test_redaction_active_after_configure_debug(self, log_stream: StringIO) -> None:
        """
        End-to-end: after configure_logging(DEBUG), root logger redacts GSTINs.
        """
        configure_logging(level="DEBUG")
        root = logging.getLogger()
        # Redirect root's stream handler to our test stream
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler):
                h.stream = log_stream

        root.debug("GSTIN is %s", VALID_GSTIN)
        raw = log_stream.getvalue()
        assert VALID_GSTIN not in raw
