from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from jose import jwt

from itc.api.deps import get_tenant_context

with open("secrets/jwt_private.pem") as f:
    PRIVATE_KEY = f.read()


def _make_token(tenant_id: str) -> str:
    return jwt.encode({"tenant_id": tenant_id}, PRIVATE_KEY, algorithm="RS256")


@pytest.mark.asyncio
async def test_valid_jwt_sets_tenant_context_on_session() -> None:
    tenant_id = "11111111-1111-1111-1111-111111111111"
    token = _make_token(tenant_id)

    mock_session = AsyncMock()
    mock_request = MagicMock()
    mock_request.headers = {"Authorization": f"Bearer {token}"}

    await get_tenant_context(request=mock_request, db=mock_session)

    mock_session.execute.assert_called_once()
    call_args = mock_session.execute.call_args
    executed_sql = str(call_args[0][0])
    assert "SET LOCAL app.tenant_id" in executed_sql


async def test_missing_auth_header_raises_401() -> None:
    mock_session = AsyncMock()
    mock_request = MagicMock()
    mock_request.headers = {}

    with pytest.raises(HTTPException) as exc_info:
        await get_tenant_context(request=mock_request, db=mock_session)

    assert exc_info.value.status_code == 401
    mock_session.execute.assert_not_called()
