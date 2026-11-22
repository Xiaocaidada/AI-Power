from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Announcement, AnnouncementRead, HomePlacement

PLACEMENT_KINDS = frozenset({"banner", "featured", "activity"})
ANNOUNCEMENT_STATUSES = frozenset({"draft", "published", "archived"})


class ContentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _validate_placement_window(starts_at: datetime | None, ends_at: datetime | None) -> None:
    if starts_at is None or ends_at is None:
        return
    if as_utc(ends_at) <= as_utc(starts_at):
        raise ContentError("invalid_window", "ends_at must be after starts_at")


def _validate_announcement_window(
    published_at: datetime | None, expires_at: datetime | None
) -> None:
    if published_at is None or expires_at is None:
        return
    if as_utc(expires_at) <= as_utc(published_at):
        raise ContentError("invalid_window", "expires_at must be after published_at")


def _placement_window(now: datetime) -> tuple[Any, ...]:
    return (
        or_(HomePlacement.starts_at.is_(None), HomePlacement.starts_at <= now),
        or_(HomePlacement.ends_at.is_(None), HomePlacement.ends_at > now),
    )


def _announcement_visibility(now: datetime) -> tuple[Any, ...]:
    return (
        Announcement.status == "published",
        or_(Announcement.published_at.is_(None), Announcement.published_at <= now),
        or_(Announcement.expires_at.is_(None), Announcement.expires_at > now),
    )


async def list_placements(
    session: AsyncSession,
    *,
    kind: str | None = None,
    include_inactive: bool = False,
    now: datetime | None = None,
) -> list[HomePlacement]:
    conditions: list[Any] = []
    if not include_inactive:
        conditions.append(HomePlacement.enabled.is_(True))
        conditions.extend(_placement_window(now or datetime.now(UTC)))
    if kind is not None:
        conditions.append(HomePlacement.kind == kind)
    rows = list(
        (await session.execute(select(HomePlacement).where(*conditions))).scalars()
    )
    rows.sort(key=lambda row: (row.kind, row.sort_order, row.title.lower()))
    return rows


async def get_placement(session: AsyncSession, placement_id: UUID) -> HomePlacement:
    placement = await session.get(HomePlacement, placement_id)
    if placement is None:
        raise ContentError("not_found", "Home placement not found")
    return placement


async def create_placement(session: AsyncSession, values: dict[str, Any]) -> HomePlacement:
    _validate_placement_window(values.get("starts_at"), values.get("ends_at"))
    placement = HomePlacement(**values)
    session.add(placement)
    await session.flush()
    return placement


async def update_placement(
    session: AsyncSession, placement: HomePlacement, values: dict[str, Any]
) -> HomePlacement:
    starts_at = values.get("starts_at", placement.starts_at)
    ends_at = values.get("ends_at", placement.ends_at)
    _validate_placement_window(starts_at, ends_at)
    for key, value in values.items():
        setattr(placement, key, value)
    await session.flush()
    return placement


async def delete_placement(session: AsyncSession, placement: HomePlacement) -> None:
    await session.delete(placement)
    await session.flush()


async def list_announcements(
    session: AsyncSession,
    *,
    category: str | None = None,
    limit: int | None = None,
    include_unpublished: bool = False,
    now: datetime | None = None,
) -> list[Announcement]:
    conditions: list[Any] = []
    if not include_unpublished:
        conditions.extend(_announcement_visibility(now or datetime.now(UTC)))
    if category is not None:
        conditions.append(Announcement.category == category)
    statement = (
        select(Announcement)
        .where(*conditions)
        .order_by(
            Announcement.pinned.desc(),
            func.coalesce(Announcement.published_at, Announcement.created_at).desc(),
            Announcement.created_at.desc(),
        )
    )
    if limit is not None:
        statement = statement.limit(limit)
    return list((await session.execute(statement)).scalars())


