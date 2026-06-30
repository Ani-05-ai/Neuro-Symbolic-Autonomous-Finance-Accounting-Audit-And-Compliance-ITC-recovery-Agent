"""Create tenant-scoped ITC schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "verdicts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verdict_type", sa.String(length=50), nullable=False),
        sa.Column("reason_chain", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("catalogue_version", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_verdicts_tenant_id"), "verdicts", ["tenant_id"], unique=False)

    op.create_table(
        "cases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vendor_gstin", sa.String(length=15), nullable=False),
        sa.Column("tax_period", sa.String(length=7), nullable=False),
        sa.Column("eligible_amount_inr", sa.Integer(), nullable=False),
        sa.Column(
            "case_status", sa.String(length=50), server_default=sa.text("'open'"), nullable=False
        ),
        sa.Column("priority_score", sa.Float(), server_default=sa.text("0.0"), nullable=False),
        sa.Column("verdict_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["verdict_id"], ["verdicts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cases_tenant_id"), "cases", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_cases_verdict_id"), "cases", ["verdict_id"], unique=False)

    op.create_table(
        "llm_trace",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task", sa.String(length=50), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("validation_passed", sa.Boolean(), nullable=False),
        sa.Column("validation_error", sa.Text(), nullable=True),
        sa.Column("retries", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_llm_trace_tenant_id"), "llm_trace", ["tenant_id"], unique=False)

    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_log_case_id"), "audit_log", ["case_id"], unique=False)
    op.create_index(op.f("ix_audit_log_tenant_id"), "audit_log", ["tenant_id"], unique=False)

    op.create_table(
        "outreach_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vendor_gstin", sa.String(length=15), nullable=False),
        sa.Column("channel", sa.String(length=50), nullable=False),
        sa.Column("recipient", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            sa.String(length=50),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_outreach_records_case_id"), "outreach_records", ["case_id"], unique=False
    )
    op.create_index(
        op.f("ix_outreach_records_tenant_id"), "outreach_records", ["tenant_id"], unique=False
    )

    op.create_table(
        "column_mappings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_column", sa.String(length=255), nullable=False),
        sa.Column("target_field", sa.String(length=100), nullable=False),
        sa.Column("transform", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "source_column",
            "target_field",
            name="uq_column_mappings_tenant_source_target",
        ),
    )
    op.create_index(
        op.f("ix_column_mappings_tenant_id"), "column_mappings", ["tenant_id"], unique=False
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_append_only_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only and cannot be updated or deleted', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
        """)
    op.execute("""
        CREATE TRIGGER trg_audit_log_append_only
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation()
        """)
    op.execute("""
        CREATE TRIGGER trg_llm_trace_append_only
        BEFORE UPDATE OR DELETE ON llm_trace
        FOR EACH ROW EXECUTE FUNCTION prevent_append_only_mutation()
        """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_llm_trace_append_only ON llm_trace")
    op.execute("DROP TRIGGER IF EXISTS trg_audit_log_append_only ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS prevent_append_only_mutation()")

    op.drop_index(op.f("ix_column_mappings_tenant_id"), table_name="column_mappings")
    op.drop_table("column_mappings")

    op.drop_index(op.f("ix_outreach_records_tenant_id"), table_name="outreach_records")
    op.drop_index(op.f("ix_outreach_records_case_id"), table_name="outreach_records")
    op.drop_table("outreach_records")

    op.drop_index(op.f("ix_audit_log_tenant_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_case_id"), table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_index(op.f("ix_llm_trace_tenant_id"), table_name="llm_trace")
    op.drop_table("llm_trace")

    op.drop_index(op.f("ix_cases_verdict_id"), table_name="cases")
    op.drop_index(op.f("ix_cases_tenant_id"), table_name="cases")
    op.drop_table("cases")

    op.drop_index(op.f("ix_verdicts_tenant_id"), table_name="verdicts")
    op.drop_table("verdicts")
