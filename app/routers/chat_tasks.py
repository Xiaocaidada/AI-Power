import asyncio
import json
import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.db import SessionLocal, get_session
from app.deps import AuthContext, get_jwt_context, get_scoped_registry
from app.metrics import track_sse_stream
from app.models import ChatTask
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas import ChatTaskCreate, ChatTaskOut
from app.services.chat_tasks import (
    TERMINAL_STATUSES,
    ChatTaskError,
    create_task,
    get_task,
    list_events,
    list_tasks,
    request_cancel,
    request_pause,
    request_resume,
    request_retry,
)
from app.services.provider_configs import ProviderConfigError, ensure_model_capability
from app.services.queue import JobQueue, get_queue
from app.services.routing import route_candidates

router = APIRouter(prefix="/chat-tasks", tags=["chat-tasks"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_scoped_registry)]
QueueDep = Annotated[JobQueue, Depends(get_queue)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]

POLL_INTERVAL_SECONDS = 0.3
KEEPALIVE_SECONDS = 15
TERMINAL_EVENTS = frozenset({"task_completed", "task_failed", "task_cancelled"})
PAUSED_STATUSES = frozenset({"paused", "waiting_approval"})


def _error(exc: ChatTaskError) -> HTTPException:
    if exc.code == "task_not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    if exc.code in {"task_terminal", "task_not_paused", "task_not_failed"}:
        return HTTPException(status.HTTP_409_CONFLICT, {"code": exc.code, "message": exc.message})
    if exc.code == "conversation_not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"code": exc.code, "message": exc.message},
    )


def _out(task: ChatTask) -> ChatTaskOut:
    return ChatTaskOut(
        id=task.id,
        conversation_id=task.conversation_id,
        kind=task.kind,
        title=task.title,
        status=task.status,
        plan=task.plan or {},
        checkpoint=task.checkpoint or {},
        result=task.result or {},
        error_code=task.error_code,
        attempts=task.attempts,
        pause_requested=task.pause_requested_at is not None,
        cancel_requested=task.cancel_requested_at is not None,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )


@router.post("", response_model=ChatTaskOut, status_code=status.HTTP_202_ACCEPTED)
async def create_chat_task(
    payload: ChatTaskCreate,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
    queue: QueueDep,
    redis: RedisDep,
) -> ChatTaskOut:
    provider_id = payload.provider_id
    model = payload.model
    if provider_id == "auto" or model == "auto":
        for candidate_provider, candidate_model in await route_candidates(session, registry, redis):
            provider_id, model = candidate_provider, candidate_model
            break
        if provider_id == "auto":
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                {
                    "code": "no_provider_available",
                    "message": "No provider is currently available",
                },
            )
    if provider_id != "auto":
        try:
            registry.get(provider_id)
            await ensure_model_capability(
                session,
                workspace_id=context.workspace.id,
                user_id=context.user.id,
                provider_id=provider_id,
                model_id=model,
                capability="chat",
            )
        except ProviderError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                {"code": "provider_not_found", "message": exc.message},
            ) from None
        except ProviderConfigError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": exc.code, "message": exc.message},
            ) from None
    try:
        task = await create_task(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            conversation_id=payload.conversation_id,
            kind=payload.kind,
            title=payload.title,
            provider_id=provider_id,
            model=model,
            steps=payload.steps,
        )
    except ChatTaskError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(task)
    try:
        await queue.enqueue_chat_task(task.id)
    except Exception:
        task.status = "failed"
        task.error_code = "queue_unavailable"
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {
                "code": "queue_unavailable",
                "message": "Task queue unavailable",
                "task_id": str(task.id),
            },
        ) from None
    return _out(task)


@router.get("", response_model=list[ChatTaskOut])
async def list_chat_tasks(
    context: JwtContext,
    session: SessionDep,
    conversation_id: UUID | None = None,
    status_filter: str | None = None,
) -> list[ChatTaskOut]:
    try:
        rows = await list_tasks(
            session,
            context.workspace.id,
            context.user.id,
            conversation_id=conversation_id,
            status=status_filter,
        )
    except ChatTaskError as exc:
        raise _error(exc) from None
    return [_out(row) for row in rows]


@router.get("/{task_id}", response_model=ChatTaskOut)
async def read_chat_task(task_id: UUID, context: JwtContext, session: SessionDep) -> ChatTaskOut:
    try:
        task = await get_task(session, task_id, context.workspace.id, context.user.id)
    except ChatTaskError as exc:
        raise _error(exc) from None
    return _out(task)


async def _control(
    task_id: UUID,
    context: AuthContext,
    session: AsyncSession,
    action,
    *,
    enqueue: bool = False,
    queue: JobQueue | None = None,
) -> ChatTaskOut:
    try:
        task = await get_task(session, task_id, context.workspace.id, context.user.id)
        task = await action(session, task)
    except ChatTaskError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(task)
    if enqueue and queue is not None:
        await queue.enqueue_chat_task(task.id)
    return _out(task)


@router.post("/{task_id}/pause", response_model=ChatTaskOut)
async def pause_chat_task(task_id: UUID, context: JwtContext, session: SessionDep) -> ChatTaskOut:
    return await _control(task_id, context, session, request_pause)


@router.post("/{task_id}/resume", response_model=ChatTaskOut)
async def resume_chat_task(
    task_id: UUID, context: JwtContext, session: SessionDep, queue: QueueDep
) -> ChatTaskOut:
    return await _control(task_id, context, session, request_resume, enqueue=True, queue=queue)


@router.post("/{task_id}/cancel", response_model=ChatTaskOut)
async def cancel_chat_task(task_id: UUID, context: JwtContext, session: SessionDep) -> ChatTaskOut:
    return await _control(task_id, context, session, request_cancel)


@router.post("/{task_id}/retry", response_model=ChatTaskOut)
async def retry_chat_task(
    task_id: UUID, context: JwtContext, session: SessionDep, queue: QueueDep
) -> ChatTaskOut:
    return await _control(task_id, context, session, request_retry, enqueue=True, queue=queue)


def _cursor(after: int | None, last_event_id: str | None) -> int:
    if after is not None:
        return after
    if last_event_id is not None:
        try:
            return max(0, int(last_event_id))
        except ValueError:
            return 0
    return 0


@router.get("/{task_id}/events")
async def chat_task_events(
    task_id: UUID,
    context: JwtContext,
    session: SessionDep,
    after: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    await get_task(session, task_id, context.workspace.id, context.user.id)
    cursor = _cursor(after, last_event_id)

    async def stream():
        position = cursor
        last_ping = time.monotonic()
        while True:
            async with SessionLocal() as poll:
                task = await poll.get(ChatTask, task_id)
                if task is None:
                    return
                events = await list_events(poll, task_id, position)
            for event in events:
                payload = json.dumps(event.payload, ensure_ascii=False)
                yield f"id: {event.seq}\nevent: {event.event}\ndata: {payload}\n\n"
                position = event.seq
            if task.status in TERMINAL_STATUSES:
                return
            if task.status in PAUSED_STATUSES:
                return
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
