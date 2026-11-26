from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, get_registry, require_admin
from app.providers.registry import ProviderRegistry
from app.schemas import (
    MarketModelActivateIn,
    MarketModelActivateOut,
    MarketModelCreate,
    MarketModelOut,
    MarketModelPageOut,
    MarketModelUpdate,
    MarketProviderOut,
)
from app.services.inner_models import (
    filter_inner_models,
    find_inner_model,
    load_inner_models,
    provider_catalog,
)
from app.services.market_models import (
    MarketModelError,
    activate_market_model,
    create_market_model,
    delete_market_model,
    get_market_model,
    get_market_model_by_id,
    list_market_models,
    update_market_model,
)
from app.services.provider_configs import ProviderConfigError

router = APIRouter(prefix="/market", tags=["market"])
admin_router = APIRouter(prefix="/admin/market", tags=["admin"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


def _available(provider_id: str, registry: ProviderRegistry) -> bool:
    return any(provider.id == provider_id for provider in registry.all())


def _out(model, registry: ProviderRegistry) -> MarketModelOut:
    return MarketModelOut(
        id=model.id,
        slug=model.slug,
        name=model.name,
        provider_id=model.provider_id,
        provider_name=model.provider_name,
        model_id=model.model_id,
        description=model.description,
        category=model.category,
        capabilities=list(model.capabilities),
        input_types=list(model.input_types),
        output_types=list(model.output_types),
        context_window=model.context_window,
        max_output=model.max_output,
        logo_url=model.logo_url,
        docs_url=model.docs_url,
        featured=model.featured,
        is_new=model.is_new,
        sort_order=model.sort_order,
        enabled=model.enabled,
        available=_available(model.provider_id, registry),
        catalog=False,
        provider_base_url="",
        thinking_supported=False,
        thinking_required=False,
        thinking_levels=[],
    )


def _inner_out(model) -> MarketModelOut:
    return MarketModelOut(
        id=model.id,
        slug=model.slug,
        name=model.name,
        provider_id=model.provider_id,
        provider_name=model.provider_name,
        model_id=model.model_id,
        description=model.description,
        category=model.category,
        capabilities=list(model.capabilities),
        input_types=list(model.input_types),
        output_types=list(model.output_types),
        context_window=model.context_window,
        max_output=model.max_output,
        logo_url="",
        docs_url=model.docs_url,
        featured=model.featured,
        is_new=model.is_new,
        sort_order=model.sort_order,
        enabled=True,
        available=False,
        catalog=True,
        provider_base_url=model.provider_base_url,
        thinking_supported=model.thinking_supported,
        thinking_required=model.thinking_required,
        thinking_levels=list(model.thinking_levels),
    )


def _sort_key(model: MarketModelOut, sort: str) -> tuple:
    if sort == "new":
        return (not model.is_new, not model.featured, model.sort_order, model.name)
    if sort == "name":
        return (model.name.lower(), model.provider_name.lower())
    return (not model.featured, model.sort_order, model.name)


def _config_error(exc: ProviderConfigError) -> HTTPException:
    if exc.code in {"provider_unreachable", "provider_http_error", "provider_bad_response"}:
        return HTTPException(
            status.HTTP_502_BAD_GATEWAY, {"code": exc.code, "message": exc.message}
        )
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"code": exc.code, "message": exc.message},
    )


@router.get("/providers", response_model=list[MarketProviderOut])
async def list_public_market_providers() -> list[MarketProviderOut]:
    return [
        MarketProviderOut(
            provider_id=item.provider_id,
            name=item.name,
            model_count=item.model_count,
            base_url=item.base_url,
            docs_url=item.docs_url,
        )
        for item in provider_catalog()
    ]


async def _collect_market_models(
    session: AsyncSession,
    *,
    search: str | None,
    category: str | None,
    capability: str | None,
    provider_id: str | None,
    input_type: str | None,
    output_type: str | None,
    sort: str,
    catalog: bool | None,
) -> list[MarketModelOut]:
    registry = get_registry()
    result: list[MarketModelOut] = []
    if catalog is not True:
        models = await list_market_models(
            session,
            search=search,
            category=category,
            capability=capability,
            provider_id=provider_id,
            input_type=input_type,
            output_type=output_type,
            sort=sort,
        )
        result = [_out(model, registry) for model in models]
    if catalog is not False:
        seen = {(item.provider_id, item.model_id) for item in result}
        for inner in filter_inner_models(
            load_inner_models(),
            search=search,
            category=category,
            capability=capability,
            provider_id=provider_id,
            input_type=input_type,
            output_type=output_type,
        ):
            if (inner.provider_id, inner.model_id) in seen:
                continue
            result.append(_inner_out(inner))
    result.sort(key=lambda item: _sort_key(item, sort))
    return result


