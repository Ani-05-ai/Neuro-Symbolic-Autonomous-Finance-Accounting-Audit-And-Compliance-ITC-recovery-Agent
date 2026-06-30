# recoveritc
AI-powered GST reconciliation and ITC recovery system with deterministic rule engine, vendor compliance workflows, and end-to-end audit trails.

## Development

This project uses a `src/` package layout and keeps quality gates in `pyproject.toml`.

```bash
uv sync --group dev
uv run ruff check .
uv run black --check .
uv run mypy src backend tests
uv run pytest --cov
```

The GitHub Actions workflow runs on pushes to `main` and on all pull requests. It
uses `uv sync --frozen --group dev`, checks linting, formatting, typing, tests,
and enforces overall coverage of at least 85%.

## Database Migrations

Alembic migrations live in `alembic/`, and SQLAlchemy ORM models live in
`backend/itc/db/models.py`.

To run the migration test against Postgres, set `DATABASE_URL` before running
pytest:

```bash
DATABASE_URL=postgresql+psycopg://recoveritc:recoveritc@localhost:5432/recoveritc_test uv run pytest --cov
```

CI provides this database automatically with a Postgres service container.
