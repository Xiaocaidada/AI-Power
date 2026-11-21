import hmac
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiKey, User
from app.security import hash_api_key

LAST_USED_UPDATE_INTERVAL = timedelta(seconds=60)
PREFIX_LENGTH = 11  # "ap_" + 8 hex characters


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API key",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def authenticate_api_key(
    raw_key: str, session: AsyncSession
) -> tuple[User, ApiKey, frozenset[str]]:
    if len(raw_key) <= PREFIX_LENGTH or not raw_key.startswith("ap_"):
        raise _unauthorized()

    prefix = raw_key[:PREFIX_LENGTH]
    stored = (
        await session.execute(select(ApiKey).where(ApiKey.prefix == prefix))
    ).scalar_one_or_none()
    if stored is None or stored.revoked_at is not None:
        raise _unauthorized()
    if not hmac.compare_digest(stored.key_hash, hash_api_key(raw_key)):
        raise _unauthorized()

    user = await session.get(User, stored.user_id)
    if user is None:
        raise _unauthorized()

    now = datetime.now(UTC)
    if (
        stored.last_used_at is None
        or _as_utc(stored.last_used_at) < now - LAST_USED_UPDATE_INTERVAL
    ):
        stored.last_used_at = now
        await session.commit()

    scopes = frozenset(scope for scope in stored.scopes.split(",") if scope)
    return user, stored, scopes
