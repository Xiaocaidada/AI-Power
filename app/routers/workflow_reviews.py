import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import WorkflowReview, WorkflowRun
from app.schemas import WorkflowReviewOut, WorkflowReviewRespondIn
from app.services.queue import JobQueue, get_queue

router = APIRouter(prefix="/workflows/reviews", tags=["workflows"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
QueueDep = Annotated[JobQueue, Depends(get_queue)]
logger = logging.getLogger(__name__)


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


@router.get("", response_model=list[WorkflowReviewOut])
async def list_workflow_reviews(
    context: JwtContext,
    session: SessionDep,
    status_filter: Annotated[str | None, Query(alias="status")] = "pending",
    run_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[WorkflowReviewOut]:
    conditions = [WorkflowReview.workspace_id == context.workspace.id]
    if status_filter is not None:
        if status_filter not in {"pending", "approved", "rejected", "expired", "cancelled"}:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "invalid_status", "message": "Invalid review status"},
            )
        conditions.append(WorkflowReview.status == status_filter)
        if status_filter == "pending":
            conditions.append(
                or_(
                    WorkflowReview.expires_at.is_(None),
                    WorkflowReview.expires_at > datetime.now(UTC),
                )
            )
    if run_id is not None:
        conditions.append(WorkflowReview.run_id == run_id)
    rows = await session.execute(
        select(WorkflowReview)
        .where(*conditions)
        .order_by(WorkflowReview.created_at.desc())
        .limit(limit)
    )
    return [WorkflowReviewOut.model_validate(row) for row in rows.scalars()]


@router.get("/{review_id}", response_model=WorkflowReviewOut)
async def get_workflow_review(
    review_id: UUID, context: JwtContext, session: SessionDep
) -> WorkflowReviewOut:
    review = await session.get(WorkflowReview, review_id)
    if review is None or review.workspace_id != context.workspace.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
    return WorkflowReviewOut.model_validate(review)


@router.post("/{review_id}/respond", response_model=WorkflowReviewOut)
async def respond_to_workflow_review(
    review_id: UUID,
    payload: WorkflowReviewRespondIn,
    context: JwtContext,
    session: SessionDep,
    queue: QueueDep,
) -> WorkflowReviewOut:
    review = await session.get(WorkflowReview, review_id)
    if review is None or review.workspace_id != context.workspace.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
    if review.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "review_already_resolved", "message": "Review already resolved"},
        )
    now = datetime.now(UTC)
    if review.expires_at is not None and _as_utc(review.expires_at) <= now:
        await session.execute(
            update(WorkflowReview)
            .where(WorkflowReview.id == review_id, WorkflowReview.status == "pending")
            .values(status="expired", decision="expired", resolved_at=now)
        )
        await session.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "review_expired", "message": "Review has expired"},
        )
    updated = await session.execute(
        update(WorkflowReview)
        .where(
            WorkflowReview.id == review_id,
            WorkflowReview.workspace_id == context.workspace.id,
            WorkflowReview.status == "pending",
        )
        .values(
            status=payload.decision,
            decision=payload.decision,
            comment=payload.comment,
            output=payload.output,
            reviewer_user_id=context.user.id,
            resolved_at=now,
        )
    )
    if updated.rowcount != 1:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "review_already_resolved", "message": "Review already resolved"},
        )
    await session.commit()
    await session.refresh(review)
    run = await session.get(WorkflowRun, review.run_id)
    if run is not None and (
        run.status == "waiting_review"
        or (run.status == "running" and run.paused_at is not None)
    ):
        try:
            await queue.enqueue_workflow_resume(run.id)
        except Exception:
            logger.exception("failed to enqueue review resume for run %s", run.id)
    return WorkflowReviewOut.model_validate(review)