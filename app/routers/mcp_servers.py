from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, require_admin
from app.models import AuditLog, McpServer
from app.schemas import (
    McpPromptOut,
    McpResourceOut,
    McpServerIn,
    McpServerOptionOut,
    McpServerOut,
    McpServerUpdate,
    McpToolOut,
)
from app.services.mcp import (
    McpError,
    list_mcp_prompts,
    list_mcp_resources,
    list_mcp_tools,
)
from app.services.outbound import OutboundError, validate_outbound_url
from app.services.provider_secrets import api_key_hint, encrypt_api_key

router = APIRouter(prefix="/mcp-servers", tags=["mcp"])
admin_router = APIRouter(prefix="/admin/mcp-servers", tags=["admin"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
AdminContext = Annotated[AuthContext, Depends(require_admin)]


def _out(server: McpServer) -> McpServerOut:
    return McpServerOut(
        id=server.id,
        name=server.name,
        description=server.description,
        endpoint_url=server.endpoint_url,
        enabled=server.enabled,
        timeout_seconds=server.timeout_seconds,
        auth_hint=server.auth_hint,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


def _validation_error(exc: OutboundError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"code": exc.code, "message": exc.message},
    )


async def _get_server(session: AsyncSession, server_id: UUID) -> McpServer:
    server = await session.get(McpServer, server_id)
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP server not found")
    return server


async def _ensure_unique_name(
    session: AsyncSession, name: str, exclude_id: UUID | None = None
) -> None:
    statement = select(McpServer.id).where(McpServer.name == name)
    if exclude_id is not None:
        statement = statement.where(McpServer.id != exclude_id)
    if (await session.execute(statement)).scalar_one_or_none() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "duplicate", "message": "MCP server name already exists"},
        )


@router.get("", response_model=list[McpServerOptionOut])
async def list_available_servers(
    context: JwtContext, session: SessionDep
) -> list[McpServerOptionOut]:
    rows = await session.execute(
        select(McpServer).where(McpServer.enabled.is_(True)).order_by(McpServer.name)
    )
    return [
        McpServerOptionOut(
            id=server.id, name=server.name, description=server.description
        )
        for server in rows.scalars()
    ]


@admin_router.get("", response_model=list[McpServerOut])
async def list_admin_servers(
    context: AdminContext, session: SessionDep
) -> list[McpServerOut]:
    rows = await session.execute(select(McpServer).order_by(McpServer.name))
    return [_out(server) for server in rows.scalars()]


@admin_router.post("", response_model=McpServerOut, status_code=status.HTTP_201_CREATED)
async def create_admin_server(
    payload: McpServerIn, context: AdminContext, session: SessionDep
) -> McpServerOut:
    try:
        await validate_outbound_url(payload.endpoint_url)
    except OutboundError as exc:
        raise _validation_error(exc) from None
    await _ensure_unique_name(session, payload.name)
    token = (payload.auth_token or "").strip()
    server = McpServer(
        name=payload.name,
        description=payload.description,
        endpoint_url=payload.endpoint_url,
        enabled=payload.enabled,
        timeout_seconds=payload.timeout_seconds,
        auth_token_encrypted=encrypt_api_key(token) if token else "",
        auth_hint=api_key_hint(token) if token else "",
    )
    session.add(server)
    await session.flush()
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="mcp_server.create",
            target_type="mcp_server",
            target_id=str(server.id),
            detail={"name": server.name},
        )
    )
    await session.commit()
    await session.refresh(server)
    return _out(server)


@admin_router.patch("/{server_id}", response_model=McpServerOut)
async def update_admin_server(
    server_id: UUID,
    payload: McpServerUpdate,
    context: AdminContext,
    session: SessionDep,
) -> McpServerOut:
    server = await _get_server(session, server_id)
    values = payload.model_dump(exclude_unset=True)
    if "endpoint_url" in values and values["endpoint_url"] is not None:
        try:
            await validate_outbound_url(values["endpoint_url"])
        except OutboundError as exc:
            raise _validation_error(exc) from None
    if "name" in values and values["name"] is not None:
        await _ensure_unique_name(session, values["name"], exclude_id=server.id)
    token = values.pop("auth_token", None)
    if token is not None:
        stripped = token.strip()
        server.auth_token_encrypted = encrypt_api_key(stripped) if stripped else ""
        server.auth_hint = api_key_hint(stripped) if stripped else ""
    for key, value in values.items():
        if value is not None:
            setattr(server, key, value)
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="mcp_server.update",
            target_type="mcp_server",
            target_id=str(server.id),
            detail={"name": server.name, "fields": sorted(values)},
        )
    )
    await session.commit()
    await session.refresh(server)
    return _out(server)


@admin_router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_server(
    server_id: UUID, context: AdminContext, session: SessionDep
) -> Response:
    server = await _get_server(session, server_id)
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="mcp_server.delete",
            target_type="mcp_server",
            target_id=str(server.id),
            detail={"name": server.name},
        )
    )
    await session.delete(server)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/{server_id}/tools", response_model=list[McpToolOut])
async def list_admin_server_tools(
    server_id: UUID, context: AdminContext, session: SessionDep
) -> list[McpToolOut]:
    server = await _get_server(session, server_id)
    try:
        tools = await list_mcp_tools(server)
    except McpError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            {"code": exc.code, "message": exc.message},
        ) from None
    return [
        McpToolOut(
            name=str(item.get("name", "")),
            description=str(item.get("description", "")),
            input_schema=item.get("input_schema")
            if isinstance(item.get("input_schema"), dict)
            else {},
        )
        for item in tools
    ]

@admin_router.get("/{server_id}/resources", response_model=list[McpResourceOut])
async def list_admin_server_resources(
    server_id: UUID, context: AdminContext, session: SessionDep
) -> list[McpResourceOut]:
    server = await _get_server(session, server_id)
    try:
        resources = await list_mcp_resources(server)
    except McpError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            {"code": exc.code, "message": exc.message},
        ) from None
    return [
        McpResourceOut(
            uri=str(item.get("uri", "")),
            name=str(item.get("name", "")),
            description=str(item.get("description", "")),
            mime_type=str(item.get("mime_type", "")),
        )
        for item in resources
    ]


@admin_router.get("/{server_id}/prompts", response_model=list[McpPromptOut])
async def list_admin_server_prompts(
    server_id: UUID, context: AdminContext, session: SessionDep
) -> list[McpPromptOut]:
    server = await _get_server(session, server_id)
    try:
        prompts = await list_mcp_prompts(server)
    except McpError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            {"code": exc.code, "message": exc.message},
        ) from None
    return [
        McpPromptOut(
            name=str(item.get("name", "")),
            description=str(item.get("description", "")),
            arguments=item.get("arguments") if isinstance(item.get("arguments"), list) else [],
        )
        for item in prompts
    ]
