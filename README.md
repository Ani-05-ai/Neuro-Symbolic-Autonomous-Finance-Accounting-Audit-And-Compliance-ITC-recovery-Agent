# recoveritc
AI-powered GST reconciliation and ITC recovery system with deterministic rule engine, vendor compliance workflows, and end-to-end audit trails.

## Development

This project uses a `src/` package layout and keeps quality gates in `pyproject.toml`.

```bash
uv sync --group dev
uv run ruff check .
uv run black --check .
uv run mypy src tests
uv run pytest --cov
```

The GitHub Actions workflow runs on pushes to `main` and on all pull requests. It
uses `uv sync --frozen --group dev`, checks linting, formatting, typing, tests,
and enforces overall coverage of at least 85%.
