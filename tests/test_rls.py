import os
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

TENANT_A = UUID("00000000-0000-0000-0000-00000000000a")
TENANT_B = UUID("00000000-0000-0000-0000-00000000000b")
VERDICT_A = UUID("10000000-0000-0000-0000-00000000000a")
VERDICT_B = UUID("10000000-0000-0000-0000-00000000000b")
CASE_A = UUID("20000000-0000-0000-0000-00000000000a")
CASE_B = UUID("20000000-0000-0000-0000-00000000000b")
APP_ROLE = "recoveritc_app"
RLS_TABLES = {
    "cases",
    "verdicts",
    "llm_trace",
    "audit_log",
    "outreach_records",
    "column_mappings",
}


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for RLS tests")
    return database_url


def _upgrade_to_head(database_url: str) -> None:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "head")


def _seed_cases(owner_engine: Engine) -> None:
    with owner_engine.begin() as connection:
        connection.execute(text(f"SET ROLE {APP_ROLE}"))
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, false)"),
            {"tenant_id": str(TENANT_A)},
        )
        connection.execute(
            text("""
                INSERT INTO verdicts (
                    id,
                    tenant_id,
                    verdict_type,
                    reason_chain,
                    catalogue_version
                )
                VALUES (
                    :verdict_id,
                    :tenant_id,
                    'ineligible',
                    '[{"rule_id": "section_16_2_c", "passed": false}]'::jsonb,
                    'test-catalogue-version'
                )
                """),
            {"verdict_id": VERDICT_A, "tenant_id": TENANT_A},
        )
        connection.execute(
            text("""
                INSERT INTO cases (
                    id,
                    tenant_id,
                    vendor_gstin,
                    tax_period,
                    eligible_amount_inr,
                    verdict_id
                )
                VALUES (
                    :case_id,
                    :tenant_id,
                    '27ABCDE1234F1Z5',
                    '03/2025',
                    500,
                    :verdict_id
                )
                """),
            {"case_id": CASE_A, "tenant_id": TENANT_A, "verdict_id": VERDICT_A},
        )

        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, false)"),
            {"tenant_id": str(TENANT_B)},
        )
        connection.execute(
            text("""
                INSERT INTO verdicts (
                    id,
                    tenant_id,
                    verdict_type,
                    reason_chain,
                    catalogue_version
                )
                VALUES (
                    :verdict_id,
                    :tenant_id,
                    'eligible',
                    '[{"rule_id": "all_pass", "passed": true}]'::jsonb,
                    'test-catalogue-version'
                )
                """),
            {"verdict_id": VERDICT_B, "tenant_id": TENANT_B},
        )
        connection.execute(
            text("""
                INSERT INTO cases (
                    id,
                    tenant_id,
                    vendor_gstin,
                    tax_period,
                    eligible_amount_inr,
                    verdict_id
                )
                VALUES (
                    :case_id,
                    :tenant_id,
                    '29ABCDE1234F1Z5',
                    '03/2025',
                    700,
                    :verdict_id
                )
                """),
            {"case_id": CASE_B, "tenant_id": TENANT_B, "verdict_id": VERDICT_B},
        )


def test_rls_policies_are_enabled_and_forced_on_tenant_tables() -> None:
    database_url = _database_url()
    _upgrade_to_head(database_url)

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert tables >= RLS_TABLES

        with engine.connect() as connection:
            rows = connection.execute(
                text("""
                    SELECT
                        relname,
                        relrowsecurity,
                        relforcerowsecurity
                    FROM pg_class
                    WHERE relname = ANY(:table_names)
                    """),
                {"table_names": list(RLS_TABLES)},
            ).mappings()

            rls_state = {row["relname"]: row for row in rows}

        assert set(rls_state) == RLS_TABLES
        for table_name, row in rls_state.items():
            assert row["relrowsecurity"], f"{table_name} should have RLS enabled"
            assert row["relforcerowsecurity"], f"{table_name} should force RLS"
    finally:
        engine.dispose()


def test_app_role_query_without_tenant_where_is_limited_to_current_tenant() -> None:
    database_url = _database_url()
    _upgrade_to_head(database_url)

    owner_engine = create_engine(database_url)
    try:
        _seed_cases(owner_engine)

        with owner_engine.connect() as connection:
            connection.execute(text(f"SET ROLE {APP_ROLE}"))
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, false)"),
                {"tenant_id": str(TENANT_A)},
            )
            visible_cases = connection.execute(
                text("SELECT vendor_gstin FROM cases ORDER BY vendor_gstin")
            ).scalars()

            assert list(visible_cases) == ["27ABCDE1234F1Z5"]

            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, false)"),
                {"tenant_id": str(TENANT_B)},
            )
            visible_cases = connection.execute(
                text("SELECT vendor_gstin FROM cases ORDER BY vendor_gstin")
            ).scalars()

            assert list(visible_cases) == ["29ABCDE1234F1Z5"]
    finally:
        owner_engine.dispose()


def test_app_role_cannot_bypass_rls() -> None:
    database_url = _database_url()
    _upgrade_to_head(database_url)

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            role = (
                connection.execute(
                    text("""
                    SELECT
                        rolbypassrls,
                        rolcanlogin
                    FROM pg_roles
                    WHERE rolname = :role_name
                    """),
                    {"role_name": APP_ROLE},
                )
                .mappings()
                .one()
            )

        assert role["rolbypassrls"] is False
        assert role["rolcanlogin"] is False
    finally:
        engine.dispose()


def test_append_only_tables_reject_update_and_delete() -> None:
    database_url = _database_url()
    _upgrade_to_head(database_url)

    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(f"SET ROLE {APP_ROLE}"))
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant_id, false)"),
                {"tenant_id": str(TENANT_A)},
            )
            connection.execute(
                text("""
                    INSERT INTO llm_trace (
                        tenant_id,
                        task,
                        prompt,
                        raw_output,
                        validation_passed
                    )
                    VALUES (
                        :tenant_id,
                        'extract',
                        'prompt',
                        '{}',
                        true
                    )
                    """),
                {"tenant_id": TENANT_A},
            )
            connection.execute(
                text("""
                    INSERT INTO audit_log (
                        tenant_id,
                        action,
                        details,
                        created_by
                    )
                    VALUES (
                        :tenant_id,
                        'verdict',
                        '{}'::jsonb,
                        'test-user'
                    )
                    """),
                {"tenant_id": TENANT_A},
            )

        _assert_dbapi_error(engine, "UPDATE llm_trace SET retries = retries + 1")
        _assert_dbapi_error(engine, "DELETE FROM llm_trace")
        _assert_dbapi_error(engine, "UPDATE audit_log SET action = 'dispatch'")
        _assert_dbapi_error(engine, "DELETE FROM audit_log")
    finally:
        engine.dispose()


def _assert_dbapi_error(engine: Engine, statement: str) -> None:
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text(f"SET ROLE {APP_ROLE}"))
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tenant_id, false)"),
            {"tenant_id": str(TENANT_A)},
        )
        with pytest.raises(DBAPIError):
            connection.execute(text(statement))
        transaction.rollback()
