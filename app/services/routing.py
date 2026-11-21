import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike
from app.models import ModelCatalog
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)

FAILURE_THRESHOLD = 3
COOLDOWN_SECONDS = 60
KEY_PREFIX = "circuit:provider:"


@dataclass(frozen=True, slots=True)
class ModelEntry:
    id: str
    provider_id: str
    model_id: str
    display_name: str
    context_window: int
    input_price: float
    output_price: float
    tags: list[str]
    priority: int
    available: bool


def _failure_key(provider_id: str) -> str:
    return f"{KEY_PREFIX}{provider_id}"


async def record_failure(redis: RedisLike, provider_id: str) -> int:
    key = _failure_key(provider_id)
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, COOLDOWN_SECONDS)
        return count
    except Exception:
        logger.warning("circuit breaker unavailable; allowing provider", exc_info=True)
        return 0


async def reset_failures(redis: RedisLike, provider_id: str) -> None:
    try:
        await redis.delete(_failure_key(provider_id))
    except Exception:
        logger.warning("circuit breaker reset failed", exc_info=True)


async def is_open(redis: RedisLike, provider_id: str) -> bool:
    try:
        value = await redis.get(_failure_key(provider_id))
    except Exception:
        return False
    if value is None:
        return False
    try:
        return int(value) >= FAILURE_THRESHOLD
    except (TypeError, ValueError):
        return False


def _tags(raw: str) -> list[str]:
    return [tag for tag in raw.split(",") if tag]


async def catalog_entries(
    session: AsyncSession, registry: ProviderRegistry, redis: RedisLike
) -> list[ModelEntry]:
    rows = (
        await session.execute(
            select(ModelCatalog).order_by(
                ModelCatalog.priority, ModelCatalog.provider_id, ModelCatalog.model_id
            )
        )
    ).scalars()
    registered = {provider.id for provider in registry.all()}
    catalog_rows = [row for row in rows if row.provider_id in registered]
    open_cache: dict[str, bool] = {}
    entries: list[ModelEntry] = []

    # A seeded catalog is authoritative: disabled rows stay hidden instead of
    # falling back to the provider's live list.
    if catalog_rows:
        for row in catalog_rows:
            if not row.enabled:
                continue
            if row.provider_id not in open_cache:
                open_cache[row.provider_id] = await is_open(redis, row.provider_id)
            entries.append(
                ModelEntry(
                    id=str(row.id),
                    provider_id=row.provider_id,
                    model_id=row.model_id,
                    display_name=row.display_name,
                    context_window=row.context_window,
                    input_price=row.input_price,
                    output_price=row.output_price,
                    tags=_tags(row.tags),
                    priority=row.priority,
                    available=not open_cache[row.provider_id],
                )
            )
        return entries

    for provider in registry.all():
        if provider.id not in open_cache:
            open_cache[provider.id] = await is_open(redis, provider.id)
        try:
            models = await provider.list_models()
        except ProviderError:
            continue
        for index, model in enumerate(models):
            entries.append(
                ModelEntry(
                    id=f"{provider.id}:{model.id}",
                    provider_id=provider.id,
                    model_id=model.id,
                    display_name=model.id,
                    context_window=0,
                    input_price=0.0,
                    output_price=0.0,
                    tags=[],
                    priority=100 + index,
                    available=not open_cache[provider.id],
                )
            )
    return entries


async def route_candidates(
    session: AsyncSession, registry: ProviderRegistry, redis: RedisLike
) -> list[tuple[str, str]]:
    entries = await catalog_entries(session, registry, redis)
    ordered = sorted(entries, key=lambda entry: (entry.priority, entry.provider_id, entry.model_id))
    return [(entry.provider_id, entry.model_id) for entry in ordered if entry.available]
