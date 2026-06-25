"""
Tests for the LLMGateway stub (Issue #10).

Acceptance criteria
-------------------
1. A single ``StubLLMGateway.call()`` writes **exactly one** ``LLMTrace``.
2. The returned value is a valid instance of the requested ``response_schema``.
3. The stub is swappable via the app factory (``create_app`` returns an
   ``AbstractLLMGateway``).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, TypeVar

import pytest
from pydantic import BaseModel

from itc.app import create_app
from itc.intelligence.gateway import AbstractLLMGateway, StubLLMGateway

if TYPE_CHECKING:
    from itc.intelligence.models import LLMTrace

S = TypeVar("S", bound=BaseModel)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class SampleSchema(BaseModel):
    """Minimal response schema used throughout the tests."""

    summary: str = "stub-summary"
    confidence: float = 0.0


@pytest.fixture
def gateway() -> StubLLMGateway:
    return StubLLMGateway()


# ---------------------------------------------------------------------------
# Core acceptance tests
# ---------------------------------------------------------------------------


class TestStubWritesExactlyOneTrace:
    def test_single_call_produces_one_trace(self, gateway: StubLLMGateway) -> None:
        """A single call must write exactly one LLMTrace record."""
        gateway.call(
            task="summarise",
            context={"doc": "hello world"},
            tenant_id="tenant-abc",
            response_schema=SampleSchema,
        )

        assert len(gateway.traces) == 1

    def test_two_calls_produce_two_traces(self, gateway: StubLLMGateway) -> None:
        """Each call appends its own independent trace."""
        for _ in range(2):
            gateway.call(
                task="summarise",
                context={},
                tenant_id="tenant-abc",
                response_schema=SampleSchema,
            )

        assert len(gateway.traces) == 2

    def test_trace_fields_match_call_args(self, gateway: StubLLMGateway) -> None:
        """The written trace must reflect the arguments passed to call()."""
        ctx = {"key": "value"}
        gateway.call(
            task="classify",
            context=ctx,
            tenant_id="tenant-xyz",
            response_schema=SampleSchema,
        )

        trace: LLMTrace = gateway.traces[0]
        assert trace.task == "classify"
        assert trace.context == ctx
        assert trace.tenant_id == "tenant-xyz"
        assert trace.response_schema_name == "SampleSchema"
        assert isinstance(trace.trace_id, uuid.UUID)
        assert trace.created_at is not None


class TestStubReturnsValidSchemaObject:
    def test_return_type_is_response_schema_instance(
        self, gateway: StubLLMGateway
    ) -> None:
        """The return value must be an instance of the supplied response_schema."""
        result = gateway.call(
            task="summarise",
            context={},
            tenant_id="t1",
            response_schema=SampleSchema,
        )

        assert isinstance(result, SampleSchema)

    def test_return_value_has_expected_defaults(self, gateway: StubLLMGateway) -> None:
        """Returned instance carries the schema's default field values."""
        result = gateway.call(
            task="summarise",
            context={},
            tenant_id="t1",
            response_schema=SampleSchema,
        )

        assert result.summary == "stub-summary"
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Dependency-injection / swappability tests
# ---------------------------------------------------------------------------


class TestGatewayIsSwappableViaAppFactory:
    def test_create_app_returns_abstract_gateway(self) -> None:
        """create_app() must expose an AbstractLLMGateway under 'llm_gateway'."""
        container = create_app()
        assert isinstance(container["llm_gateway"], AbstractLLMGateway)

    def test_stub_can_be_replaced_with_custom_impl(self) -> None:
        """A custom implementation can satisfy the abstract interface."""

        class RecordingGateway(AbstractLLMGateway):
            called: bool = False

            def call(
                self,
                task: str,
                context: dict[str, Any],
                tenant_id: str,
                response_schema: type[S],
            ) -> S:
                RecordingGateway.called = True
                return response_schema.model_construct()

            @property
            def traces(self) -> list[LLMTrace]:
                return []

        gw: AbstractLLMGateway = RecordingGateway()
        gw.call("t", {}, "tenant", SampleSchema)
        assert RecordingGateway.called
