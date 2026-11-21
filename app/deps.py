from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import AgentRegistry, build_agent_registry
from app.db import get_session
from app.models import User, Workspace, WorkspaceMember
from app.providers.registry import ProviderRegistry, build_registry
from app.security import decode_access_token
from app.services.api_keys import authenticate_api_key
from app.services.workspaces import resolve_workspace
from app.tools.base import ToolRegistry
from app.tools.registry import build_tool_registry

_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _workspace_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")


@dataclass(frozen=True, slots=True)
class AuthContext:
    user: User
    workspace: Workspace
    role: str
    scopes: frozenset[str] | None = None
    api_key_id: UUID | None = None
    api_key_rate_limit: int | None = None


def _parse_workspace_id(value: str | None) -> UUID | None:
    if value is None or value.strip() == "":
        return None
    try:
        return UUID(value.strip())
    except ValueError:
        raise _workspace_not_found() from None


def _stamp(request: Request, user: User, workspace: Workspace) -> None:
    request.state.user_id = str(user.id)
    request.state.workspace_id = str(workspace.id)


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


async def get_jwt_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
) -> AuthContext:
    """JWT-only authentication, resolving the active workspace from the header."""
    user = await _resolve_jwt(credentials, session)
    workspace, role = await resolve_workspace(session, user, _parse_workspace_id(x_workspace_id))
    _stamp(request, user, workspace)
    return AuthContext(user=user, workspace=workspace, role=role)


async def get_current_user(
    context: Annotated[AuthContext, Depends(get_jwt_context)],
) -> User:
    """JWT-only user for account management endpoints."""
    return context.user


async def get_auth_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-Id")] = None,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> AuthContext:
    if x_api_key:
        user, key, scopes = await authenticate_api_key(x_api_key, session)
        requested = _parse_workspace_id(x_workspace_id)
        if requested is not None and requested != key.workspace_id:
            raise _workspace_not_found()
        workspace = await session.get(Workspace, key.workspace_id)
        member = await session.get(
            WorkspaceMember, {"workspace_id": key.workspace_id, "user_id": user.id}
        )
        if workspace is None or member is None:
            raise _unauthorized()
        _stamp(request, user, workspace)
        return AuthContext(
            user=user,
            workspace=workspace,
            role=member.role,
            scopes=scopes,
            api_key_id=key.id,
            api_key_rate_limit=key.rate_limit_per_minute,
        )
    return await get_jwt_context(request, credentials, session, x_workspace_id)


def require_scope(scope: str):
    async def dependency(
        context: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> AuthContext:
        if context.scopes is not None and scope not in context.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "insufficient_scope",
                    "message": f"API key is missing scope: {scope}",
                },
            )
        return context

    return dependency


_registry: ProviderRegistry | None = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = build_registry()
    return _registry


def get_tool_registry() -> ToolRegistry:
    return build_tool_registry()


def get_agent_registry() -> AgentRegistry:
    return build_agent_registry()
