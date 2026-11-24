from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.db import get_session
from app.deps import AuthContext, get_jwt_context, get_scoped_registry
from app.providers.registry import ProviderRegistry
from app.schemas import (
    AgentPlanUpdate,
    AgentTaskCreate,
    ChatTaskOut,
    TaskApprovalIn,
    TaskSaveToKnowledgeIn,
)
from app.services.agent_tasks import (
    confirm_agent_plan,
    create_agent_task,
    decide_approval,
    update_agent_plan,
)
from app.services.chat_modes import (
    ChatModeError,
    ensure_thinking_supported,
    resolve_model_capabilities,
)
from app.services.chat_tasks import (
    ChatTaskError,
    get_task,
    list_tasks,
    resolve_task_model,
)
from app.services.queue import JobQueue, get_queue
from app.services.research import save_task_report_to_knowledge

router = APIRouter(prefix="/agent-tasks", tags=["agent-tasks"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_scoped_registry)]
QueueDep = Annotated[JobQueue, Depends(get_queue)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]


def _task_error(exc: ChatTaskError) -> HTTPException:
    if exc.code in {"task_not_found", "conversation_not_found", "agent_not_found"}:
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    if exc.code in {
        "plan_locked",
        "plan_not_pending",
        "task_not_completed",
        "approval_resolved",
        "approval_unavailable",
    }:
        return HTTPException(status.HTTP_409_CONFLICT, {"code": exc.code, "message": exc.message})
    if exc.code == "provider_not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    if exc.code == "no_provider_available":
        return HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": exc.code, "message": exc.message},
        )
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"code": exc.code, "message": exc.message},
    )


def _out(task) -> ChatTaskOut:
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


async def _agent_task(session: AsyncSession, task_id: UUID, context: AuthContext):
    try:
        task = await get_task(session, task_id, context.workspace.id, context.user.id)
    except ChatTaskError as exc:
        raise _task_error(exc) from None
    if task.kind != "agent":
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "task_not_found", "message": "Agent task not found"},
        )
    return task


@router.post("", response_model=ChatTaskOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentTaskCreate,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
    redis: RedisDep,
) -> ChatTaskOut:
    try:
        provider_id, model = await resolve_task_model(
            session,
            registry,
            redis,
            provider_id=payload.provider_id,
            model=payload.model,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
        )
        capabilities = await resolve_model_capabilities(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            provider_id=provider_id,
            model_id=model,
        )
        ensure_thinking_supported(
            payload.thinking_level,
            capabilities=capabilities.capabilities,
            reasoning_levels=capabilities.reasoning_levels,
        )
        task = await create_agent_task(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            conversation_id=payload.conversation_id,
            provider_id=provider_id,
            model=model,
            goal=payload.goal,
            agent_id=payload.agent_id,
            plugin_ids=payload.plugin_ids,
            kb_ids=payload.kb_ids,
            max_steps=payload.max_steps,
            thinking_level=payload.thinking_level,
            language=payload.language,
            provider=registry.get(provider_id),
        )
    except ChatModeError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": exc.code, "message": exc.message},
        ) from None
    except ChatTaskError as exc:
        raise _task_error(exc) from None
    await session.commit()
    await session.refresh(task)
    return _out(task)


@router.get("", response_model=list[ChatTaskOut])
async def list_agent_tasks(
    context: JwtContext,
    session: SessionDep,
    status_filter: str | None = None,
    conversation_id: UUID | None = None,
) -> list[ChatTaskOut]:
    try:
        rows = await list_tasks(
            session,
            context.workspace.id,
            context.user.id,
            conversation_id=conversation_id,
            status=status_filter,
            kind="agent",
        )
    except ChatTaskError as exc:
        raise _task_error(exc) from None
    return [_out(row) for row in rows]


@router.get("/{task_id}", response_model=ChatTaskOut)
async def read_agent_task(
    task_id: UUID, context: JwtContext, session: SessionDep
) -> ChatTaskOut:
    task = await _agent_task(session, task_id, context)
    return _out(task)


@router.patch("/{task_id}/plan", response_model=ChatTaskOut)
async def edit_agent_plan(
    task_id: UUID,
    payload: AgentPlanUpdate,
    context: JwtContext,
    session: SessionDep,
) -> ChatTaskOut:
    task = await _agent_task(session, task_id, context)
    try:
        task = await update_agent_plan(
            session, task, [item.model_dump() for item in payload.steps]
        )
    except ChatTaskError as exc:
        raise _task_error(exc) from None
    await session.commit()
    await session.refresh(task)
    return _out(task)


@router.post("/{task_id}/confirm", response_model=ChatTaskOut)
async def confirm_agent(
    task_id: UUID,
    context: JwtContext,
    session: SessionDep,
    queue: QueueDep,
) -> ChatTaskOut:
    task = await _agent_task(session, task_id, context)
    try:
        task = await confirm_agent_plan(session, task)
    except ChatTaskError as exc:
        raise _task_error(exc) from None
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
            {"code": "queue_unavailable", "message": "Task queue unavailable"},
        ) from None
    return _out(task)


@router.post("/{task_id}/approval", response_model=ChatTaskOut)
async def resolve_approval(
    task_id: UUID,
    payload: TaskApprovalIn,
    context: JwtContext,
    session: SessionDep,
    queue: QueueDep,
) -> ChatTaskOut:
    task = await _agent_task(session, task_id, context)
    try:
        task = await decide_approval(
            session,
            task,
            approval_id=payload.approval_id,
            decision=payload.decision,
            note=payload.note,
        )
    except ChatTaskError as exc:
        raise _task_error(exc) from None
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
            {"code": "queue_unavailable", "message": "Task queue unavailable"},
        ) from None
    return _out(task)


@router.post("/{task_id}/save-to-knowledge")
async def save_agent_output_to_knowledge(
    task_id: UUID,
    payload: TaskSaveToKnowledgeIn,
    context: JwtContext,
    session: SessionDep,
    queue: QueueDep,
) -> dict:
    task = await _agent_task(session, task_id, context)
    try:
        saved = await save_task_report_to_knowledge(
            session,
            task=task,
            queue=queue,
            kb_id=payload.kb_id,
            title=payload.title,
        )
    except ChatTaskError as exc:
        raise _task_error(exc) from None
    return {
        "document_id": str(saved["document_id"]),
        "status": saved["status"],
        "duplicate": saved["duplicate"],
    }