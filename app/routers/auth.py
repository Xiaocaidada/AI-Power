from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.config import get_settings
from app.db import get_session
from app.deps import get_current_user
from app.models import RefreshToken, User
from app.schemas import LoginIn, RefreshTokenIn, RegisterIn, TokenOut, UserOut
from app.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.services.rate_limit import enforce_login_rate_limit
from app.services.workspaces import create_personal_workspace

router = APIRouter(prefix="/auth", tags=["auth"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]

_INVALID_CREDENTIALS = "Invalid email or password"
_INVALID_REFRESH = "Invalid refresh token"


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _issue_tokens(session: AsyncSession, user: User) -> TokenOut:
    settings = get_settings()
    raw_token, token_hash = generate_refresh_token()
    now = datetime.now(UTC)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    await session.commit()
    return TokenOut(
        access_token=create_access_token(user.id),
        expires_in=settings.access_token_ttl_minutes * 60,
        refresh_token=raw_token,
        refresh_expires_in=settings.refresh_token_ttl_days * 24 * 3600,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterIn, session: SessionDep) -> User:
    user = User(email=str(payload.email), password_hash=hash_password(payload.password))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from None
    await session.refresh(user)
    await create_personal_workspace(session, user)
    return user


@router.post("/login", response_model=TokenOut)
async def login(
    payload: LoginIn,
    request: Request,
    session: SessionDep,
    redis: RedisDep,
) -> TokenOut:
    await enforce_login_rate_limit(request, redis)

    result = await session.execute(select(User).where(User.email == str(payload.email)))
    user = result.scalar_one_or_none()
    if user is None:
        verify_password(payload.password, DUMMY_PASSWORD_HASH)
        raise _unauthorized(_INVALID_CREDENTIALS)
    if not verify_password(payload.password, user.password_hash):
        raise _unauthorized(_INVALID_CREDENTIALS)
    return await _issue_tokens(session, user)


@router.post("/refresh", response_model=TokenOut)
async def refresh(payload: RefreshTokenIn, session: SessionDep) -> TokenOut:
    stored = (
        await session.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == hash_refresh_token(payload.refresh_token)
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if stored is None or stored.revoked_at is not None or _as_utc(stored.expires_at) <= now:
        raise _unauthorized(_INVALID_REFRESH)

    settings = get_settings()
    raw_token, token_hash = generate_refresh_token()
    replacement = RefreshToken(
        user_id=stored.user_id,
        token_hash=token_hash,
        expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
    )
    session.add(replacement)
    await session.flush()

    rotation = await session.execute(
        update(RefreshToken)
        .where(RefreshToken.id == stored.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now, replaced_by_id=replacement.id)
    )
    if rotation.rowcount != 1:
        await session.rollback()
        raise _unauthorized(_INVALID_REFRESH)

    await session.commit()
    return TokenOut(
        access_token=create_access_token(stored.user_id),
        expires_in=settings.access_token_ttl_minutes * 60,
        refresh_token=raw_token,
        refresh_expires_in=settings.refresh_token_ttl_days * 24 * 3600,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshTokenIn, session: SessionDep) -> Response:
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == hash_refresh_token(payload.refresh_token),
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUser) -> User:
    return current_user
