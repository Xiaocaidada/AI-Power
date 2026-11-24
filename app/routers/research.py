from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.db import get_session
from app.deps import AuthContext, get_jwt_context, get_scoped_registry
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas import (
    ChatTaskOut,
    ResearchFollowupIn,
    ResearchPlanUpdate,
    ResearchSectionRegenerateIn,
    ResearchTaskCreate,
    TaskSaveToKnowledgeIn,
    TaskSaveToProjectIn,
)
from app.services.chat_modes import (
    ChatModeError,
    ensure_thinking_supported,
    resolve_model_capabilities,
)
from app.services.chat_tasks import (
    ChatTaskError,
    append_event,
    get_task,
    list_tasks,
    resolve_task_model,
)
from app.services.queue import JobQueue, get_queue
from app.services.research import (
    build_research_answer,
    confirm_research_plan,
    create_research_task,
    regenerate_section,
    save_task_report_to_knowledge,
    save_task_report_to_project,
    update_research_plan,
)

router = APIRouter(prefix="/research/tasks", tags=["research"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_scoped_registry)]
QueueDep = Annotated[JobQueue, Depends(get_queue)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]


def _task_error(exc: ChatTaskError) -> HTTPException:
    if exc.code in {"task_not_found", "conversation_not_found", "project_not_found"}:
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    if exc.code in {"plan_locked", "plan_not_pending", "task_not_completed"}:
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


async def _research_task(session: AsyncSession, task_id: UUID, context: AuthContext):
    try:
        task = await get_task(session, task_id, context.workspace.id, context.user.id)
    except ChatTaskError as exc:
        raise _task_error(exc) from None
    if task.kind != "research":
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            {"code": "task_not_found", "message": "Research task not found"},
        )
    return task


async def _task_provider(task, registry: ProviderRegistry) -> tuple[object, str]:
    input_payload = dict(task.input or {})
    provider_id = str(input_payload.get("provider_id") or "")
    model = str(input_payload.get("model") or "")
    try:
        return registry.get(provider_id), model
    except ProviderError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": "provider_not_found", "message": "Provider is not available"},
        ) from None


@router.post("", response_model=ChatTaskOut, status_code=status.HTTP_201_CREATED)
async def create_research(
    payload: ResearchTaskCreate,
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
        task = await create_research_task(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            conversation_id=payload.conversation_id,
            provider_id=provider_id,
            model=model,
            topic=payload.topic,
            questions=payload.questions,
            scope=payload.scope,
            kb_ids=payload.kb_ids,
            search_provider_id=payload.search_provider_id,
            language=payload.language,
            max_steps=payload.max_steps,
            thinking_level=payload.thinking_level,
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
async def list_research_tasks(
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
            kind="research",
        )
    except ChatTaskError as exc:
        raise _task_error(exc) from None
    return [_out(row) for row in rows]


@router.get("/{task_id}", response_model=ChatTaskOut)
async def read_research_task(
    task_id: UUID, context: JwtContext, session: SessionDep
) -> ChatTaskOut:
    task = await _research_task(session, task_id, context)
    return _out(task)


@router.patch("/{task_id}/plan", response_model=ChatTaskOut)
async def edit_research_plan(
    task_id: UUID,
    payload: ResearchPlanUpdate,
    context: JwtContext,
    session: SessionDep,
) -> ChatTaskOut:
    task = await _research_task(session, task_id, context)
    try:
        task = await update_research_plan(
            session, task, [item.model_dump() for item in payload.steps]
        )
    except ChatTaskError as exc:
        raise _task_error(exc) from None
    await session.commit()
    await session.refresh(task)
    return _out(task)


@router.post("/{task_id}/confirm", response_model=ChatTaskOut)
async def confirm_research(
    task_id: UUID,
    context: JwtContext,
    session: SessionDep,
    queue: QueueDep,
) -> ChatTaskOut:
    task = await _research_task(session, task_id, context)
    try:
        task = await confirm_research_plan(session, task)
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


@router.post("/{task_id}/followup")
async def research_followup(
    task_id: UUID,
    payload: ResearchFollowupIn,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
) -> dict[str, str]:
    task = await _research_task(session, task_id, context)
    if task.status != "completed":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "task_not_completed", "message": "Research report is not ready"},
        )
    provider, model = await _task_provider(task, registry)
    thinking_level = str((task.input or {}).get("thinking_level") or "standard")
    try:
        answer = await build_research_answer(
            task=task,
            provider=provider,
            model=model,
            question=payload.question,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            thinking_level=thinking_level,
        )
    except ChatTaskError as exc:
        raise _task_error(exc) from None
    result = dict(task.result or {})
    followups = list(result.get("followups") or [])
    followups.append({"question": payload.question, "answer": answer})
    task.result = {**result, "followups": followups[-20:]}
    await append_event(
        session,
        task.id,
        "research_followup",
        {"question": payload.question, "answer": answer[:1000]},
    )
    await session.commit()
    return {"answer": answer}


@router.post("/{task_id}/sections/{section}/regenerate", response_model=ChatTaskOut)
async def regenerate_research_section(
    task_id: UUID,
    section: str,
    payload: ResearchSectionRegenerateIn,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
) -> ChatTaskOut:
    if section != payload.section:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "section_mismatch", "message": "Section does not match the path"},
        )
    task = await _research_task(session, task_id, context)
    if task.status != "completed":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "task_not_completed", "message": "Research report is not ready"},
        )
    provider, model = await _task_provider(task, registry)
    try:
        sections, report = await regenerate_section(
            task=task,
            provider=provider,
            model=model,
            section=section,
            instruction=payload.instruction,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            thinking_level=str((task.input or {}).get("thinking_level") or "standard"),
        )
    except ChatTaskError as exc:
        raise _task_error(exc) from None
    result = dict(task.result or {})
    task.result = {**result, "sections": sections, "report": report}
    await append_event(
        session,
        task.id,
        "research_section_regenerated",
        {"section": section, "instruction": payload.instruction[:300]},
    )
    await session.commit()
    await session.refresh(task)
    return _out(task)


@router.post("/{task_id}/save-to-knowledge")
async def save_research_to_knowledge(
    task_id: UUID,
    payload: TaskSaveToKnowledgeIn,
    context: JwtContext,
    session: SessionDep,
    queue: QueueDep,
) -> dict:
    task = await _research_task(session, task_id, context)
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


@router.post("/{task_id}/save-to-project")
async def save_research_to_project(
    task_id: UUID,
    payload: TaskSaveToProjectIn,
    context: JwtContext,
    session: SessionDep,
    queue: QueueDep,
) -> dict:
    task = await _research_task(session, task_id, context)
    try:
        saved = await save_task_report_to_project(
            session,
            task=task,
            queue=queue,
            project_id=payload.project_id,
            kb_id=payload.kb_id,
            title=payload.title,
        )
    except ChatTaskError as exc:
        raise _task_error(exc) from None
    return {
        "document_id": str(saved["document_id"]),
        "project_id": str(saved["project_id"]),
        "status": saved["status"],
        "duplicate": saved["duplicate"],
    }