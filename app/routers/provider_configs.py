from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import ProviderConfig, ProviderModel
from app.schemas import (
    PersonalModelOut,
    ProviderConfigCreate,
    ProviderConfigOut,
    ProviderConfigUpdate,
    ProviderModelCreate,
    ProviderModelOut,
    ProviderModelUpdate,
    ProviderSyncOut,
    ProviderTestOut,
    ThinkingLevelSpec,
)
from app.services.model_capabilities import effective_capabilities
from app.services.provider_configs import (
    ProviderConfigError,
    accessible_models,
    add_model,
    create_config,
    get_config,
    list_configs,
    list_models,
    sync_models,
    test_config,
    thinking_config_for,
    update_config,
    update_model,
)

router = APIRouter(prefix="/provider-configs", tags=["provider-configs"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


def _error(exc: ProviderConfigError) -> HTTPException:
    if exc.code == "not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    if exc.code == "model_exists":
        return HTTPException(status.HTTP_409_CONFLICT, {"code": exc.code, "message": exc.message})
    if exc.code in {"provider_unreachable", "provider_http_error", "provider_bad_response"}:
        return HTTPException(
            status.HTTP_502_BAD_GATEWAY, {"code": exc.code, "message": exc.message}
        )
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"code": exc.code, "message": exc.message},
    )


