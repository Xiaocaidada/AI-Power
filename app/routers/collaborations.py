import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.db import SessionLocal, get_session
from app.deps import (
    AuthContext,
    get_jwt_context,
    get_scoped_registry,
    require_scope,
)
from app.metrics import track_sse_stream
from app.models import (
    CollaborationRun,
    CollaborationRunEvent,
    CollaborationStep,
)
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas import (
    CollaborationRunCreate,
    CollaborationRunOut,
    CollaborationStepOut,
    RunAcceptedOut,
    RunCancelOut,
)
from app.services.access import get_owned_knowledge_base
from app.services.queue import JobQueue, get_queue
from app.services.quotas import enforce_quota
from app.services.run_events import (
    KEEPALIVE_SECONDS,
    POLL_INTERVAL_SECONDS,
    TERMINAL_EVENTS,
    TERMINAL_STATUSES,
    append_collaboration_event,
    format_sse,
    list_collaboration_events,
)

router = APIRouter(prefix="/collaborations", tags=["collaborations"])
logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ChatContext = Annotated[AuthContext, Depends(require_scope("chat:write"))]
RedisDep = Annotated[RedisLike, Depends(get_redis)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_scoped_registry)]
QueueDep = Annotated[JobQueue, Depends(get_queue)]


async def _get_owned_run(
    run_id: UUID, workspace_id: UUID, session: AsyncSession
) -> CollaborationRun:
    run = (
        await session.execute(
            select(CollaborationRun).where(
                CollaborationRun.id == run_id,
                CollaborationRun.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Collaboration run not found")
    return run


def _resume_cursor(after: int | None, last_event_id: str | None) -> int:
    if after is not None:
        return after
    if last_event_id is not None:
        try:
            return max(int(last_event_id), 0)
        except ValueError:
            return 0
    return 0


@router.post("/runs", response_model=RunAcceptedOut, status_code=202)
async def create_collaboration_run(
    payload: CollaborationRunCreate,
    context: ChatContext,
    session: SessionDep,
    queue: QueueDep,
    registry: RegistryDep,
    redis: RedisDep,
) -> RunAcceptedOut:
    try:
        registry.get(payload.provider_id)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    if payload.kb_id is not None:
        await get_owned_knowledge_base(payload.kb_id, context.workspace.id, session)
    await enforce_quota(redis, context)

    run = CollaborationRun(
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        api_key_id=context.api_key_id,
        provider_id=payload.provider_id,
        model=payload.model,
        kb_id=payload.kb_id,
        status="queued",
        input_text=payload.input,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    run_id = run.id
    try:
        await queue.enqueue_collaboration_run(run_id)
    except Exception:
        logger.exception("failed to enqueue collaboration run %s", run_id)
        run.status = "failed"
        run.error_code = "queue_unavailable"
        run.finished_at = datetime.now(UTC)
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": "queue_unavailable", "message": "Collaboration queue is unavailable"},
        ) from None
    return RunAcceptedOut(run_id=run_id, status="queued")


@router.get("/runs/{run_id}/events")
async def collaboration_run_events(
    run_id: UUID,
    context: ChatContext,
    session: SessionDep,
    after: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    await _get_owned_run(run_id, context.workspace.id, session)
    cursor = _resume_cursor(after, last_event_id)

    async def stream():
        position = cursor
        last_ping = time.monotonic()
        missing_terminal_polls = 0
        while True:
            async with SessionLocal() as poll:
                run = await poll.get(CollaborationRun, run_id)
                if run is None:
                    return
                events = await list_collaboration_events(poll, run_id, position)
                terminal_rows = (
                    await poll.execute(
                        select(func.count())
                        .select_from(CollaborationRunEvent)
                        .where(
                            CollaborationRunEvent.run_id == run_id,
                            CollaborationRunEvent.event.in_(TERMINAL_EVENTS),
                        )
                    )
                ).scalar_one()
            terminal_seen = False
            for event in events:
                yield format_sse(event)
                position = event.seq
                if event.event in TERMINAL_EVENTS:
                    terminal_seen = True
            if run.status in TERMINAL_STATUSES:
                if not terminal_seen and terminal_rows == 0:
                    missing_terminal_polls += 1
                    if missing_terminal_polls < 2:
                        await asyncio.sleep(POLL_INTERVAL_SECONDS)
                        continue
                    payload = {
                        "run_id": str(run.id),
                        "status": run.status,
                        "error_code": run.error_code,
                        "total_ms": run.total_ms,
                        "rounds": run.rounds,
                        "prompt_tokens": run.prompt_tokens,
                        "completion_tokens": run.completion_tokens,
                        "cost": run.cost,
                    }
                    yield (
                        "event: collaboration_end\n"
                        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    )
                return
            missing_terminal_polls = 0
            now = time.monotonic()
            if now - last_ping >= KEEPALIVE_SECONDS:
                yield ": keepalive\n\n"
                last_ping = now
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    return StreamingResponse(
        track_sse_stream(stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{run_id}/cancel", response_model=RunCancelOut)
async def cancel_collaboration_run(
    run_id: UUID,
    context: ChatContext,
    session: SessionDep,
) -> RunCancelOut:
    run = await _get_owned_run(run_id, context.workspace.id, session)
    if run.status not in TERMINAL_STATUSES:
        now = datetime.now(UTC)
        cancelled = await session.execute(
            update(CollaborationRun)
            .where(
                CollaborationRun.id == run_id,
                CollaborationRun.workspace_id == context.workspace.id,
                CollaborationRun.status == "queued",
            )
            .values(status="cancelled", error_code="cancelled", finished_at=now)
        )
        await session.commit()
        if cancelled.rowcount == 1:
            try:
                await append_collaboration_event(
                    run_id,
                    "collaboration_end",
                    {
                        "run_id": str(run_id),
                        "status": "cancelled",
                        "error_code": "cancelled",
                    },
                )
            except Exception:
                logger.exception("failed to append collaboration cancel event %s", run_id)
        else:
            await session.execute(
                update(CollaborationRun)
                .where(
                    CollaborationRun.id == run_id,
                    CollaborationRun.workspace_id == context.workspace.id,
                    CollaborationRun.status == "running",
                )
                .values(cancel_requested_at=now)
            )
            await session.commit()
        await session.refresh(run)
    return RunCancelOut(
        run_id=run.id,
        status=run.status,
        cancel_requested_at=run.cancel_requested_at,
    )


@router.get("/runs/{run_id}", response_model=CollaborationRunOut)
async def get_collaboration_run(
    run_id: UUID,
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
) -> CollaborationRunOut:
    run = (
        await session.execute(
            select(CollaborationRun).where(
                CollaborationRun.id == run_id,
                CollaborationRun.workspace_id == context.workspace.id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Collaboration run not found")
    steps = (
        await session.execute(
            select(CollaborationStep)
            .where(CollaborationStep.run_id == run.id)
            .order_by(CollaborationStep.created_at, CollaborationStep.id)
        )
    ).scalars()
    return CollaborationRunOut(
        **CollaborationRunOut.model_validate(run).model_dump(exclude={"steps"}),
        steps=[CollaborationStepOut.model_validate(step) for step in steps],
    )


@router.get("/runs", response_model=list[CollaborationRunOut])
async def list_collaboration_runs(
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: UUID | None = None,
) -> list[CollaborationRunOut]:
    conditions = [CollaborationRun.workspace_id == context.workspace.id]
    if before is not None:
        conditions.append(CollaborationRun.id < before)
    runs = (
        await session.execute(
            select(CollaborationRun)
            .where(*conditions)
            .order_by(CollaborationRun.id.desc())
            .limit(limit)
        )
    ).scalars()
    return [CollaborationRunOut.model_validate(run) for run in runs]
