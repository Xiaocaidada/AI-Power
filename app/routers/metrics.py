from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.db import get_session
from app.deps import get_registry
from app.metrics import metrics
from app.models import IngestionJob
from app.providers.registry import ProviderRegistry
from app.services.routing import is_open

router = APIRouter(tags=["metrics"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_registry)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]

JOB_STATUSES = ("queued", "running", "ready", "failed", "dead")


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(
    session: SessionDep, registry: RegistryDep, redis: RedisDep
) -> PlainTextResponse:
    rows = (
        await session.execute(
            select(IngestionJob.status, func.count()).group_by(IngestionJob.status)
        )
    ).all()
    counts = {status: count for status, count in rows}
    for status in JOB_STATUSES:
        metrics.set_gauge("ai_power_ingestion_jobs", float(counts.get(status, 0)), status=status)
    for provider in registry.all():
        metrics.set_gauge(
            "ai_power_circuit_open",
            1.0 if await is_open(redis, provider.id) else 0.0,
            provider=provider.id,
        )
    return PlainTextResponse(
        metrics.render(), media_type="text/plain; version=0.0.4; charset=utf-8"
    )
