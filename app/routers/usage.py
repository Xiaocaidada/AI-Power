from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import UsageEvent
from app.schemas import (
    QuotaSummaryOut,
    QuotaWindowOut,
    UsageBucketOut,
    UsageCostBucketOut,
    UsageCostOut,
    UsageSummaryOut,
)
from app.services.quotas import quota_snapshot
from app.services.usage_stats import bucket_expression, resolve_range

router = APIRouter(prefix="/usage", tags=["usage"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]


def _range(from_ts: datetime | None, to_ts: datetime | None) -> tuple[datetime, datetime]:
    try:
        return resolve_range(from_ts, to_ts)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None


@router.get("/quota", response_model=QuotaSummaryOut)
async def quota_summary(
    context: JwtContext, session: SessionDep, redis: RedisDep
) -> QuotaSummaryOut:
    snapshot = await quota_snapshot(session, redis, context)
    return QuotaSummaryOut(
        plan=snapshot.plan,
        requests=QuotaWindowOut(
            limit=snapshot.request_limit,
            used=snapshot.request_used,
            remaining=max(snapshot.request_limit - snapshot.request_used, 0),
            reset_seconds=snapshot.request_reset,
        ),
        tokens=QuotaWindowOut(
            limit=snapshot.token_limit,
            used=snapshot.token_used,
            remaining=max(snapshot.token_limit - snapshot.token_used, 0),
            reset_seconds=snapshot.token_reset,
        ),
        max_keys=snapshot.max_keys,
        active_keys=snapshot.active_keys,
    )


@router.get("/summary", response_model=UsageSummaryOut)
async def usage_summary(
    context: JwtContext,
    session: SessionDep,
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
    group_by: Literal["day", "provider", "model"] = "day",
) -> UsageSummaryOut:
    start_at, end_at = _range(from_ts, to_ts)

    bucket = bucket_expression(group_by)
    statement = (
        select(
            bucket.label("bucket"),
            func.count().label("requests"),
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0).label("completion_tokens"),
        )
        .where(
            UsageEvent.workspace_id == context.workspace.id,
            UsageEvent.created_at >= start_at,
            UsageEvent.created_at <= end_at,
        )
        .group_by(bucket)
        .order_by(bucket)
    )
    rows = (await session.execute(statement)).all()

    return UsageSummaryOut(
        start=start_at,
        end=end_at,
        group_by=group_by,
        buckets=[
            UsageBucketOut(
                key=str(row.bucket),
                requests=row.requests,
                prompt_tokens=row.prompt_tokens,
                completion_tokens=row.completion_tokens,
                total_tokens=row.prompt_tokens + row.completion_tokens,
            )
            for row in rows
        ],
    )


@router.get("/cost", response_model=UsageCostOut)
async def usage_cost(
    context: JwtContext,
    session: SessionDep,
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
    group_by: Literal["day", "provider", "model"] = "day",
) -> UsageCostOut:
    start_at, end_at = _range(from_ts, to_ts)
    bucket = bucket_expression(group_by)
    statement = (
        select(
            bucket.label("bucket"),
            func.count().label("requests"),
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(UsageEvent.cost), 0.0).label("cost"),
            func.coalesce(func.sum(case((UsageEvent.unpriced.is_(True), 1), else_=0)), 0).label(
                "unpriced_requests"
            ),
        )
        .where(
            UsageEvent.workspace_id == context.workspace.id,
            UsageEvent.created_at >= start_at,
            UsageEvent.created_at <= end_at,
        )
        .group_by(bucket)
        .order_by(bucket)
    )
    rows = (await session.execute(statement)).all()
    buckets = [
        UsageCostBucketOut(
            key=str(row.bucket),
            requests=row.requests,
            prompt_tokens=row.prompt_tokens,
            completion_tokens=row.completion_tokens,
            total_tokens=row.prompt_tokens + row.completion_tokens,
            cost=round(float(row.cost), 6),
            unpriced_requests=row.unpriced_requests,
        )
        for row in rows
    ]
    return UsageCostOut(
        start=start_at,
        end=end_at,
        group_by=group_by,
        total_cost=round(sum(bucket.cost for bucket in buckets), 6),
        unpriced_requests=sum(bucket.unpriced_requests for bucket in buckets),
        buckets=buckets,
    )
