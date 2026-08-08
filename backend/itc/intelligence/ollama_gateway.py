# itc/intelligence/ollama_gateway.py
"""Real LLMGateway backed by local Ollama. Same contract as StubLLMGateway —
no call-site changes needed anywhere that already uses AbstractLLMGateway."""

from __future__ import annotations

from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from itc.intelligence.gateway import AbstractLLMGateway
from itc.intelligence.models import LLMTrace

S = TypeVar("S", bound=BaseModel)

OLLAMA_URL = "http://localhost:11434/api/generate"

# Local CPU-bound 7B inference can comfortably exceed a short timeout,
# especially for longer freeform generations (e.g. drafting an email body
# is a bigger task than a one-line explanation) or when the model has
# unloaded from memory between calls and needs to cold-load again.
GENERATE_TIMEOUT_SECONDS = 180

MAX_ATTEMPTS = 3  # 1 initial + 2 retries; schema-parroting is intermittent,
# not a hard prompt bug, so a couple of retries clears it in practice.
# Timeouts are retried too -- a slow response isn't a reason to kill the
# whole batch either.

# Keys that only appear in a JSON-Schema *meta*-object, never in a real
# instance of VerdictExplanation / VendorEmailDraft / etc. If the raw
# response contains these, Mistral echoed the schema instead of filling
# it in -- no need to even attempt pydantic validation first.
_SCHEMA_ECHO_MARKERS = (
    '"properties"',
    '"$defs"',
    '"type": "object"',
    "'type': 'object'",
)


class LLMSchemaParrotError(RuntimeError):
    """Raised after all retries are exhausted -- either because Ollama kept
    returning a schema-shaped echo instead of a valid instance, an
    otherwise-invalid response, or the request kept timing out. Callers
    (e.g. batch loops in demo_run.py) should catch this specifically and
    skip/log the item rather than let it crash the whole run -- these are
    known intermittent failure modes of small local models, not data/logic
    bugs. (Name kept as-is for now to avoid churn in already-written
    except clauses; consider renaming to LLMCallFailedError if this ever
    gets a wider audience.)"""

    def __init__(self, task: str, tenant_id: str, last_raw: str, attempts: int) -> None:
        self.task = task
        self.tenant_id = tenant_id
        self.last_raw = last_raw
        self.attempts = attempts
        super().__init__(
            f"Ollama failed to produce a valid '{task}' response after "
            f"{attempts} attempt(s). Last raw response: {last_raw[:200]!r}"
        )


class OllamaLLMGateway(AbstractLLMGateway):
    """Calls local Ollama/Mistral. Validates against response_schema;
    retries with a firmer, example-based prompt if the model echoes the
    schema or returns otherwise-invalid JSON. Never decides eligibility --
    only ever explains or drafts, per the neuro-symbolic invariant."""

    def __init__(self, model: str = "mistral") -> None:
        self._model = model
        self._traces: list[LLMTrace] = []

    def call(
        self,
        task: str,
        context: dict[str, Any],
        tenant_id: str,
        response_schema: type[S],
    ) -> S:
        prompt = self._build_prompt(task, context, response_schema)
        raw = ""
        last_error: Exception | None = None

        for _attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                raw = self._generate(prompt)
            except httpx.TimeoutException as exc:
                last_error = exc
                # Same prompt, no need to change wording -- just try again.
                # A timeout says nothing about prompt quality.
                continue

            if self._looks_like_schema_echo(raw):
                last_error = ValueError(
                    "response echoed the JSON schema instead of an instance"
                )
                prompt = self._build_retry_prompt(
                    task, context, response_schema, raw, schema_echo=True
                )
                continue

            try:
                result = response_schema.model_validate_json(raw)
            except Exception as exc:
                last_error = exc
                prompt = self._build_retry_prompt(
                    task, context, response_schema, raw, schema_echo=False
                )
                continue

            self._traces.append(
                LLMTrace(
                    tenant_id=tenant_id,
                    task=task,
                    context=context,
                    response_schema_name=response_schema.__name__,
                )
            )
            return result

        # Every attempt failed -- surface a typed error so callers can
        # skip this one item instead of the whole batch dying.
        raise LLMSchemaParrotError(task, tenant_id, raw, MAX_ATTEMPTS) from last_error

    @property
    def traces(self) -> list[LLMTrace]:
        return list(self._traces)

    def _build_prompt(self, task: str, context: dict[str, Any], schema: type[S]) -> str:
        example = self._example_json(schema)
        return (
            f"Task: {task}\n"
            f"Context: {context}\n\n"
            f"Reply with ONLY a JSON object shaped exactly like this example "
            f"(replace the example values with your real answer, keep the same keys):\n"
            f"{example}\n\n"
            f"Do not include the word 'schema', 'type', or 'properties' anywhere. "
            f"No prose, no markdown fences, no explanation of the format -- "
            f"just the filled-in JSON object."
        )

    def _build_retry_prompt(
        self,
        task: str,
        context: dict[str, Any],
        schema: type[S],
        bad_raw: str,
        *,
        schema_echo: bool,
    ) -> str:
        example = self._example_json(schema)
        if schema_echo:
            complaint = (
                "Your previous response was the JSON *schema* definition itself "
                "(it contained keys like 'properties' or 'type'). That is wrong. "
                "I need an actual filled-in example, not the schema."
            )
        else:
            complaint = (
                f"Your previous response was invalid JSON or missing "
                f"required fields: {bad_raw[:200]!r}"
            )

        return (
            f"Task: {task}\n"
            f"Context: {context}\n\n"
            f"{complaint}\n\n"
            f"Reply with ONLY this exact JSON shape, values filled in for real:\n"
            f"{example}\n\n"
            f"Nothing else -- no schema, no prose, no markdown fences."
        )

    @staticmethod
    def _looks_like_schema_echo(raw: str) -> bool:
        return any(marker in raw for marker in _SCHEMA_ECHO_MARKERS)

    @staticmethod
    def _example_json(schema: type[S]) -> dict[str, Any]:
        """Builds a placeholder *instance* of the schema (not the schema
        itself) so the model has a concrete example to mimic instead of
        a meta-description to parrot."""
        placeholders = {
            "string": "<your answer here>",
            "integer": 0,
            "number": 0.0,
            "boolean": True,
            "array": [],
            "object": {},
        }
        props = schema.model_json_schema().get("properties", {})
        example: dict[str, Any] = {}
        for field_name, field_schema in props.items():
            field_type = field_schema.get("type", "string")
            example[field_name] = placeholders.get(field_type, "<value>")
        return example

    def _generate(self, prompt: str) -> str:
        resp = httpx.post(
            OLLAMA_URL,
            json={
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "keep_alive": "10m",  # keep the model resident between calls
                # in a batch (default unload is ~5m idle) so later calls in
                # the same run don't pay the ~8s cold-load cost again.
            },
            timeout=GENERATE_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return str(data["response"]).strip()
