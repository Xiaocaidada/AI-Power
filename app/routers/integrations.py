from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import ExternalCall, IntegrationConfig
from app.schemas import (
    ExternalCallOut,
    IntegrationConfigCreate,
    IntegrationConfigOut,
    IntegrationConfigUpdate,
    IntegrationTestOut,
)
from app.services.integrations import (
    IntegrationError,
    create_config,
    delete_config,
    get_config,
    list_configs,
    set_default,
    test_config,
    update_config,
)

router = APIRouter(prefix="/integrations", tags=["integrations"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


def _error(exc: IntegrationError) -> HTTPException:
    if exc.code == "not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    if exc.code == "forbidden":
        return HTTPException(status.HTTP_403_FORBIDDEN, {"code": exc.code, "message": exc.message})
    if exc.code in {
        "integration_timeout",
        "integration_unreachable",
        "integration_upstream_error",
        "integration_rate_limited",
        "integration_auth_failed",
        "integration_bad_response",
        "integration_response_too_large",
    }:
        return HTTPException(
            status.HTTP_502_BAD_GATEWAY, {"code": exc.code, "message": exc.message}
        )
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"code": exc.code, "message": exc.message},
    )


def _out(config: IntegrationConfig, user_id: UUID) -> IntegrationConfigOut:
    return IntegrationConfigOut(
        id=config.id,
        kind=config.kind,
        provider=config.provider,
        name=config.name,
        base_url=config.base_url,
        auth_type=config.auth_type,
        credential_hint=config.credential_hint,
        model=config.model,
        options=config.options or {},
        shared=config.shared,
        enabled=config.enabled,
        is_default=config.is_default,
        owned=config.owner_user_id == user_id,
        status=config.status,
        last_error=config.last_error,
        last_tested_at=config.last_tested_at,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.get("/calls", response_model=list[ExternalCallOut])
async def list_external_calls(
    context: JwtContext,
    session: SessionDep,
    kind: str | None = None,
    integration_id: UUID | None = None,
    limit: int = 50,
) -> list[ExternalCallOut]:
    conditions = [ExternalCall.workspace_id == context.workspace.id]
    if kind is not None:
        conditions.append(ExternalCall.kind == kind)
    if integration_id is not None:
        conditions.append(ExternalCall.integration_id == integration_id)
    rows = list(
        (
            await session.execute(
                select(ExternalCall)
                .where(*conditions)
                .order_by(ExternalCall.created_at.desc(), ExternalCall.id.desc())
                .limit(max(1, min(limit, 100)))
            )
        ).scalars()
    )
    return [
        ExternalCallOut(
            id=row.id,
            integration_id=row.integration_id,
            kind=row.kind,
            provider=row.provider,
            operation=row.operation,
            status=row.status,
            error_code=row.error_code,
            duration_ms=row.duration_ms,
            units=row.units,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("", response_model=list[IntegrationConfigOut])
async def list_integrations(
    context: JwtContext, session: SessionDep, kind: str | None = None
) -> list[IntegrationConfigOut]:
    try:
        rows = await list_configs(session, context.workspace.id, context.user.id, kind)
    except IntegrationError as exc:
        raise _error(exc) from None
    return [_out(row, context.user.id) for row in rows]


@router.post("", response_model=IntegrationConfigOut, status_code=status.HTTP_201_CREATED)
async def create_integration(
    payload: IntegrationConfigCreate, context: JwtContext, session: SessionDep
) -> IntegrationConfigOut:
    try:
        config = await create_config(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            kind=payload.kind,
            provider=payload.provider,
            name=payload.name,
            base_url=payload.base_url,
            credential=payload.credential,
            model=payload.model,
            options=payload.options,
            shared=payload.shared,
            enabled=payload.enabled,
        )
    except IntegrationError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(config)
    return _out(config, context.user.id)


@router.get("/{config_id}", response_model=IntegrationConfigOut)
async def read_integration(
    config_id: UUID, context: JwtContext, session: SessionDep
) -> IntegrationConfigOut:
    try:
        config = await get_config(
            session, config_id, context.workspace.id, context.user.id
        )
    except IntegrationError as exc:
        raise _error(exc) from None
    return _out(config, context.user.id)


@router.patch("/{config_id}", response_model=IntegrationConfigOut)
async def patch_integration(
    config_id: UUID,
    payload: IntegrationConfigUpdate,
    context: JwtContext,
    session: SessionDep,
) -> IntegrationConfigOut:
    try:
        config = await get_config(
            session, config_id, context.workspace.id, context.user.id, owner_only=True
        )
        config = await update_config(
            session,
            config,
            name=payload.name,
            base_url=payload.base_url,
            credential=payload.credential,
            model=payload.model,
            options=payload.options,
            shared=payload.shared,
            enabled=payload.enabled,
            is_default=payload.is_default,
        )
    except IntegrationError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(config)
    return _out(config, context.user.id)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_integration(
    config_id: UUID, context: JwtContext, session: SessionDep
) -> None:
    try:
        config = await get_config(
            session, config_id, context.workspace.id, context.user.id, owner_only=True
        )
        await delete_config(session, config)
    except IntegrationError as exc:
        raise _error(exc) from None
    await session.commit()


@router.post("/{config_id}/test", response_model=IntegrationTestOut)
async def test_integration(
    config_id: UUID, context: JwtContext, session: SessionDep
) -> IntegrationTestOut:
    try:
        config = await get_config(
            session, config_id, context.workspace.id, context.user.id, owner_only=True
        )
        result = await test_config(config)
    except IntegrationError as exc:
        raise _error(exc) from None
    await session.commit()
    return IntegrationTestOut(**result)


@router.post("/{config_id}/default", response_model=IntegrationConfigOut)
async def make_integration_default(
    config_id: UUID, context: JwtContext, session: SessionDep
) -> IntegrationConfigOut:
    try:
        config = await get_config(
            session, config_id, context.workspace.id, context.user.id, owner_only=True
        )
        config = await set_default(session, config)
    except IntegrationError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(config)
    return _out(config, context.user.id)