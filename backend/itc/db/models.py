"""SQLAlchemy ORM models for the ITC recovery domain."""

from datetime import datetime
from typing import Any
from uuid import UUID as PythonUUID

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base metadata registry for Alembic autogeneration."""


class TenantScopedMixin:
    """Columns shared by every tenant-owned table."""

    tenant_id: Mapped[PythonUUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)


class TimestampMixin:
    """Creation and update timestamps maintained by the database/application."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class Case(TenantScopedMixin, TimestampMixin, Base):
    """A GST reconciliation case opened for a purchase invoice."""

    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "case_reference",
            name="uq_cases_tenant_case_reference",
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    case_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    supplier_gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'open'"))


class Verdict(TenantScopedMixin, TimestampMixin, Base):
    """Decision recorded for a reconciliation case."""

    __tablename__ = "verdicts"

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    case_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    outcome: Mapped[str] = mapped_column(String(50), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text)


class LLMTrace(TenantScopedMixin, Base):
    """Append-only trace of model calls used during reconciliation."""

    __tablename__ = "llm_traces"

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    case_id: Mapped[PythonUUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cases.id", ondelete="SET NULL"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    response_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class AuditLog(TenantScopedMixin, Base):
    """Append-only audit trail for user and system actions."""

    __tablename__ = "audit_logs"

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    actor_id: Mapped[PythonUUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[PythonUUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class OutreachRecord(TenantScopedMixin, TimestampMixin, Base):
    """Supplier outreach attempt connected to a reconciliation case."""

    __tablename__ = "outreach_records"

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    case_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    supplier_gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default=text("'pending'")
    )


class ColumnMapping(TenantScopedMixin, TimestampMixin, Base):
    """Tenant-specific import column mapping for invoice files."""

    __tablename__ = "column_mappings"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_column",
            "target_field",
            name="uq_column_mappings_tenant_source_target",
        ),
    )

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    source_column: Mapped[str] = mapped_column(String(255), nullable=False)
    target_field: Mapped[str] = mapped_column(String(100), nullable=False)
    transform: Mapped[str | None] = mapped_column(String(255))