async def get_announcement(
    session: AsyncSession,
    announcement_id: UUID,
    *,
    include_unpublished: bool = False,
    now: datetime | None = None,
) -> Announcement:
    conditions: list[Any] = [Announcement.id == announcement_id]
    if not include_unpublished:
        conditions.extend(_announcement_visibility(now or datetime.now(UTC)))
    announcement = (
        await session.execute(select(Announcement).where(*conditions))
    ).scalar_one_or_none()
    if announcement is None:
        raise ContentError("not_found", "Announcement not found")
    return announcement


async def create_announcement(session: AsyncSession, values: dict[str, Any]) -> Announcement:
    if values.get("status") == "published" and values.get("published_at") is None:
        values["published_at"] = datetime.now(UTC)
    _validate_announcement_window(values.get("published_at"), values.get("expires_at"))
    announcement = Announcement(**values)
    session.add(announcement)
    await session.flush()
    return announcement


async def update_announcement(
    session: AsyncSession, announcement: Announcement, values: dict[str, Any]
) -> Announcement:
    for key, value in values.items():
        setattr(announcement, key, value)
    if announcement.status == "published" and announcement.published_at is None:
        announcement.published_at = datetime.now(UTC)
    _validate_announcement_window(announcement.published_at, announcement.expires_at)
    await session.flush()
    return announcement


async def delete_announcement(session: AsyncSession, announcement: Announcement) -> None:
    await session.execute(
        delete(AnnouncementRead).where(AnnouncementRead.announcement_id == announcement.id)
    )
    await session.delete(announcement)
    await session.flush()


def _read_join(user_id: UUID) -> Any:
    return and_(
        AnnouncementRead.announcement_id == Announcement.id,
        AnnouncementRead.user_id == user_id,
    )


async def notification_feed(
    session: AsyncSession,
    user_id: UUID,
    *,
    limit: int = 20,
    now: datetime | None = None,
) -> tuple[int, list[tuple[Announcement, datetime | None]]]:
    reference = now or datetime.now(UTC)
    visibility = _announcement_visibility(reference)
    join = _read_join(user_id)
    rows = (
        await session.execute(
            select(Announcement, AnnouncementRead.read_at)
            .outerjoin(AnnouncementRead, join)
            .where(*visibility)
            .order_by(
                Announcement.pinned.desc(),
                func.coalesce(Announcement.published_at, Announcement.created_at).desc(),
                Announcement.created_at.desc(),
            )
            .limit(limit)
        )
    ).all()
    unread_count = (
        await session.execute(
            select(func.count())
            .select_from(Announcement)
            .outerjoin(AnnouncementRead, join)
            .where(*visibility, AnnouncementRead.id.is_(None))
        )
    ).scalar_one()
    return int(unread_count), [(row[0], row[1]) for row in rows]


async def mark_announcement_read(
    session: AsyncSession,
    user_id: UUID,
    announcement_id: UUID,
    *,
    now: datetime | None = None,
) -> tuple[Announcement, datetime]:
    reference = now or datetime.now(UTC)
    announcement = await get_announcement(session, announcement_id, now=reference)
    existing = (
        await session.execute(
            select(AnnouncementRead).where(
                AnnouncementRead.announcement_id == announcement.id,
                AnnouncementRead.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return announcement, existing.read_at
    read = AnnouncementRead(
        announcement_id=announcement.id, user_id=user_id, read_at=reference
    )
    session.add(read)
    await session.flush()
    return announcement, read.read_at


async def mark_all_announcements_read(
    session: AsyncSession,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> int:
    reference = now or datetime.now(UTC)
    join = _read_join(user_id)
    announcement_ids = (
        await session.execute(
            select(Announcement.id)
            .outerjoin(AnnouncementRead, join)
            .where(*_announcement_visibility(reference), AnnouncementRead.id.is_(None))
        )
    ).scalars().all()
    for announcement_id in announcement_ids:
        session.add(
            AnnouncementRead(
                announcement_id=announcement_id, user_id=user_id, read_at=reference
            )
        )
    await session.flush()
    return len(announcement_ids)