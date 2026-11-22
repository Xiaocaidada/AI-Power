from datetime import UTC, datetime, timedelta

from sqlalchemy import func

from app.models import UsageEvent

DEFAULT_RANGE_DAYS = 30


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def resolve_range(from_ts: datetime | None, to_ts: datetime | None) -> tuple[datetime, datetime]:
    end_at = as_utc(to_ts) if to_ts is not None else datetime.now(UTC)
    start_at = (
        as_utc(from_ts) if from_ts is not None else end_at - timedelta(days=DEFAULT_RANGE_DAYS)
    )
    if start_at > end_at:
        raise ValueError("from must be earlier than or equal to to")
    return start_at, end_at


def bucket_expression(group_by: str):
    if group_by == "day":
        return func.date(UsageEvent.created_at)
    if group_by == "provider":
        return func.coalesce(UsageEvent.provider_id, "unknown")
    if group_by == "source":
        return func.coalesce(UsageEvent.source, "chat")
    return func.coalesce(UsageEvent.model, "unknown")