def _out(config: ProviderConfig, model_count: int, user_id: UUID) -> ProviderConfigOut:
    return ProviderConfigOut(
        id=config.id,
        name=config.name,
        provider_type=config.provider_type,
        base_url=config.base_url,
        api_key_hint=config.api_key_hint,
        note=config.note,
        shared=config.shared,
        owned=config.owner_user_id == user_id,
        status=config.status,
        last_error=config.last_error,
        last_tested_at=config.last_tested_at,
        model_count=model_count,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


def _model_out(model: ProviderModel) -> ProviderModelOut:
    capabilities = effective_capabilities(
        model.model_id, list(model.capabilities or []), model.source
    )
    return ProviderModelOut.model_validate(model).model_copy(
        update={
            "capabilities": capabilities,
            "thinking_config": [
                ThinkingLevelSpec(**item) for item in thinking_config_for(model)
            ],
        }
    )


@router.get("", response_model=list[ProviderConfigOut])
async def list_provider_configs(
    context: JwtContext, session: SessionDep
) -> list[ProviderConfigOut]:
    rows = await list_configs(session, context.workspace.id, context.user.id)
    return [_out(config, count, context.user.id) for config, count in rows]


@router.get("/models", response_model=list[PersonalModelOut])
async def list_personal_models(context: JwtContext, session: SessionDep) -> list[PersonalModelOut]:
    return [
        PersonalModelOut(**item)
        for item in await accessible_models(session, context.workspace.id, context.user.id)
    ]


@router.post("", response_model=ProviderConfigOut, status_code=status.HTTP_201_CREATED)
async def create_provider_config(
    payload: ProviderConfigCreate, context: JwtContext, session: SessionDep
) -> ProviderConfigOut:
    try:
        config = await create_config(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            name=payload.name,
            provider_type=payload.provider_type,
            base_url=payload.base_url,
            api_key=payload.api_key,
            note=payload.note,
            shared=payload.shared,
        )
    except ProviderConfigError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(config)
    return _out(config, 0, context.user.id)


@router.get("/{config_id}", response_model=ProviderConfigOut)
async def get_provider_config(
    config_id: UUID, context: JwtContext, session: SessionDep
) -> ProviderConfigOut:
    try:
        config = await get_config(session, config_id, context.workspace.id, context.user.id)
    except ProviderConfigError as exc:
        raise _error(exc) from None
    models = await list_models(session, config.id)
    return _out(config, len(models), context.user.id)


@router.patch("/{config_id}", response_model=ProviderConfigOut)
async def patch_provider_config(
    config_id: UUID,
    payload: ProviderConfigUpdate,
    context: JwtContext,
    session: SessionDep,
) -> ProviderConfigOut:
    try:
        config = await get_config(
            session, config_id, context.workspace.id, context.user.id, owner_only=True
        )
        config = await update_config(
            session,
            config,
            name=payload.name,
            base_url=payload.base_url,
            api_key=payload.api_key,
            note=payload.note,
            shared=payload.shared,
        )
    except ProviderConfigError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(config)
    models = await list_models(session, config.id)
    return _out(config, len(models), context.user.id)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_config(
    config_id: UUID, context: JwtContext, session: SessionDep
) -> Response:
    try:
        config = await get_config(
            session, config_id, context.workspace.id, context.user.id, owner_only=True
        )
    except ProviderConfigError as exc:
        raise _error(exc) from None
    config.deleted_at = datetime.now(UTC)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{config_id}/test", response_model=ProviderTestOut)
async def test_provider_config(
    config_id: UUID, context: JwtContext, session: SessionDep
) -> ProviderTestOut:
    try:
        config = await get_config(
            session, config_id, context.workspace.id, context.user.id, owner_only=True
        )
    except ProviderConfigError as exc:
        raise _error(exc) from None
    result = await test_config(session, config)
    await session.commit()
    return ProviderTestOut(**result)


@router.post("/{config_id}/sync", response_model=ProviderSyncOut)
async def sync_provider_models(
    config_id: UUID, context: JwtContext, session: SessionDep
) -> ProviderSyncOut:
    try:
        config = await get_config(
            session, config_id, context.workspace.id, context.user.id, owner_only=True
        )
        result = await sync_models(session, config)
    except ProviderConfigError as exc:
        await session.commit()
        raise _error(exc) from None
    await session.commit()
    return ProviderSyncOut(**result)


@router.get("/{config_id}/models", response_model=list[ProviderModelOut])
async def list_provider_models(
    config_id: UUID, context: JwtContext, session: SessionDep
) -> list[ProviderModelOut]:
    try:
        config = await get_config(session, config_id, context.workspace.id, context.user.id)
    except ProviderConfigError as exc:
        raise _error(exc) from None
    return [_model_out(model) for model in await list_models(session, config.id)]


@router.post(
    "/{config_id}/models",
    response_model=ProviderModelOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_provider_model(
    config_id: UUID,
    payload: ProviderModelCreate,
    context: JwtContext,
    session: SessionDep,
) -> ProviderModelOut:
    try:
        config = await get_config(
            session, config_id, context.workspace.id, context.user.id, owner_only=True
        )
        model = await add_model(
            session,
            config,
            model_id=payload.model_id,
            display_name=payload.display_name,
            capabilities=payload.capabilities,
            reasoning_levels=payload.reasoning_levels,
            thinking_config=payload.thinking_config,
            context_window=payload.context_window,
            max_output=payload.max_output,
        )
    except ProviderConfigError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(model)
    return _model_out(model)


@router.patch("/{config_id}/models/{model_id}", response_model=ProviderModelOut)
async def patch_provider_model(
    config_id: UUID,
    model_id: UUID,
    payload: ProviderModelUpdate,
    context: JwtContext,
    session: SessionDep,
) -> ProviderModelOut:
    try:
        config = await get_config(
            session, config_id, context.workspace.id, context.user.id, owner_only=True
        )
    except ProviderConfigError as exc:
        raise _error(exc) from None
    models = await list_models(session, config.id)
    model = next((item for item in models if item.id == model_id), None)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider model not found")
    model = await update_model(
        session,
        model,
        display_name=payload.display_name,
        capabilities=payload.capabilities,
        reasoning_levels=payload.reasoning_levels,
        thinking_config=payload.thinking_config,
        context_window=payload.context_window,
        max_output=payload.max_output,
        enabled=payload.enabled,
    )
    await session.commit()
    await session.refresh(model)
    return _model_out(model)


@router.delete("/{config_id}/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider_model(
    config_id: UUID,
    model_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> Response:
    try:
        config = await get_config(
            session, config_id, context.workspace.id, context.user.id, owner_only=True
        )
    except ProviderConfigError as exc:
        raise _error(exc) from None
    models = await list_models(session, config.id)
    model = next((item for item in models if item.id == model_id), None)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider model not found")
    await session.delete(model)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
