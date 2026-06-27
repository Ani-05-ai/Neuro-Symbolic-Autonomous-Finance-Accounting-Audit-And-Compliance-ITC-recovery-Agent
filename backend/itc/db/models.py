"""SQLAlchemy ORM models for the ITC recovery domain."""

from datetime import datetime
from typing import Any
from uuid import UUID as PythonUUID

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
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

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    vendor_gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    tax_period: Mapped[str] = mapped_column(String(7), nullable=False)
    eligible_amount_inr: Mapped[int] = mapped_column(Integer, nullable=False)
    case_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default=text("'open'"),
    )
    priority_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        server_default=text("0.0"),
    )
    verdict_id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("verdicts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


class Verdict(TenantScopedMixin, TimestampMixin, Base):
    """Decision recorded for a reconciliation case."""

    __tablename__ = "verdicts"

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    verdict_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reason_chain: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    catalogue_version: Mapped[str] = mapped_column(String(40), nullable=False)


class LLMTrace(TenantScopedMixin, Base):
    """Append-only trace of model calls used during reconciliation."""

    __tablename__ = "llm_trace"

    id: Mapped[PythonUUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    task: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    raw_output: Mapped[str | None] = mapped_column(Text)
    validation_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    validation_error: Mapped[str | None] = mapped_column(Text)
    retries: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )


class AuditLog(TenantScopedMixin, Base):
    """Append-only audit trail for user and system actions."""

    __tablename__ = "audit_log"

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
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
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
    vendor_gstin: Mapped[str] = mapped_column(String(15), nullable=False)
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
