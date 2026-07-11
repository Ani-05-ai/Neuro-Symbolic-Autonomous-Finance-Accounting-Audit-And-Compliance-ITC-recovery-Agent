# itc/intelligence/ollama_gateway.py  (adjust path per what you find above)
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


class OllamaLLMGateway(AbstractLLMGateway):
    """Calls local Ollama/Mistral. Validates against response_schema;
    retries once with the validation error fed back into the prompt."""

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
        raw = self._generate(prompt)

        try:
            result = response_schema.model_validate_json(raw)
        except Exception as first_error:
            # retry once, feeding the validation error back
            retry_prompt = (
                f"{prompt}\n\nYour previous response was invalid: {first_error}\n"
                f"Return ONLY valid JSON matching the schema, nothing else."
            )
            raw = self._generate(retry_prompt)
            result = response_schema.model_validate_json(
                raw
            )  # let it raise if still bad

        self._traces.append(
            LLMTrace(
                tenant_id=tenant_id,
                task=task,
                context=context,
                response_schema_name=response_schema.__name__,
            )
        )
        return result

    @property
    def traces(self) -> list[LLMTrace]:
        return list(self._traces)

    def _build_prompt(self, task: str, context: dict[str, Any], schema: type[S]) -> str:
        return (
            f"Task: {task}\n"
            f"Context: {context}\n\n"
            f"Respond with ONLY valid JSON matching this schema: "
            f"{schema.model_json_schema()}\nNo prose, no markdown fences."
        )

    def _generate(self, prompt: str) -> str:
        resp = httpx.post(
            OLLAMA_URL,
            json={
                "model": self._model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=60,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return str(data["response"]).strip()
