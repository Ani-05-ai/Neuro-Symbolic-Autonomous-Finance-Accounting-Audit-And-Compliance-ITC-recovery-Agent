"""
LLMGateway — abstract contract + stub implementation.

Architecture
============
``AbstractLLMGateway`` defines the interface.  All callers depend on the
abstraction (dependency-injection friendly).  ``StubLLMGateway`` is the
concrete implementation shipped for M0: it returns a hardcoded valid instance
of ``response_schema`` and writes exactly **one** ``LLMTrace`` record before
returning.

Swapping in a real implementation later only requires changing what is bound
to ``AbstractLLMGateway`` in the app factory — no call-site changes needed.
"""

from __future__ import annotations

import abc
from typing import Any, Type, TypeVar

from pydantic import BaseModel

from itc.intelligence.models import LLMTrace

S = TypeVar("S", bound=BaseModel)


# ---------------------------------------------------------------------------
# Abstract contract
# ---------------------------------------------------------------------------


class AbstractLLMGateway(abc.ABC):
    """Dependency-injection contract for every LLM call in the system."""

    @abc.abstractmethod
    def call(
        self,
        task: str,
        context: dict[str, Any],
        tenant_id: str,
        response_schema: Type[S],
    ) -> S:
        """
        Parameters
        ----------
        task:
            Short string identifying the kind of work (e.g. ``"summarise"``).
        context:
            Arbitrary key/value pairs forwarded to the model as context.
        tenant_id:
            Identifies the calling tenant for billing / audit purposes.
        response_schema:
            A Pydantic ``BaseModel`` subclass.  The gateway MUST return a
            validated instance of this type.

        Returns
        -------
        S
            A valid, fully-populated instance of ``response_schema``.
        """

    @property
    @abc.abstractmethod
    def traces(self) -> list[LLMTrace]:
        """Read-only view of every trace written by this gateway instance."""


# ---------------------------------------------------------------------------
# Stub implementation (M0 — no real model calls)
# ---------------------------------------------------------------------------


class StubLLMGateway(AbstractLLMGateway):
    """
    Returns a hardcoded valid instance of ``response_schema`` by calling
    ``response_schema()`` with no arguments (all fields must therefore have
    defaults, *or* the schema must accept empty construction — callers are
    responsible for designing stubs-friendly schemas during M0).

    Writes exactly **one** ``LLMTrace`` record to an in-memory list before
    returning.  In production this list will be replaced by async DB writes.
    """

    def __init__(self) -> None:
        self._traces: list[LLMTrace] = []

    # ------------------------------------------------------------------
    # AbstractLLMGateway implementation
    # ------------------------------------------------------------------

    def call(
        self,
        task: str,
        context: dict[str, Any],
        tenant_id: str,
        response_schema: Type[S],
    ) -> S:
        # 1. Write trace BEFORE returning (audit-first pattern)
        trace = LLMTrace(
            tenant_id=tenant_id,
            task=task,
            context=context,
            response_schema_name=response_schema.__name__,
        )
        self._traces.append(trace)

        # 2. Return a hardcoded valid instance of the requested schema.
        #    ``model_construct`` skips validation intentionally — the *real*
        #    gateway will run full validation on the model's JSON output.
        return response_schema.model_construct()

    @property
    def traces(self) -> list[LLMTrace]:
        return list(self._traces)
