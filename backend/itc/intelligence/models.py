"""
LLM trace model — an in-memory record written for every gateway call.

In the real implementation this will be persisted to the DB via SQLAlchemy /
async session.  For the stub phase we keep it as a plain Pydantic model so the
test layer can inspect it without touching a database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class LLMTrace(BaseModel):
    """One record per LLMGateway.call() invocation."""

    trace_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    tenant_id: str
    task: str
    context: dict[str, Any]
    response_schema_name: str
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
