from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import UsageEvent
from app.schemas import UsageBucketOut, UsageSummaryOut

router = APIRouter(prefix="/usage", tags=["usage"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]

DEFAULT_RANGE_DAYS = 30


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _bucket_key(event: UsageEvent, group_by: str) -> str:
    if group_by == "day":
        return _as_utc(event.created_at).date().isoformat()
    if group_by == "provider":
        return event.provider_id or "unknown"
    return event.model or "unknown"


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

    events = (
        await session.execute(
            select(UsageEvent).where(
                UsageEvent.workspace_id == context.workspace.id,
                UsageEvent.created_at >= start_at,
                UsageEvent.created_at <= end_at,
            )
        )
    ).scalars()

    buckets: dict[str, dict[str, int]] = {}
    for event in events:
        key = _bucket_key(event, group_by)
        bucket = buckets.setdefault(
            key,
            {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )
        prompt = event.prompt_tokens or 0
        completion = event.completion_tokens or 0
        bucket["requests"] += 1
        bucket["prompt_tokens"] += prompt
        bucket["completion_tokens"] += completion
        bucket["total_tokens"] += prompt + completion

    return UsageSummaryOut(
        start=start_at,
        end=end_at,
        group_by=group_by,
        buckets=[UsageBucketOut(key=key, **values) for key, values in sorted(buckets.items())],
    )
