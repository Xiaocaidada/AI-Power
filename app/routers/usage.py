from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import ApiKey, Message, Trace, UsageEvent
from app.schemas import (
    QuotaSummaryOut,
    QuotaWindowOut,
    UsageBucketOut,
    UsageByKeyBucketOut,
    UsageByKeyOut,
    UsageCostBucketOut,
    UsageCostOut,
    UsageRecentItemOut,
    UsageSummaryOut,
)
from app.services.quotas import quota_snapshot
from app.services.usage_stats import bucket_expression, resolve_range

router = APIRouter(prefix="/usage", tags=["usage"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]

GroupBy = Literal["day", "provider", "model", "source"]
SourceFilter = Literal[
    "chat", "workflow", "collaboration", "arena", "prompt_lab", "model_eval"
]


def _range(from_ts: datetime | None, to_ts: datetime | None) -> tuple[datetime, datetime]:
    try:
        return resolve_range(from_ts, to_ts)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None


def _filters(
    context: AuthContext,
    start_at: datetime,
    end_at: datetime,
    source: SourceFilter | None,
    api_key_id: UUID | None,
) -> list[object]:
    conditions: list[object] = [
        UsageEvent.workspace_id == context.workspace.id,
        UsageEvent.created_at >= start_at,
        UsageEvent.created_at <= end_at,
    ]
    if source is not None:
        conditions.append(UsageEvent.source == source)
    if api_key_id is not None:
        conditions.append(UsageEvent.api_key_id == api_key_id)
    return conditions


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
    group_by: GroupBy = "day",
    source: SourceFilter | None = None,
    api_key_id: UUID | None = None,
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
        .where(*_filters(context, start_at, end_at, source, api_key_id))
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
    group_by: GroupBy = "day",
    source: SourceFilter | None = None,
    api_key_id: UUID | None = None,
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
        .where(*_filters(context, start_at, end_at, source, api_key_id))
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


@router.get("/recent", response_model=list[UsageRecentItemOut])
async def usage_recent(
    context: JwtContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[UsageRecentItemOut]:
    rows = (
        await session.execute(
            select(UsageEvent, Trace.status)
            .outerjoin(Message, Message.id == UsageEvent.message_id)
            .outerjoin(Trace, Trace.request_id == Message.request_id)
            .where(UsageEvent.workspace_id == context.workspace.id)
            .order_by(UsageEvent.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        UsageRecentItemOut(
            id=event.id,
            source=event.source,
            provider_id=event.provider_id,
            model=event.model,
            prompt_tokens=event.prompt_tokens,
            completion_tokens=event.completion_tokens,
            total_tokens=(event.prompt_tokens or 0) + (event.completion_tokens or 0),
            cost=event.cost,
            status=status_value,
            conversation_id=event.conversation_id,
            created_at=event.created_at,
        )
        for event, status_value in rows
    ]


@router.get("/by-key", response_model=UsageByKeyOut)
async def usage_by_key(
    context: JwtContext,
    session: SessionDep,
    from_ts: Annotated[datetime | None, Query(alias="from")] = None,
    to_ts: Annotated[datetime | None, Query(alias="to")] = None,
    source: SourceFilter | None = None,
    api_key_id: UUID | None = None,
) -> UsageByKeyOut:
    start_at, end_at = _range(from_ts, to_ts)
    statement = (
        select(
            UsageEvent.api_key_id.label("api_key_id"),
            ApiKey.name.label("name"),
            ApiKey.prefix.label("prefix"),
            func.count().label("requests"),
            func.coalesce(func.sum(UsageEvent.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(UsageEvent.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(UsageEvent.cost), 0.0).label("cost"),
            func.coalesce(func.sum(case((UsageEvent.unpriced.is_(True), 1), else_=0)), 0).label(
                "unpriced_requests"
            ),
        )
        .outerjoin(ApiKey, ApiKey.id == UsageEvent.api_key_id)
        .where(*_filters(context, start_at, end_at, source, api_key_id))
        .group_by(UsageEvent.api_key_id, ApiKey.name, ApiKey.prefix)
        .order_by(func.coalesce(func.sum(UsageEvent.cost), 0.0).desc(), UsageEvent.api_key_id)
    )
    rows = (await session.execute(statement)).all()
    buckets = [
        UsageByKeyBucketOut(
            api_key_id=row.api_key_id,
            name=row.name or "unattributed",
            prefix=row.prefix,
            requests=row.requests,
            prompt_tokens=row.prompt_tokens,
            completion_tokens=row.completion_tokens,
            total_tokens=row.prompt_tokens + row.completion_tokens,
            cost=round(float(row.cost), 6),
            unpriced_requests=row.unpriced_requests,
        )
        for row in rows
    ]
    return UsageByKeyOut(
        start=start_at,
        end=end_at,
        total_requests=sum(bucket.requests for bucket in buckets),
        total_cost=round(sum(bucket.cost for bucket in buckets), 6),
        unpriced_requests=sum(bucket.unpriced_requests for bucket in buckets),
        buckets=buckets,
    )
