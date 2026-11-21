from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import UsageEvent
from app.schemas import QuotaSummaryOut, QuotaWindowOut, UsageBucketOut, UsageSummaryOut
from app.services.quotas import quota_snapshot

router = APIRouter(prefix="/usage", tags=["usage"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]

DEFAULT_RANGE_DAYS = 30


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _bucket_expression(group_by: str):
    if group_by == "day":
        return func.date(UsageEvent.created_at)
    if group_by == "provider":
        return func.coalesce(UsageEvent.provider_id, "unknown")
    return func.coalesce(UsageEvent.model, "unknown")


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
    end_at = _as_utc(to_ts) if to_ts is not None else datetime.now(UTC)
    start_at = (
        _as_utc(from_ts) if from_ts is not None else end_at - timedelta(days=DEFAULT_RANGE_DAYS)
    )
    if start_at > end_at:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "from must be earlier than or equal to to")

    bucket_expression = _bucket_expression(group_by)
    statement = (
        select(
            bucket_expression.label("bucket"),
            func.count().label("requests"),
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0).label("completion_tokens"),
        )
        .where(
            UsageEvent.workspace_id == context.workspace.id,
            UsageEvent.created_at >= start_at,
            UsageEvent.created_at <= end_at,
        )
        .group_by(bucket_expression)
        .order_by(bucket_expression)
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
