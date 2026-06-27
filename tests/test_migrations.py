import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

EXPECTED_TABLES = {
    "cases",
    "verdicts",
    "llm_traces",
    "audit_logs",
    "outreach_records",
    "column_mappings",
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

        trigger_query = text("""
                        SELECT event_object_table, trigger_name
                        FROM information_schema.triggers
                        WHERE event_object_table IN ('audit_logs', 'llm_traces')
                        """)
        with engine.connect() as connection:
            triggers = {row for row in connection.execute(trigger_query)}

        assert ("audit_logs", "trg_audit_logs_append_only") in triggers
        assert ("llm_traces", "trg_llm_traces_append_only") in triggers
    finally:
        engine.dispose()
