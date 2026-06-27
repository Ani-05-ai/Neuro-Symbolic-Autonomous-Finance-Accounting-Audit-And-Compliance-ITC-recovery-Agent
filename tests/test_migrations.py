import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

EXPECTED_TABLES = {
    "cases",
    "verdicts",
    "llm_trace",
    "audit_log",
    "outreach_records",
    "column_mappings",
}

EXPECTED_COLUMNS = {
    "cases": {
        "tenant_id",
        "vendor_gstin",
        "tax_period",
        "eligible_amount_inr",
        "case_status",
        "priority_score",
        "verdict_id",
    },
    "verdicts": {"tenant_id", "verdict_type", "reason_chain", "catalogue_version"},
    "llm_trace": {
        "tenant_id",
        "task",
        "prompt",
        "raw_output",
        "validation_passed",
        "validation_error",
        "retries",
    },
    "audit_log": {"tenant_id", "case_id", "action", "details", "created_by"},
    "outreach_records": {"tenant_id", "case_id", "vendor_gstin", "channel", "recipient", "status"},
    "column_mappings": {"tenant_id", "source_column", "target_field", "transform"},
}


def _database_url() -> str:
    database_url = os.getenv("DATABASE_URL")
    if database_url is None:
        pytest.skip("DATABASE_URL is required for migration tests")
    return database_url


def test_alembic_upgrade_head_creates_initial_schema() -> None:
    database_url = _database_url()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)

    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())

        assert table_names >= EXPECTED_TABLES

        for table_name in EXPECTED_TABLES:
            columns = {column["name"]: column for column in inspector.get_columns(table_name)}
            assert "tenant_id" in columns
            assert columns["tenant_id"]["nullable"] is False
            assert set(columns) >= EXPECTED_COLUMNS[table_name]

        case_foreign_keys = inspector.get_foreign_keys("cases")
        assert any(
            foreign_key["referred_table"] == "verdicts"
            and foreign_key["constrained_columns"] == ["verdict_id"]
            for foreign_key in case_foreign_keys
        )

        trigger_query = text("""
                        SELECT event_object_table, trigger_name
                        FROM information_schema.triggers
                        WHERE event_object_table IN ('audit_log', 'llm_trace')
                        """)
        with engine.connect() as connection:
            triggers = {row for row in connection.execute(trigger_query)}

        assert ("audit_log", "trg_audit_log_append_only") in triggers
        assert ("llm_trace", "trg_llm_trace_append_only") in triggers
    finally:
        engine.dispose()