@router.get("/models", response_model=list[MarketModelOut])
async def list_public_market_models(
    session: SessionDep,
    search: str | None = None,
    category: str | None = None,
    capability: str | None = None,
    provider_id: str | None = None,
    input_type: str | None = None,
    output_type: str | None = None,
    sort: Literal["featured", "new", "name"] = "featured",
    catalog: bool | None = None,
    limit: int | None = Query(default=None, ge=1, le=100),
) -> list[MarketModelOut]:
    result = await _collect_market_models(
        session,
        search=search,
        category=category,
        capability=capability,
        provider_id=provider_id,
        input_type=input_type,
        output_type=output_type,
        sort=sort,
        catalog=catalog,
    )
    return result[:limit] if limit is not None else result


@router.get("/models/page", response_model=MarketModelPageOut)
async def list_public_market_model_page(
    session: SessionDep,
    search: str | None = None,
    category: str | None = None,
    capability: str | None = None,
    provider_id: str | None = None,
    input_type: str | None = None,
    output_type: str | None = None,
    sort: Literal["featured", "new", "name"] = "featured",
    catalog: bool | None = None,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=24, ge=1, le=100),
) -> MarketModelPageOut:
    result = await _collect_market_models(
        session,
        search=search,
        category=category,
        capability=capability,
        provider_id=provider_id,
        input_type=input_type,
        output_type=output_type,
        sort=sort,
        catalog=catalog,
    )
    start = (page - 1) * per_page
    return MarketModelPageOut(
        items=result[start : start + per_page],
        total=len(result),
        page=page,
        per_page=per_page,
    )


@router.get("/models/{slug}", response_model=MarketModelOut)
async def get_public_market_model(slug: str, session: SessionDep) -> MarketModelOut:
    try:
        model = await get_market_model(session, slug)
    except MarketModelError as exc:
        inner = find_inner_model(slug)
        if inner is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
        return _inner_out(inner)
    return _out(model, get_registry())


@router.post("/models/{slug}/activate", response_model=MarketModelActivateOut)
async def activate_public_market_model(
    slug: str,
    payload: MarketModelActivateIn,
    context: JwtContext,
    session: SessionDep,
) -> MarketModelActivateOut:
    """Register a catalog model for the caller with their own key/base URL."""
    try:
        stored = await get_market_model(session, slug)
    except MarketModelError:
        stored = None
    inner = None if stored is not None else find_inner_model(slug)
    if stored is None and inner is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": "not_found", "message": "Market model not found"}
        )

    if inner is not None:
        provider_name = inner.provider_name
        model_id = inner.model_id
        display_name = inner.name
        capabilities = list(inner.capabilities)
        context_window = inner.context_window
        max_output = inner.max_output
        thinking_levels = list(inner.thinking_levels)
    else:
        provider_name = stored.provider_name
        model_id = stored.model_id
        display_name = stored.name
        capabilities = list(stored.capabilities)
        context_window = stored.context_window
        max_output = stored.max_output
        thinking_levels = []

    try:
        config, model = await activate_market_model(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            provider_name=payload.provider_name or provider_name,
            model_id=model_id,
            display_name=display_name,
            capabilities=capabilities,
            context_window=context_window,
            max_output=max_output,
            thinking_levels=thinking_levels,
            base_url=payload.base_url,
            api_key=payload.api_key,
        )
    except ProviderConfigError as exc:
        raise _config_error(exc) from None
    await session.commit()
    return MarketModelActivateOut(
        provider_id=config.id,
        model_id=model.model_id,
        name=model.display_name,
        provider_name=config.name,
    )


@admin_router.get("/models", response_model=list[MarketModelOut])
async def list_admin_market_models(
    context: Annotated[AuthContext, Depends(require_admin)],
    session: SessionDep,
) -> list[MarketModelOut]:
    registry = get_registry()
    return [
        _out(model, registry) for model in await list_market_models(session, include_disabled=True)
    ]


@admin_router.post("/models", response_model=MarketModelOut, status_code=status.HTTP_201_CREATED)
async def create_admin_market_model(
    payload: MarketModelCreate,
    context: Annotated[AuthContext, Depends(require_admin)],
    session: SessionDep,
) -> MarketModelOut:
    try:
        model = await create_market_model(session, payload.model_dump())
    except MarketModelError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from None
    await session.commit()
    await session.refresh(model)
    return _out(model, get_registry())


@admin_router.patch("/models/{model_id}", response_model=MarketModelOut)
async def update_admin_market_model(
    model_id: UUID,
    payload: MarketModelUpdate,
    context: Annotated[AuthContext, Depends(require_admin)],
    session: SessionDep,
) -> MarketModelOut:
    try:
        model = await get_market_model_by_id(session, model_id)
    except MarketModelError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    model = await update_market_model(session, model, payload.model_dump(exclude_unset=True))
    await session.commit()
    await session.refresh(model)
    return _out(model, get_registry())


@admin_router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_market_model(
    model_id: UUID,
    context: Annotated[AuthContext, Depends(require_admin)],
    session: SessionDep,
) -> Response:
    try:
        model = await get_market_model_by_id(session, model_id)
    except MarketModelError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    await delete_market_model(session, model)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
