from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.db import get_session
from app.deps import get_current_user, get_registry
from app.providers.registry import ProviderRegistry
from app.schemas import ModelOut
from app.services.routing import ModelEntry, catalog_entries

router = APIRouter(
    prefix="/models",
    tags=["models"],
    dependencies=[Depends(get_current_user)],
)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_registry)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]

MAX_COMPARE = 5


def _out(entry: ModelEntry) -> ModelOut:
    return ModelOut(
        id=entry.id,
        provider_id=entry.provider_id,
        model_id=entry.model_id,
        display_name=entry.display_name,
        context_window=entry.context_window,
        input_price=entry.input_price,
        output_price=entry.output_price,
        tags=entry.tags,
        priority=entry.priority,
        available=entry.available,
    )


@router.get("", response_model=list[ModelOut])
async def list_models(
    session: SessionDep, registry: RegistryDep, redis: RedisDep
) -> list[ModelOut]:
    entries = await catalog_entries(session, registry, redis)
    return [_out(entry) for entry in entries]


@router.get("/compare", response_model=list[ModelOut])
async def compare_models(
    session: SessionDep,
    registry: RegistryDep,
    redis: RedisDep,
    ids: Annotated[str, Query(min_length=1)],
) -> list[ModelOut]:
    requested = [item.strip() for item in ids.split(",") if item.strip()]
    if not requested:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ids must not be empty")
    if len(requested) > MAX_COMPARE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            {"code": "too_many_models", "message": f"Compare at most {MAX_COMPARE} models"},
        )

    entries = {entry.id: entry for entry in await catalog_entries(session, registry, redis)}
    missing = [model_id for model_id in requested if model_id not in entries]
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "model_not_found", "message": "Unknown model id", "ids": missing},
        )
    return [_out(entries[model_id]) for model_id in requested]
