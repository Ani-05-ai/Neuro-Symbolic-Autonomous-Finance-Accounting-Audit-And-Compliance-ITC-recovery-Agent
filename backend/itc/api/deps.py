from functools import lru_cache

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from itc.core.config import Settings

JWT_ALGORITHM = "RS256"


@lru_cache
def _get_jwt_public_key() -> str:
    settings = Settings()
    with open(settings.jwt_public_key_path, "r") as f:
        return f.read()


def _extract_tenant_id(request: Request) -> str:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )

    token = auth_header.removeprefix("Bearer ")
    public_key = _get_jwt_public_key()

    try:
        payload = jwt.decode(token, public_key, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from exc

    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing tenant_id claim",
        )

    return tenant_id


async def get_tenant_context(request: Request, db: AsyncSession) -> str:
    """FastAPI dependency: decodes the JWT, extracts tenant_id, and sets
    it as the Postgres session-local setting that RLS policies check.

    Usage: any route touching the DB must declare this dependency:
        @router.get("/cases")
        async def list_cases(tenant_id: str = Depends(get_tenant_context), db=Depends(get_db)):
            ...
    """
    tenant_id = _extract_tenant_id(request)

    await db.execute(
        text("SET LOCAL app.tenant_id = :tenant_id"),
        {"tenant_id": tenant_id},
    )

    return tenant_id