import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatTask, ChatTaskEvent, Conversation
from app.providers.base import ChatMessage
from app.services.chat_modes import thinking_provider_opts
from app.services.model_stream import ModelCompletion
from app.services.provider_configs import build_user_registry
from app.services.usage_ledger import SOURCE_CHAT_TASK

logger = logging.getLogger(__name__)

TASK_STATUSES = (
    "queued",
    "running",
    "waiting_approval",
    "paused",
    "completed",
    "failed",
    "cancelled",
)
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
PAUSED_STATUSES = frozenset({"paused", "waiting_approval"})
TASK_KINDS = ("llm_steps", "research", "agent")
GENERIC_TASK_KINDS = ("llm_steps",)
LEASE_MINUTES = 5


class ChatTaskError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def append_event(
    session: AsyncSession,
    task_id: UUID,
    event: str,
    payload: dict[str, Any] | None = None,
) -> ChatTaskEvent:
    current = await session.scalar(
        select(func.max(ChatTaskEvent.seq)).where(ChatTaskEvent.task_id == task_id)
    )
    row = ChatTaskEvent(
        task_id=task_id,
        seq=int(current or 0) + 1,
        event=event,
        payload=payload or {},
    )
    session.add(row)
    await session.flush()
    return row


async def get_task(
    session: AsyncSession, task_id: UUID, workspace_id: UUID, user_id: UUID
) -> ChatTask:
    task = (
        await session.execute(
            select(ChatTask).where(
                ChatTask.id == task_id,
                ChatTask.workspace_id == workspace_id,
                ChatTask.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if task is None:
        raise ChatTaskError("task_not_found", "Chat task not found")
    return task


async def list_tasks(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    *,
    conversation_id: UUID | None = None,
    status: str | None = None,
    kind: str | None = None,
) -> list[ChatTask]:
    conditions = [
        ChatTask.workspace_id == workspace_id,
        ChatTask.user_id == user_id,
    ]
    if conversation_id is not None:
        conditions.append(ChatTask.conversation_id == conversation_id)
    if kind is not None:
        if kind not in TASK_KINDS:
            raise ChatTaskError("invalid_kind", "Unsupported task kind")
        conditions.append(ChatTask.kind == kind)
    if status is not None:
        if status not in TASK_STATUSES:
            raise ChatTaskError("invalid_status", "Unsupported task status")
        conditions.append(ChatTask.status == status)
    return list(
        (
            await session.execute(
                select(ChatTask)
                .where(*conditions)
                .order_by(ChatTask.created_at.desc(), ChatTask.id.desc())
                .limit(100)
            )
        ).scalars()
    )


async def create_task(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    conversation_id: UUID | None,
    kind: str,
    title: str,
    provider_id: str,
    model: str,
    steps: list[str],
) -> ChatTask:
    if kind not in GENERIC_TASK_KINDS:
        raise ChatTaskError("invalid_kind", "Unsupported task kind")
    clean_steps = [step.strip() for step in steps if step.strip()]
    if not clean_steps:
        raise ChatTaskError("steps_required", "At least one step is required")
    if conversation_id is not None:
        conversation = (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.workspace_id == workspace_id,
                    Conversation.user_id == user_id,
                    Conversation.archived_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if conversation is None:
            raise ChatTaskError("conversation_not_found", "Conversation not found")
    task = ChatTask(
        workspace_id=workspace_id,
        user_id=user_id,
        conversation_id=conversation_id,
        kind=kind,
        title=(title or "").strip()[:200],
        status="queued",
        input={
            "provider_id": provider_id,
            "model": model,
            "steps": clean_steps[:20],
        },
        plan={
            "steps": [
                {"index": index, "status": "pending", "prompt": step[:500]}
                for index, step in enumerate(clean_steps[:20])
            ]
        },
        checkpoint={"completed_steps": 0, "outputs": []},
        result={},
    )
    session.add(task)
    await session.flush()
    await append_event(
        session,
        task.id,
        "task_created",
        {"kind": kind, "steps": len(clean_steps), "status": "queued"},
    )
    return task


async def request_pause(session: AsyncSession, task: ChatTask) -> ChatTask:
    if task.status in TERMINAL_STATUSES:
        raise ChatTaskError("task_terminal", "Task has already finished")
    if task.status == "paused":
        return task
    now = datetime.now(UTC)
    task.pause_requested_at = now
    if task.status == "queued":
        task.status = "paused"
        task.finished_at = None
        await append_event(session, task.id, "task_paused", {"status": "paused"})
    else:
        await append_event(session, task.id, "task_pause_requested", {"status": task.status})
    await session.flush()
    return task


async def request_resume(session: AsyncSession, task: ChatTask) -> ChatTask:
    if task.status == "running":
        return task
    if task.status not in {"paused", "waiting_approval"}:
        raise ChatTaskError("task_not_paused", "Task is not paused")
    task.status = "queued"
    task.pause_requested_at = None
    task.error_code = None
    task.finished_at = None
    await append_event(session, task.id, "task_resumed", {"status": "queued"})
    await session.flush()
    return task


async def request_cancel(
    session: AsyncSession, task: ChatTask, *, immediate: bool = False
) -> ChatTask:
    if task.status in TERMINAL_STATUSES:
        return task
    now = datetime.now(UTC)
    if immediate or task.status in {"queued", "paused", "waiting_approval"}:
        task.status = "cancelled"
        task.cancel_requested_at = now
        task.finished_at = now
        task.lease_expires_at = None
        await append_event(session, task.id, "task_cancelled", {"status": "cancelled"})
    else:
        task.cancel_requested_at = now
        await append_event(session, task.id, "task_cancel_requested", {"status": task.status})
    await session.flush()
    return task


async def request_retry(session: AsyncSession, task: ChatTask) -> ChatTask:
    if task.status != "failed":
        raise ChatTaskError("task_not_failed", "Only failed tasks can be retried")
    task.status = "queued"
    task.error_code = None
    task.cancel_requested_at = None
    task.pause_requested_at = None
    task.finished_at = None
    task.lease_expires_at = None
    await append_event(session, task.id, "task_retry_requested", {"status": "queued"})
    await session.flush()
    return task


async def list_events(session: AsyncSession, task_id: UUID, after: int) -> list[ChatTaskEvent]:
    return list(
        (
            await session.execute(
                select(ChatTaskEvent)
                .where(
                    ChatTaskEvent.task_id == task_id,
                    ChatTaskEvent.seq > after,
                )
                .order_by(ChatTaskEvent.seq)
            )
        ).scalars()
    )


async def resolve_task_model(
    session: AsyncSession,
    registry,
    redis,
    *,
    provider_id: str,
    model: str,
    workspace_id: UUID,
    user_id: UUID,
) -> tuple[str, str]:
    """Resolve ``auto`` and validate that the model supports chat."""
    from app.providers.base import ProviderError
    from app.services.provider_configs import ProviderConfigError, ensure_model_capability
    from app.services.routing import route_candidates

    resolved_provider = provider_id
    resolved_model = model
    if provider_id == "auto" or model == "auto":
        for candidate_provider, candidate_model in await route_candidates(
            session, registry, redis
        ):
            resolved_provider, resolved_model = candidate_provider, candidate_model
            break
        if resolved_provider == "auto":
            raise ChatTaskError("no_provider_available", "No provider is currently available")
    try:
        registry.get(resolved_provider)
        await ensure_model_capability(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            provider_id=resolved_provider,
            model_id=resolved_model,
            capability="chat",
        )
    except ProviderError as exc:
        raise ChatTaskError("provider_not_found", exc.message) from None
    except ProviderConfigError as exc:
        raise ChatTaskError(exc.code, exc.message) from None
    return resolved_provider, resolved_model


async def mark_task_started(session: AsyncSession, task: ChatTask) -> bool:
    """Emit ``task_started`` for a claimed task; returns False when it should stop."""
    if task.status in TERMINAL_STATUSES:
        return False
    if task.cancel_requested_at is not None:
        await request_cancel(session, task, immediate=True)
        await session.commit()
        return False
    await append_event(
        session,
        task.id,
        "task_started",
        {
            "attempt": task.attempts,
            "completed_steps": (task.checkpoint or {}).get("completed_steps", 0),
        },
    )
    await session.commit()
    return True


def _renew_lease(task: ChatTask) -> None:
    task.lease_expires_at = datetime.now(UTC) + timedelta(minutes=LEASE_MINUTES)


async def touch_lease(task: ChatTask) -> None:
    _renew_lease(task)


async def checkpoint_or_stop(
    session: AsyncSession,
    task: ChatTask,
    checkpoint: dict[str, Any],
    completed_steps: int,
) -> bool:
    """Persist progress and honour cancel/pause at a safe step boundary."""
    if task.status in TERMINAL_STATUSES:
        return False
    if task.cancel_requested_at is not None:
        await request_cancel(session, task, immediate=True)
        await session.commit()
        return False
    task.checkpoint = checkpoint
    if task.pause_requested_at is not None:
        task.status = "paused"
        task.lease_expires_at = None
        task.pause_requested_at = None
        await append_event(
            session,
            task.id,
            "task_paused",
            {"completed_steps": completed_steps},
        )
        await session.commit()
        return False
    _renew_lease(task)
    return True


async def fail_task(
    session: AsyncSession, task: ChatTask, code: str, message: str
) -> None:
    await _fail(session, task, code, message)


async def finish_task(
    session: AsyncSession,
    task: ChatTask,
    result: dict[str, Any],
    event: str,
    payload: dict[str, Any] | None = None,
) -> None:
    task.status = "completed"
    task.result = result
    task.finished_at = datetime.now(UTC)
    task.lease_expires_at = None
    await append_event(session, task.id, event, payload or {})
    await append_event(session, task.id, "task_completed", {"status": "completed"})
    await session.commit()


async def _fail(session: AsyncSession, task: ChatTask, code: str, message: str) -> None:
    task.status = "failed"
    task.error_code = code
    task.finished_at = datetime.now(UTC)
    task.lease_expires_at = None
    await append_event(
        session,
        task.id,
        "task_failed",
        {
            "code": code,
            "message": message,
            "completed_steps": (task.checkpoint or {}).get("completed_steps", 0),
        },
    )
    await session.commit()


async def execute_chat_task(task_id: UUID, provider_registry=None) -> None:
    from app.db import SessionLocal

    async with SessionLocal() as session:
        claimed = await session.execute(
            update(ChatTask)
            .where(ChatTask.id == task_id, ChatTask.status == "queued")
            .values(
                status="running",
                attempts=ChatTask.attempts + 1,
                started_at=datetime.now(UTC),
                finished_at=None,
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=LEASE_MINUTES),
            )
        )
        if claimed.rowcount == 0:
            await session.rollback()
            return
        await session.commit()
        task = await session.get(ChatTask, task_id)
        if task is None:
            return
        kind = task.kind
        if kind in {"research", "agent"}:
            await session.rollback()
            if kind == "research":
                from app.services.research import execute_research_task

                await execute_research_task(task_id, provider_registry)
            else:
                from app.services.agent_tasks import execute_agent_task

                await execute_agent_task(task_id, provider_registry)
            return
        if not await mark_task_started(session, task):
            return

        workspace_id = task.workspace_id
        user_id = task.user_id
        input_payload = dict(task.input or {})
        checkpoint = dict(task.checkpoint or {})
        registry = provider_registry or await build_user_registry(session, workspace_id, user_id)
        provider_id = str(input_payload.get("provider_id") or "")
        model = str(input_payload.get("model") or "")
        steps = list(input_payload.get("steps") or [])
        try:
            provider = registry.get(provider_id)
        except Exception:
            await _fail(session, task, "provider_not_found", "Provider is not available")
            return
        if not steps:
            await _fail(session, task, "steps_required", "Task has no steps")
            return

    outputs = list(checkpoint.get("outputs") or [])
    completed = int(checkpoint.get("completed_steps") or 0)
    for index in range(completed, len(steps)):
        async with SessionLocal() as session:
            current = await session.get(ChatTask, task_id)
            if current is None:
                return
            if current.cancel_requested_at is not None:
                await request_cancel(session, current, immediate=True)
                await session.commit()
                return
            if current.pause_requested_at is not None:
                current.status = "paused"
                current.lease_expires_at = None
                current.pause_requested_at = None
                await append_event(
                    session,
                    current.id,
                    "task_paused",
                    {"completed_steps": completed},
                )
                await session.commit()
                return
            current.lease_expires_at = datetime.now(UTC) + timedelta(minutes=LEASE_MINUTES)
            await append_event(
                session,
                current.id,
                "step_started",
                {"index": index, "total": len(steps)},
            )
            await session.commit()

        completion = ModelCompletion(
            provider=provider,
            model=model,
            messages=[ChatMessage(role="user", content=steps[index])],
            opts={
                "temperature": 0.2,
                "max_tokens": 2000,
                **thinking_provider_opts(
                    str(input_payload.get("thinking_level") or "standard")
                ),
            },
            workspace_id=workspace_id,
            user_id=user_id,
            source=SOURCE_CHAT_TASK,
        )
        metrics = await completion.run()
        async with SessionLocal() as session:
            current = await session.get(ChatTask, task_id)
            if current is None:
                return
            if metrics.status != "completed":
                await _fail(
                    session,
                    current,
                    metrics.error_code or "task_step_failed",
                    "Task step failed",
                )
                return
            outputs.append(metrics.content)
            current.checkpoint = {
                "completed_steps": index + 1,
                "outputs": outputs,
            }
            plan = dict(current.plan or {})
            plan_steps = list(plan.get("steps") or [])
            if index < len(plan_steps):
                plan_steps[index] = {**plan_steps[index], "status": "done"}
            plan["steps"] = plan_steps
            current.plan = plan
            current.lease_expires_at = datetime.now(UTC) + timedelta(minutes=LEASE_MINUTES)
            await append_event(
                session,
                current.id,
                "step_completed",
                {
                    "index": index,
                    "total": len(steps),
                    "prompt_tokens": metrics.prompt_tokens,
                    "completion_tokens": metrics.completion_tokens,
                    "summary": metrics.content[:300],
                },
            )
            await session.commit()

    async with SessionLocal() as session:
        current = await session.get(ChatTask, task_id)
        if current is None:
            return
        if current.cancel_requested_at is not None:
            await request_cancel(session, current, immediate=True)
            await session.commit()
            return
        current.status = "completed"
        current.result = {"outputs": outputs, "text": "\n\n".join(outputs)}
        current.finished_at = datetime.now(UTC)
        current.lease_expires_at = None
        await append_event(
            session,
            current.id,
            "task_completed",
            {"steps": len(outputs), "status": "completed"},
        )
        await session.commit()


async def requeue_stale_tasks(session: AsyncSession) -> list[UUID]:
    stale = list(
        (
            await session.execute(
                select(ChatTask).where(
                    ChatTask.status == "running",
                    ChatTask.lease_expires_at.is_not(None),
                    ChatTask.lease_expires_at < datetime.now(UTC),
                )
            )
        ).scalars()
    )
    ids: list[UUID] = []
    for task in stale:
        task.status = "queued"
        task.lease_expires_at = None
        await append_event(session, task.id, "task_requeued", {"reason": "stale_lease"})
        ids.append(task.id)
    if ids:
        await session.commit()
    return ids
