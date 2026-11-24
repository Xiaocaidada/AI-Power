from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import SearchProviderConfig
from app.schemas import (
    SearchProviderCreate,
    SearchProviderOut,
    SearchProviderTestOut,
    SearchProviderUpdate,
)
from app.services.search_providers import (
    SearchProviderError,
    create_config,
    delete_config,
    get_config,
    list_configs,
    set_default,
    test_config,
    update_config,
)

router = APIRouter(prefix="/search-providers", tags=["search-providers"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


def _error(exc: SearchProviderError) -> HTTPException:
    if exc.code == "not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    if exc.code == "provider_disabled":
        return HTTPException(status.HTTP_409_CONFLICT, {"code": exc.code, "message": exc.message})
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"code": exc.code, "message": exc.message},
    )


def _out(config: SearchProviderConfig, user_id: UUID) -> SearchProviderOut:
    return SearchProviderOut(
        id=config.id,
        provider=config.provider,
        name=config.name,
        base_url=config.base_url,
        api_key_hint=config.api_key_hint,
        max_results=config.max_results,
        timeout_seconds=config.timeout_seconds,
        enabled=config.enabled,
        shared=config.shared,
        is_default=config.is_default,
        owned=config.owner_user_id == user_id,
        status=config.status,
        last_error=config.last_error,
        last_tested_at=config.last_tested_at,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )


@router.get("", response_model=list[SearchProviderOut])
async def list_search_providers(
    context: JwtContext, session: SessionDep
) -> list[SearchProviderOut]:
    rows = await list_configs(session, context.workspace.id, context.user.id)
    return [_out(row, context.user.id) for row in rows]


@router.post("", response_model=SearchProviderOut, status_code=status.HTTP_201_CREATED)
async def create_search_provider(
    payload: SearchProviderCreate,
    context: JwtContext,
    session: SessionDep,
) -> SearchProviderOut:
    try:
        config = await create_config(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            provider=payload.provider,
            name=payload.name,
            base_url=payload.base_url,
            api_key=payload.api_key,
            max_results=payload.max_results,
            timeout_seconds=payload.timeout_seconds,
            shared=payload.shared,
            enabled=payload.enabled,
        )
    except SearchProviderError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(config)
    return _out(config, context.user.id)


@router.patch("/{config_id}", response_model=SearchProviderOut)
async def patch_search_provider(
    config_id: UUID,
    payload: SearchProviderUpdate,
    context: JwtContext,
    session: SessionDep,
) -> SearchProviderOut:
    try:
        config = await get_config(
            session,
            config_id,
            context.workspace.id,
            context.user.id,
            owner_only=True,
        )
        config = await update_config(session, config, **payload.model_dump(exclude_unset=True))
    except SearchProviderError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(config)
    return _out(config, context.user.id)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_search_provider(
    config_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> Response:
    try:
        config = await get_config(
            session,
            config_id,
            context.workspace.id,
            context.user.id,
            owner_only=True,
        )
        await delete_config(session, config)
    except SearchProviderError as exc:
        raise _error(exc) from None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{config_id}/test", response_model=SearchProviderTestOut)
async def test_search_provider(
    config_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> SearchProviderTestOut:
    try:
        config = await get_config(
            session,
            config_id,
            context.workspace.id,
            context.user.id,
            owner_only=True,
        )
    except SearchProviderError as exc:
        raise _error(exc) from None
    result = await test_config(config)
    await session.commit()
    return SearchProviderTestOut(**result)


@router.post("/{config_id}/default", response_model=SearchProviderOut)
async def make_search_provider_default(
    config_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> SearchProviderOut:
    try:
        config = await get_config(
            session,
            config_id,
            context.workspace.id,
            context.user.id,
            owner_only=True,
        )
        config = await set_default(session, config)
    except SearchProviderError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(config)
    return _out(config, context.user.id)
