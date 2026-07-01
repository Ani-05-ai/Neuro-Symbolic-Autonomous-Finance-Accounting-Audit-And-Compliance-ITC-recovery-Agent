from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jose import jwt

from itc.api import deps


def _generate_key_pair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private_pem, public_pem


PRIVATE_KEY, PUBLIC_KEY = _generate_key_pair()


def _make_token(tenant_id: str) -> str:
    return jwt.encode({"tenant_id": tenant_id}, PRIVATE_KEY, algorithm="RS256")


@pytest.mark.asyncio
async def test_valid_jwt_sets_tenant_context_on_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = "11111111-1111-1111-1111-111111111111"
    token = _make_token(tenant_id)
    monkeypatch.setattr(deps, "_get_jwt_public_key", lambda: PUBLIC_KEY)

    mock_session = AsyncMock()
    mock_request = MagicMock()
    mock_request.headers = {"Authorization": f"Bearer {token}"}

    await deps.get_tenant_context(request=mock_request, db=mock_session)

    mock_session.execute.assert_called_once()
    call_args = mock_session.execute.call_args
    executed_sql = str(call_args[0][0])
    assert "SET LOCAL app.tenant_id" in executed_sql


async def test_missing_auth_header_raises_401() -> None:
    mock_session = AsyncMock()
    mock_request = MagicMock()
    mock_request.headers = {}

    with pytest.raises(HTTPException) as exc_info:
        await deps.get_tenant_context(request=mock_request, db=mock_session)

    assert exc_info.value.status_code == 401
    mock_session.execute.assert_not_called()
