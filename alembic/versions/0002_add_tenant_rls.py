"""Add tenant row-level security policies.

Revision ID: 0002_add_tenant_rls
Revises: 0001_initial_schema
Create Date: 2026-06-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_add_tenant_rls"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "recoveritc_app"
TENANT_SCOPED_TABLES = (
    "cases",
    "verdicts",
    "llm_traces",
    "audit_logs",
    "outreach_records",
    "column_mappings",
)


def upgrade() -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE}
                    NOLOGIN
                    NOBYPASSRLS;
            ELSE
                ALTER ROLE {APP_ROLE} NOLOGIN NOBYPASSRLS;
            END IF;

            EXECUTE format('GRANT %I TO %I', '{APP_ROLE}', CURRENT_USER);
        END
        $$
        """)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")

    for table_name in TENANT_SCOPED_TABLES:
        policy_name = f"{table_name}_tenant_isolation"
        op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table_name} TO {APP_ROLE}")
        op.execute(f"""
            CREATE POLICY {policy_name}
            ON {table_name}
            FOR ALL
            TO {APP_ROLE}
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
            """)


def downgrade() -> None:
    op.execute(f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                EXECUTE format('REVOKE %I FROM %I', '{APP_ROLE}', CURRENT_USER);
            END IF;
        END
        $$
        """)

    for table_name in reversed(TENANT_SCOPED_TABLES):
        policy_name = f"{table_name}_tenant_isolation"
        op.execute(f"DROP POLICY IF EXISTS {policy_name} ON {table_name}")
        op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {table_name} FROM {APP_ROLE}")
        op.execute(f"ALTER TABLE {table_name} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table_name} DISABLE ROW LEVEL SECURITY")

    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {APP_ROLE}")
