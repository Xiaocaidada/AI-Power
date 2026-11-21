from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import ApiKey
from app.schemas import ApiKeyCreate, ApiKeyCreatedOut, ApiKeyOut
from app.security import generate_api_key
from app.services.quotas import enforce_key_creation

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]

DEFAULT_SCOPES = ("chat:write", "kb:read")
ALLOCATION_ATTEMPTS = 3


@router.post("", response_model=ApiKeyCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreate,
    context: JwtContext,
    session: SessionDep,
    redis: RedisDep,
) -> ApiKeyCreatedOut:
    await enforce_key_creation(session, context, redis)
    scopes = sorted(set(payload.scopes or DEFAULT_SCOPES))
    for _ in range(ALLOCATION_ATTEMPTS):
        raw_key, prefix, key_hash = generate_api_key()
        api_key = ApiKey(
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            name=payload.name,
            prefix=prefix,
            key_hash=key_hash,
            scopes=",".join(scopes),
            expires_at=payload.expires_at,
            rate_limit_per_minute=payload.rate_limit_per_minute,
        )
        session.add(api_key)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            continue
        await session.refresh(api_key)
        data = ApiKeyOut.model_validate(api_key).model_dump()
        return ApiKeyCreatedOut(**data, key=raw_key)

    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not allocate API key")


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(context: JwtContext, session: SessionDep) -> list[ApiKey]:
    result = await session.execute(
        select(ApiKey)
        .where(ApiKey.workspace_id == context.workspace.id)
        .order_by(ApiKey.created_at.desc())
    )
    return list(result.scalars())


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: UUID, context: JwtContext, session: SessionDep) -> Response:
    api_key = (
        await session.execute(
            select(ApiKey).where(
                ApiKey.id == key_id,
                ApiKey.workspace_id == context.workspace.id,
            )
        )
    ).scalar_one_or_none()
    if api_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")

    if api_key.revoked_at is None:
        api_key.revoked_at = datetime.now(UTC)
        await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
