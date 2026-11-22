from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_registry, require_admin
from app.providers.registry import ProviderRegistry
from app.schemas import MarketModelCreate, MarketModelOut, MarketModelUpdate
from app.services.market_models import (
    MarketModelError,
    create_market_model,
    delete_market_model,
    get_market_model,
    get_market_model_by_id,
    list_market_models,
    update_market_model,
)

router = APIRouter(prefix="/market", tags=["market"])
admin_router = APIRouter(prefix="/admin/market", tags=["admin"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


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
    )


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
) -> list[MarketModelOut]:
    registry = get_registry()
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
    return [_out(model, registry) for model in models]


@router.get("/models/{slug}", response_model=MarketModelOut)
async def get_public_market_model(slug: str, session: SessionDep) -> MarketModelOut:
    try:
        model = await get_market_model(session, slug)
    except MarketModelError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    return _out(model, get_registry())


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
