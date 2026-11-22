from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, require_admin
from app.models import Announcement, AuditLog, HomePlacement
from app.schemas import (
    AnnouncementCreate,
    AnnouncementOut,
    AnnouncementUpdate,
    HomeFeedOut,
    HomePlacementCreate,
    HomePlacementOut,
    HomePlacementUpdate,
    NotificationFeedOut,
    NotificationMarkAllOut,
    NotificationOut,
)
from app.services.content import (
    ContentError,
    create_announcement,
    create_placement,
    delete_announcement,
    delete_placement,
    get_announcement,
    get_placement,
    list_announcements,
    list_placements,
    mark_all_announcements_read,
    mark_announcement_read,
    notification_feed,
    update_announcement,
    update_placement,
)

router = APIRouter(tags=["content"])
notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])
admin_router = APIRouter(prefix="/admin/content", tags=["admin"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
AdminContext = Annotated[AuthContext, Depends(require_admin)]


def _http_error(exc: ContentError) -> HTTPException:
    if exc.code == "not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, exc.message)
    return HTTPException(422, exc.message)


def _audit(
    session: AsyncSession,
    context: AuthContext,
    action: str,
    target_type: str,
    target_id: UUID,
    detail: dict[str, object],
) -> None:
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            detail=detail,
        )
    )


def _notification(announcement: Announcement, read_at) -> NotificationOut:
    data = AnnouncementOut.model_validate(announcement).model_dump()
    return NotificationOut(**data, read_at=read_at)


@router.get("/home", response_model=HomeFeedOut)
async def home_feed(session: SessionDep) -> HomeFeedOut:
    placements = await list_placements(session)
    announcements = await list_announcements(session, limit=3)
    return HomeFeedOut(
        banners=[item for item in placements if item.kind == "banner"],
        featured=[item for item in placements if item.kind == "featured"],
        activities=[item for item in placements if item.kind == "activity"],
        announcements=list(announcements),
    )


@router.get("/announcements", response_model=list[AnnouncementOut])
async def list_public_announcements(
    session: SessionDep,
    category: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[Announcement]:
    return await list_announcements(session, category=category, limit=limit)


@router.get("/announcements/{announcement_id}", response_model=AnnouncementOut)
async def get_public_announcement(
    announcement_id: UUID, session: SessionDep
) -> Announcement:
    try:
        return await get_announcement(session, announcement_id)
    except ContentError as exc:
        raise _http_error(exc) from None


@notifications_router.get("", response_model=NotificationFeedOut)
async def list_notifications(
    context: JwtContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> NotificationFeedOut:
    unread_count, rows = await notification_feed(session, context.user.id, limit=limit)
    return NotificationFeedOut(
        unread_count=unread_count,
        items=[_notification(announcement, read_at) for announcement, read_at in rows],
    )


@notifications_router.post("/{announcement_id}/read", response_model=NotificationOut)
async def mark_notification_read(
    announcement_id: UUID, context: JwtContext, session: SessionDep
) -> NotificationOut:
    try:
        announcement, read_at = await mark_announcement_read(
            session, context.user.id, announcement_id
        )
    except ContentError as exc:
        raise _http_error(exc) from None
    await session.commit()
    return _notification(announcement, read_at)


@notifications_router.post("/read-all", response_model=NotificationMarkAllOut)
async def mark_all_notifications_read(
    context: JwtContext, session: SessionDep
) -> NotificationMarkAllOut:
    marked = await mark_all_announcements_read(session, context.user.id)
    await session.commit()
    return NotificationMarkAllOut(marked=marked)


@admin_router.get("/placements", response_model=list[HomePlacementOut])
async def list_admin_placements(
    context: AdminContext, session: SessionDep
) -> list[HomePlacement]:
    return await list_placements(session, include_inactive=True)


@admin_router.post(
    "/placements", response_model=HomePlacementOut, status_code=status.HTTP_201_CREATED
)
async def create_admin_placement(
    payload: HomePlacementCreate, context: AdminContext, session: SessionDep
) -> HomePlacement:
    try:
        placement = await create_placement(session, payload.model_dump())
    except ContentError as exc:
        raise _http_error(exc) from None
    _audit(
        session,
        context,
        "content.placement_create",
        "home_placement",
        placement.id,
        {"kind": placement.kind, "title": placement.title},
    )
    await session.commit()
    await session.refresh(placement)
    return placement


@admin_router.patch("/placements/{placement_id}", response_model=HomePlacementOut)
async def update_admin_placement(
    placement_id: UUID,
    payload: HomePlacementUpdate,
    context: AdminContext,
    session: SessionDep,
) -> HomePlacement:
    try:
        placement = await get_placement(session, placement_id)
        placement = await update_placement(
            session, placement, payload.model_dump(exclude_unset=True)
        )
    except ContentError as exc:
        raise _http_error(exc) from None
    _audit(
        session,
        context,
        "content.placement_update",
        "home_placement",
        placement.id,
        {"enabled": placement.enabled},
    )
    await session.commit()
    await session.refresh(placement)
    return placement


@admin_router.delete("/placements/{placement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_placement(
    placement_id: UUID, context: AdminContext, session: SessionDep
) -> Response:
    try:
        placement = await get_placement(session, placement_id)
    except ContentError as exc:
        raise _http_error(exc) from None
    _audit(
        session,
        context,
        "content.placement_delete",
        "home_placement",
        placement.id,
        {"kind": placement.kind, "title": placement.title},
    )
    await delete_placement(session, placement)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("/announcements", response_model=list[AnnouncementOut])
async def list_admin_announcements(
    context: AdminContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[Announcement]:
    return await list_announcements(session, include_unpublished=True, limit=limit)


@admin_router.post(
    "/announcements", response_model=AnnouncementOut, status_code=status.HTTP_201_CREATED
)
async def create_admin_announcement(
    payload: AnnouncementCreate, context: AdminContext, session: SessionDep
) -> Announcement:
    try:
        announcement = await create_announcement(session, payload.model_dump())
    except ContentError as exc:
        raise _http_error(exc) from None
    _audit(
        session,
        context,
        "content.announcement_create",
        "announcement",
        announcement.id,
        {"status": announcement.status, "title": announcement.title},
    )
    await session.commit()
    await session.refresh(announcement)
    return announcement


@admin_router.patch("/announcements/{announcement_id}", response_model=AnnouncementOut)
async def update_admin_announcement(
    announcement_id: UUID,
    payload: AnnouncementUpdate,
    context: AdminContext,
    session: SessionDep,
) -> Announcement:
    try:
        announcement = await get_announcement(
            session, announcement_id, include_unpublished=True
        )
        announcement = await update_announcement(
            session, announcement, payload.model_dump(exclude_unset=True)
        )
    except ContentError as exc:
        raise _http_error(exc) from None
    _audit(
        session,
        context,
        "content.announcement_update",
        "announcement",
        announcement.id,
        {"status": announcement.status, "pinned": announcement.pinned},
    )
    await session.commit()
    await session.refresh(announcement)
    return announcement


@admin_router.delete(
    "/announcements/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_admin_announcement(
    announcement_id: UUID, context: AdminContext, session: SessionDep
) -> Response:
    try:
        announcement = await get_announcement(
            session, announcement_id, include_unpublished=True
        )
    except ContentError as exc:
        raise _http_error(exc) from None
    _audit(
        session,
        context,
        "content.announcement_delete",
        "announcement",
        announcement.id,
        {"status": announcement.status, "title": announcement.title},
    )
    await delete_announcement(session, announcement)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)