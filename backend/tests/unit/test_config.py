from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_missing_database_url_raises_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in [
        "DATABASE_URL",
        "REDIS_URL",
        "LLM_PROVIDER",
        "LLM_MODEL",
        "SMTP_HOST",
        "SMTP_PORT",
        "JWT_PUBLIC_KEY_PATH",
    ]:
        monkeypatch.delenv(var, raising=False)

    from itc.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]
