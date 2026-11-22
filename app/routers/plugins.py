from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, require_admin
from app.models import PluginCall, PluginConfig, PluginDefinition
from app.schemas import (
    PluginCallOut,
    PluginConfigIn,
    PluginCreate,
    PluginOut,
    PluginUpdate,
)
from app.services.plugins import (
    PluginError,
    create_definition,
    delete_definition,
    get_definition,
    list_plugin_calls,
    list_plugin_rows,
    update_definition,
    upsert_workspace_config,
)

router = APIRouter(prefix="/plugins", tags=["plugins"])
admin_router = APIRouter(prefix="/admin/plugins", tags=["admin"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
AdminContext = Annotated[AuthContext, Depends(require_admin)]


def _plugin_out(
    definition: PluginDefinition, config: PluginConfig | None
) -> PluginOut:
    return PluginOut(
        id=definition.id,
        slug=definition.slug,
        name=definition.name,
        description=definition.description,
        category=definition.category,
        docs_url=definition.docs_url,
        endpoint_url=definition.endpoint_url,
        method=definition.method,
        auth_type=definition.auth_type,
        parameters=definition.parameters or {},
        sensitive=definition.sensitive,
        enabled=definition.enabled,
        timeout_seconds=definition.timeout_seconds,
        configured=config is not None,
        config_enabled=config.enabled if config is not None else False,
        credential_hint=config.credential_hint if config is not None else "",
        status=config.status if config is not None else "unconfigured",
        last_error=config.last_error if config is not None else None,
        last_checked_at=config.last_checked_at if config is not None else None,
    )


def _error(exc: PluginError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND
        if exc.code == "not_found"
        else status.HTTP_409_CONFLICT
        if exc.code == "duplicate"
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(code, {"code": exc.code, "message": exc.message})


@router.get("", response_model=list[PluginOut])
async def list_plugins(
    context: JwtContext, session: SessionDep
) -> list[PluginOut]:
    rows = await list_plugin_rows(session, context.workspace.id)
    return [_plugin_out(definition, config) for definition, config in rows]


@router.patch("/{plugin_id}", response_model=PluginOut)
async def configure_plugin(
    plugin_id: UUID,
    payload: PluginConfigIn,
    context: JwtContext,
    session: SessionDep,
) -> PluginOut:
    if context.role != "owner":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only the workspace owner can configure plugins",
        )
    try:
        definition = await get_definition(session, plugin_id)
    except PluginError as exc:
        raise _error(exc) from None
    config = await upsert_workspace_config(
        session,
        workspace_id=context.workspace.id,
        definition=definition,
        enabled=payload.enabled,
        credential=payload.credential,
        user_id=context.user.id,
    )
    await session.commit()
    await session.refresh(config)
    return _plugin_out(definition, config)


@router.get("/calls", response_model=list[PluginCallOut])
async def list_workspace_plugin_calls(
    context: JwtContext,
    session: SessionDep,
    conversation_id: UUID | None = None,
) -> list[PluginCall]:
    return await list_plugin_calls(session, context.workspace.id, conversation_id)


@admin_router.get("", response_model=list[PluginOut])
async def list_admin_plugins(
    context: AdminContext, session: SessionDep
) -> list[PluginOut]:
    definitions = list(
        (
            await session.execute(
                select(PluginDefinition).order_by(
                    PluginDefinition.category, PluginDefinition.name
                )
            )
        ).scalars()
    )
    return [_plugin_out(definition, None) for definition in definitions]


@admin_router.post("", response_model=PluginOut, status_code=status.HTTP_201_CREATED)
async def create_admin_plugin(
    payload: PluginCreate, context: AdminContext, session: SessionDep
) -> PluginOut:
    try:
        definition = await create_definition(session, payload.model_dump())
    except PluginError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(definition)
    return _plugin_out(definition, None)


@admin_router.patch("/{plugin_id}", response_model=PluginOut)
async def update_admin_plugin(
    plugin_id: UUID,
    payload: PluginUpdate,
    context: AdminContext,
    session: SessionDep,
) -> PluginOut:
    try:
        definition = await get_definition(session, plugin_id)
    except PluginError as exc:
        raise _error(exc) from None
    values = payload.model_dump(exclude_unset=True)
    for key in ("parameters", "endpoint_url", "slug"):
        if key in values and values[key] is None:
            values.pop(key)
    try:
        definition = await update_definition(session, definition, values)
    except PluginError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(definition)
    return _plugin_out(definition, None)


@admin_router.delete("/{plugin_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_plugin(
    plugin_id: UUID, context: AdminContext, session: SessionDep
) -> Response:
    try:
        definition = await get_definition(session, plugin_id)
    except PluginError as exc:
        raise _error(exc) from None
    await delete_definition(session, definition)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)