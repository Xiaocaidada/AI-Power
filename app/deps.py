from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import User
from app.providers.registry import ProviderRegistry, build_registry
from app.security import decode_access_token
from app.services.api_keys import authenticate_api_key

_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


@dataclass(frozen=True, slots=True)
class AuthContext:
    user: User
    scopes: frozenset[str] | None = None


async def _resolve_jwt(
    credentials: HTTPAuthorizationCredentials | None, session: AsyncSession
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        user_id = decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError:
        raise _unauthorized() from None
    user = await session.get(User, user_id)
    if user is None:
        raise _unauthorized()
    return user


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """JWT-only authentication for account management endpoints."""
    user = await _resolve_jwt(credentials, session)
    request.state.user_id = str(user.id)
    return user


async def get_auth_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> AuthContext:
    if x_api_key:
        user, scopes = await authenticate_api_key(x_api_key, session)
        request.state.user_id = str(user.id)
        return AuthContext(user=user, scopes=scopes)
    user = await _resolve_jwt(credentials, session)
    request.state.user_id = str(user.id)
    return AuthContext(user=user, scopes=None)


def require_scope(scope: str):
    async def dependency(
        context: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> User:
        if context.scopes is not None and scope not in context.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "insufficient_scope",
                    "message": f"API key is missing scope: {scope}",
                },
            )
        return context.user

    return dependency


_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = build_registry()
    return _registry
