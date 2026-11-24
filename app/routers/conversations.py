import asyncio
import json
import logging
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, delete, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentSpec
from app.agents.registry import SUPERVISOR_AGENT, AgentRegistry
from app.clients import RedisLike, get_redis
from app.config import get_settings
from app.db import SessionLocal, get_session
from app.deps import (
    AuthContext,
    get_agent_registry,
    get_jwt_context,
    get_scoped_registry,
    get_tool_registry,
    require_scope,
)
from app.metrics import record_usage_metrics, track_sse_stream
from app.models import (
    ChatAttachment,
    Conversation,
    ConversationKnowledgeBase,
    ConversationPlugin,
    CustomAgent,
    Document,
    Message,
    MessageCitation,
    MessageFeedback,
    Project,
    Trace,
)
from app.observability import request_id_var
from app.providers.base import ChatChunk, ChatMessage, LLMProvider, ProviderError, Usage
from app.providers.registry import ProviderRegistry
from app.schemas import (
    AttachmentOut,
    CitationOut,
    ConversationBatchIn,
    ConversationBatchOut,
    ConversationCreate,
    ConversationDetailOut,
    ConversationOut,
    ConversationPluginOut,
    ConversationPluginsIn,
    ConversationUpdate,
    ErrorOut,
    MessageEditOut,
    MessageFeedbackIn,
    MessageFeedbackOut,
    MessageOut,
    MessageUpdateIn,
    PluginCallOut,
    SendMessageIn,
)
from app.services.access import get_owned_knowledge_base
from app.services.agent import AgentFailure, AgentRunner
from app.services.agent_tools import build_mcp_tool_specs
from app.services.attachments import (
    AttachmentError,
    attachments_by_message,
    attachments_for_message,
    build_user_content,
    claim_attachments,
    delete_attachment_rows,
    is_image,
    unlinked_conversation_attachments,
)
from app.services.budget import check_workspace_budget
from app.services.custom_agents import (
    CustomAgentError,
    build_agent_spec,
    get_custom_agent,
)
from app.services.generation import normalize_generation_settings
from app.services.memories import (
    get_memory_settings,
    record_memory_usage,
    select_memories,
)
from app.services.memory_permissions import (
    MemoryAccess,
    agent_memory_access,
    project_allows_global,
    project_memory_allowed,
)
from app.services.plugins import (
    PluginError,
    build_plugin_tools,
    confirm_conversation_plugin,
    list_conversation_plugins,
    list_plugin_calls,
    plugin_tool_names,
    set_conversation_plugins,
)
from app.services.projects import ProjectError, get_project
from app.services.prompts import resolve_conversation_prompt
from app.services.provider_configs import ProviderConfigError, ensure_model_capability
from app.services.quotas import add_token_usage, enforce_quota
from app.services.rag import build_rag_messages, fit_context
from app.services.retrieval import Citation, build_citations, retrieve_chunks
from app.services.routing import record_failure, reset_failures, route_candidates
from app.services.usage_ledger import SOURCE_CHAT, write_usage_event
from app.services.webhooks import enqueue_event
from app.tools.base import ToolContext, ToolRegistry

router = APIRouter(prefix="/conversations", tags=["conversations"])
messages_router = APIRouter(prefix="/messages", tags=["conversations"])
logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
ChatContext = Annotated[AuthContext, Depends(require_scope("chat:write"))]
ReadContext = Annotated[AuthContext, Depends(require_scope("kb:read"))]
RedisDep = Annotated[RedisLike, Depends(get_redis)]
ToolRegistryDep = Annotated[ToolRegistry, Depends(get_tool_registry)]
AgentRegistryDep = Annotated[AgentRegistry, Depends(get_agent_registry)]

HISTORY_MESSAGE_LIMIT = 12
TITLE_MAX_LENGTH = 30


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _get_workspace_conversation(
    conversation_id: UUID,
    workspace_id: UUID,
    session: AsyncSession,
    *,
    include_archived: bool = False,
) -> Conversation:
    conditions = [
        Conversation.id == conversation_id,
        Conversation.workspace_id == workspace_id,
    ]
    if not include_archived:
        conditions.append(Conversation.archived_at.is_(None))
    conversation = (
        await session.execute(select(Conversation).where(*conditions))
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


async def _get_owned_conversation(
    conversation_id: UUID, workspace_id: UUID, session: AsyncSession
) -> Conversation:
    return await _get_workspace_conversation(conversation_id, workspace_id, session)


def _normalize_generation_settings(values: dict[str, object] | None) -> dict[str, object]:
    return normalize_generation_settings(values)


def _generation_opts(conversation: Conversation) -> dict[str, object]:
    return _normalize_generation_settings(conversation.generation_settings)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def _validate_model_choice(
    session: AsyncSession,
    registry: ProviderRegistry,
    context: AuthContext,
    *,
    provider_id: str,
    model: str,
    agent: bool,
) -> None:
    if provider_id == "auto":
        return
    try:
        registry.get(provider_id)
        await ensure_model_capability(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            provider_id=provider_id,
            model_id=model,
            capability="tools" if agent else "chat",
        )
    except ProviderError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    except ProviderConfigError as exc:
        status_code = (
            status.HTTP_404_NOT_FOUND
            if exc.code in {"not_found", "model_not_found"}
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(status_code, {"code": exc.code, "message": exc.message}) from None


async def _validate_attachment_images(
    session: AsyncSession,
    context: AuthContext,
    *,
    provider_id: str,
    model: str,
    agent: bool,
    attachments: Sequence[ChatAttachment],
) -> None:
    if not any(is_image(item) for item in attachments):
        return
    if agent:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "image_agent_unsupported",
                "message": "Image attachments are not supported in agent mode",
            },
        )
    if provider_id == "auto":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "vision_model_required",
                "message": "Choose a vision-capable model for image attachments",
            },
        )
    try:
        await ensure_model_capability(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            provider_id=provider_id,
            model_id=model,
            capability="vision",
        )
    except (ProviderError, ProviderConfigError):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "model_missing_vision",
                "message": "The selected model does not support image input",
            },
        ) from None


async def _require_project(session: AsyncSession, workspace_id: UUID, project_id: UUID):
    try:
        return await get_project(session, workspace_id, project_id)
    except ProjectError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found") from None


async def _update_trace(
    trace_id: UUID,
    *,
    status: str | None = None,
    error_code: str | None = None,
    ttft_ms: float | None = None,
    total_ms: float | None = None,
    agents: list[dict[str, object]] | None = None,
) -> None:
    try:
        async with SessionLocal() as session:
            trace = await session.get(Trace, trace_id)
            if trace is None:
                return
            if status is not None:
                trace.status = status
            if error_code is not None:
                trace.error_code = error_code
            if ttft_ms is not None:
                trace.ttft_ms = ttft_ms
            if total_ms is not None:
                trace.total_ms = total_ms
            if agents is not None:
                trace.agents = agents
            await session.commit()
    except Exception:
        logger.exception("failed to update trace %s", trace_id)


async def _finalize(
    message_id: UUID,
    content: str,
    message_status: str,
    usage: Usage | None,
    workspace_id: UUID,
    citations: Sequence[Citation] = (),
    redis: RedisLike | None = None,
    api_key_id: UUID | None = None,
) -> None:
    try:
        async with SessionLocal() as session:
            message = await session.get(Message, message_id)
            if message is None:
                return
            message.content = content
            message.status = message_status
            message.prompt_tokens = usage.prompt_tokens if usage else None
            message.completion_tokens = usage.completion_tokens if usage else None
            cost_value = 0.0

            if message.role == "assistant":
                written = await write_usage_event(
                    session,
                    workspace_id=workspace_id,
                    user_id=message.user_id,
                    source=SOURCE_CHAT,
                    conversation_id=message.conversation_id,
                    message_id=message.id,
                    api_key_id=api_key_id,
                    provider_id=message.provider_id,
                    model=message.model,
                    prompt_tokens=message.prompt_tokens,
                    completion_tokens=message.completion_tokens,
                )
                if written is not None:
                    cost_value = written.cost
                    record_usage_metrics(
                        prompt_tokens=message.prompt_tokens,
                        completion_tokens=message.completion_tokens,
                        cost=written.cost,
                        provider_id=message.provider_id,
                        model=message.model,
                        source=SOURCE_CHAT,
                    )
                    await check_workspace_budget(session, redis, workspace_id)
                if citations:
                    existing_citations = await session.execute(
                        select(MessageCitation.id)
                        .where(MessageCitation.message_id == message_id)
                        .limit(1)
                    )
                    if existing_citations.scalar_one_or_none() is None:
                        session.add_all(
                            [
                                MessageCitation(
                                    message_id=message.id,
                                    citation_index=citation.index,
                                    document_id=citation.document_id,
                                    chunk_id=citation.chunk_id,
                                    page_no=citation.page_no,
                                    snippet=citation.snippet,
                                )
                                for citation in citations
                            ]
                        )
            conversation = await session.get(Conversation, message.conversation_id)
            if conversation is not None:
                conversation.updated_at = datetime.now(UTC)
            await session.commit()
            if message.role == "assistant":
                await enqueue_event(
                    workspace_id,
                    "message.completed",
                    {
                        "message_id": str(message.id),
                        "conversation_id": str(message.conversation_id),
                        "status": message.status,
                        "provider_id": message.provider_id,
                        "model": message.model,
                        "prompt_tokens": message.prompt_tokens,
                        "completion_tokens": message.completion_tokens,
                        "cost": cost_value,
                        "content": (content or "")[:2000],
                    },
                )
                if get_settings().memory_extraction_enabled:
                    from app.services.memory_extraction import (
                        schedule_memory_extraction,
                    )

                    await schedule_memory_extraction(message.id)
    except Exception:
        logger.exception("failed to finalize message %s", message_id)


async def _stream_reply(
    *,
    provider: LLMProvider,
    conversation_id: UUID,
    assistant_id: UUID,
    history: list[ChatMessage],
    model: str,
    workspace_id: UUID,
    citations: Sequence[Citation] = (),
    stream: AsyncIterator[ChatChunk] | None = None,
    first_chunk: ChatChunk | None = None,
    opts: dict[str, object] | None = None,
    redis: RedisLike | None = None,
    trace_id: UUID | None = None,
    started: float | None = None,
    api_key_id: UUID | None = None,
) -> AsyncIterator[str]:
    parts: list[str] = []
    usage: Usage | None = None
    finish_reason: str | None = None
    ttft_ms: float | None = None

    async def accrue_tokens() -> None:
        if redis is not None and usage is not None:
            await add_token_usage(
                redis,
                workspace_id,
                (usage.prompt_tokens or 0) + (usage.completion_tokens or 0),
            )

    try:
        yield _sse(
            "meta",
            {
                "message_id": str(assistant_id),
                "provider": provider.id,
                "model": model,
                "conversation_id": str(conversation_id),
            },
        )
        for citation in citations:
            yield _sse(
                "citation",
                {
                    "index": citation.index,
                    "document_id": str(citation.document_id),
                    "chunk_id": str(citation.chunk_id),
                    "page_no": citation.page_no,
                    "snippet": citation.snippet,
                },
            )
        chunk_stream = (
            stream
            if stream is not None
            else provider.stream_chat(history, model, **(opts or {}))
        )

        async def chunks() -> AsyncIterator[ChatChunk]:
            if first_chunk is not None:
                yield first_chunk
            async for item in chunk_stream:
                yield item

        async for chunk in chunks():
            if chunk.delta:
                if ttft_ms is None and trace_id is not None and started is not None:
                    ttft_ms = round((time.perf_counter() - started) * 1000, 1)
                    await _update_trace(trace_id, ttft_ms=ttft_ms)
                parts.append(chunk.delta)
                yield _sse("delta", {"text": chunk.delta})
            if chunk.usage is not None:
                usage = chunk.usage
            if chunk.finish_reason is not None:
                finish_reason = chunk.finish_reason
        if redis is not None:
            await reset_failures(redis, provider.id)

        yield _sse(
            "usage",
            {
                "prompt_tokens": usage.prompt_tokens if usage else None,
                "completion_tokens": usage.completion_tokens if usage else None,
            },
        )
        yield _sse("done", {"finish_reason": finish_reason})
        await accrue_tokens()
        if trace_id is not None and started is not None:
            await _update_trace(
                trace_id,
                status="completed",
                total_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        await _finalize(
            assistant_id,
            "".join(parts),
            "completed",
            usage,
            workspace_id,
            citations,
            redis=redis,
            api_key_id=api_key_id,
        )
    except asyncio.CancelledError:
        await accrue_tokens()
        if trace_id is not None and started is not None:
            await _update_trace(
                trace_id,
                status="cancelled",
                total_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        await _finalize(
            assistant_id,
            "".join(parts),
            "cancelled",
            usage,
            workspace_id,
            citations,
            redis=redis,
            api_key_id=api_key_id,
        )
        raise
    except ProviderError as exc:
        await accrue_tokens()
        if redis is not None:
            await record_failure(redis, provider.id)
        if trace_id is not None and started is not None:
            await _update_trace(
                trace_id,
                status="failed",
                error_code=exc.code,
                total_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        yield _sse("error", {"code": exc.code, "message": exc.message})
        await _finalize(
            assistant_id,
            "".join(parts),
            "failed",
            usage,
            workspace_id,
            citations,
            redis=redis,
            api_key_id=api_key_id,
        )
    except Exception:
        await accrue_tokens()
        if redis is not None:
            await record_failure(redis, provider.id)
        if trace_id is not None and started is not None:
            await _update_trace(
                trace_id,
                status="failed",
                error_code="internal_error",
                total_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        logger.exception("streaming failed for message %s", assistant_id)
        yield _sse("error", {"code": "internal_error", "message": "Streaming failed"})
        await _finalize(
            assistant_id,
            "".join(parts),
            "failed",
            usage,
            workspace_id,
            citations,
            redis=redis,
            api_key_id=api_key_id,
        )


async def _stream_agent_reply(
    *,
    provider: LLMProvider,
    conversation_id: UUID,
    assistant_id: UUID,
    history: list[ChatMessage],
    model: str,
    workspace_id: UUID,
    user_id: UUID,
    kb_id: UUID | None,
    kb_ids: Sequence[UUID] | None = None,
    context: AuthContext,
    redis: RedisLike,
    tool_registry: ToolRegistry,
    agent_registry: AgentRegistry,
    system_prompt: str | None = None,
    citations: Sequence[Citation] = (),
    trace_id: UUID | None = None,
    started: float | None = None,
    generation_opts: dict[str, object] | None = None,
    root_agent: str = SUPERVISOR_AGENT,
    agent_id: UUID | None = None,
    project_id: UUID | None = None,
    memory_access: MemoryAccess | None = None,
) -> AsyncIterator[str]:
    tool_citations: list[Citation] = []
    runner = AgentRunner(
        provider=provider,
        model=model,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        generation_opts=generation_opts or {},
        context=ToolContext(
            workspace_id=workspace_id,
            user_id=user_id,
            kb_id=kb_id,
            kb_ids=list(kb_ids) if kb_ids is not None else None,
            conversation_id=conversation_id,
            agent_id=agent_id,
            project_id=project_id,
            memory_access=memory_access,
            redis=redis,
            citations=tool_citations,
        ),
        quota_guard=lambda: enforce_quota(redis, context),
        system_prompt=system_prompt,
        root_agent=root_agent,
    )
    parts: list[str] = []
    ttft_ms: float | None = None
    usage: Usage | None = None

    async def finish() -> Usage | None:
        result = runner.usage
        if result.prompt_tokens is not None or result.completion_tokens is not None:
            await add_token_usage(
                redis,
                workspace_id,
                (result.prompt_tokens or 0) + (result.completion_tokens or 0),
            )
        return result

    try:
        yield _sse(
            "meta",
            {
                "message_id": str(assistant_id),
                "provider": provider.id,
                "model": model,
                "conversation_id": str(conversation_id),
                "agent": True,
            },
        )
        for citation in citations:
            yield _sse(
                "citation",
                {
                    "index": citation.index,
                    "document_id": str(citation.document_id),
                    "chunk_id": str(citation.chunk_id),
                    "page_no": citation.page_no,
                    "snippet": citation.snippet,
                },
            )
        async for event in runner.run(history):
            if event.kind == "delta":
                text = str(event.data.get("text", ""))
                if text:
                    parts.append(text)
                    if ttft_ms is None and trace_id is not None and started is not None:
                        ttft_ms = round((time.perf_counter() - started) * 1000, 1)
                        await _update_trace(trace_id, ttft_ms=ttft_ms)
                    yield _sse("delta", {"text": text})
                continue
            yield _sse(event.kind, event.data)
        for citation in tool_citations:
            yield _sse(
                "citation",
                {
                    "index": citation.index,
                    "document_id": str(citation.document_id),
                    "chunk_id": str(citation.chunk_id),
                    "page_no": citation.page_no,
                    "snippet": citation.snippet,
                },
            )
        usage = await finish()
        yield _sse(
            "usage",
            {
                "prompt_tokens": usage.prompt_tokens if usage else None,
                "completion_tokens": usage.completion_tokens if usage else None,
            },
        )
        yield _sse("done", {"finish_reason": "stop"})
        if trace_id is not None and started is not None:
            await _update_trace(
                trace_id,
                status="completed",
                total_ms=round((time.perf_counter() - started) * 1000, 1),
                agents=runner.tool_records or None,
            )
        await _finalize(
            assistant_id,
            "".join(parts),
            "completed",
            usage,
            workspace_id,
            tool_citations,
            api_key_id=context.api_key_id,
        )
    except asyncio.CancelledError:
        usage = await finish()
        if trace_id is not None and started is not None:
            await _update_trace(
                trace_id,
                status="cancelled",
                total_ms=round((time.perf_counter() - started) * 1000, 1),
                agents=runner.tool_records or None,
            )
        await _finalize(
            assistant_id,
            "".join(parts),
            "cancelled",
            usage,
            workspace_id,
            tool_citations,
            api_key_id=context.api_key_id,
        )
        raise
    except AgentFailure as exc:
        usage = await finish()
        if trace_id is not None and started is not None:
            await _update_trace(
                trace_id,
                status="failed",
                error_code=exc.code,
                total_ms=round((time.perf_counter() - started) * 1000, 1),
                agents=runner.tool_records or None,
            )
        yield _sse("error", {"code": exc.code, "message": exc.message})
        await _finalize(
            assistant_id,
            "".join(parts),
            "failed",
            usage,
            workspace_id,
            tool_citations,
            redis=redis,
            api_key_id=context.api_key_id,
        )
    except ProviderError as exc:
        usage = await finish()
        await record_failure(redis, provider.id)
        if trace_id is not None and started is not None:
            await _update_trace(
                trace_id,
                status="failed",
                error_code=exc.code,
                total_ms=round((time.perf_counter() - started) * 1000, 1),
                agents=runner.tool_records or None,
            )
        yield _sse("error", {"code": exc.code, "message": exc.message})
        await _finalize(
            assistant_id,
            "".join(parts),
            "failed",
            usage,
            workspace_id,
            tool_citations,
            redis=redis,
            api_key_id=context.api_key_id,
        )
    except Exception:
        usage = await finish()
        await record_failure(redis, provider.id)
        if trace_id is not None and started is not None:
            await _update_trace(
                trace_id,
                status="failed",
                error_code="internal_error",
                total_ms=round((time.perf_counter() - started) * 1000, 1),
                agents=runner.tool_records or None,
            )
        logger.exception("agent streaming failed for message %s", assistant_id)
        yield _sse("error", {"code": "internal_error", "message": "Agent run failed"})
        await _finalize(
            assistant_id,
            "".join(parts),
            "failed",
            usage,
            workspace_id,
            tool_citations,
            redis=redis,
            api_key_id=context.api_key_id,
        )


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    context: ChatContext,
    session: SessionDep,
    registry: Annotated[ProviderRegistry, Depends(get_scoped_registry)],
) -> Conversation:
    project = None
    if payload.project_id is not None:
        try:
            project = await get_project(session, context.workspace.id, payload.project_id)
        except ProjectError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found") from None
    custom_agent = None
    custom_agent_id = payload.custom_agent_id
    if custom_agent_id is None and project is not None:
        custom_agent_id = project.default_custom_agent_id
    if custom_agent_id is not None:
        try:
            custom_agent = await get_custom_agent(
                session,
                context.workspace.id,
                custom_agent_id,
                context.user.id,
            )
        except CustomAgentError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found") from None

    if payload.provider_id == "":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "invalid_model", "message": "provider_id is required"},
        )
    provider_id = payload.provider_id
    if provider_id is None and custom_agent is not None:
        provider_id = custom_agent.default_provider_id
    if provider_id is None and project is not None:
        provider_id = project.default_provider_id
    if provider_id is None:
        provider_id = "auto"

    if provider_id == "auto":
        model = "auto"
    elif payload.model is not None:
        if payload.model == "":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "invalid_model", "message": "model is required"},
            )
        model = payload.model
    elif (
        custom_agent is not None
        and custom_agent.default_provider_id == provider_id
        and custom_agent.default_model
    ):
        model = custom_agent.default_model
    elif (
        project is not None
        and project.default_provider_id == provider_id
        and project.default_model
    ):
        model = project.default_model
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "invalid_model", "message": "model is required"},
        )

    project_kb_ids = (
        [UUID(item) for item in project.kb_ids] if project is not None else []
    )
    explicit_kbs = "kb_id" in payload.model_fields_set or bool(payload.kb_ids)
    if "kb_id" in payload.model_fields_set:
        kb_id = payload.kb_id
    elif payload.kb_ids:
        kb_id = payload.kb_ids[0]
    elif custom_agent is not None and custom_agent.default_kb_id is not None:
        kb_id = custom_agent.default_kb_id
    elif project_kb_ids:
        kb_id = project_kb_ids[0]
    else:
        kb_id = project.default_kb_id if project is not None else None
    kb_ids = list(dict.fromkeys(payload.kb_ids))
    if not explicit_kbs and custom_agent is None and project is not None:
        inherited = project_kb_ids or (
            [project.default_kb_id] if project.default_kb_id is not None else []
        )
        kb_ids = list(dict.fromkeys([*kb_ids, *inherited]))
    if kb_id is not None and kb_id not in kb_ids:
        kb_ids.insert(0, kb_id)
    kb_ids = kb_ids[:10]
    kb_id = kb_ids[0] if kb_ids else None

    if custom_agent is not None:
        agent = True
    elif "agent" in payload.model_fields_set:
        agent = payload.agent
    else:
        agent = project.default_agent if project is not None else False

    if "plugin_ids" in payload.model_fields_set:
        plugin_ids = list(dict.fromkeys(payload.plugin_ids))
    elif custom_agent is not None:
        plugin_ids = [UUID(item) for item in custom_agent.plugin_ids]
    else:
        plugin_ids = []
    if plugin_ids:
        agent = True
    confirmed_ids = set(payload.confirmed_plugin_ids)

    if provider_id != "auto":
        try:
            registry.get(provider_id)
            await ensure_model_capability(
                session,
                workspace_id=context.workspace.id,
                user_id=context.user.id,
                provider_id=provider_id,
                model_id=model,
                capability="tools" if agent else "chat",
            )
        except ProviderError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
        except ProviderConfigError as exc:
            status_code = (
                status.HTTP_404_NOT_FOUND
                if exc.code in {"not_found", "model_not_found"}
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            )
            raise HTTPException(status_code, {"code": exc.code, "message": exc.message}) from None

    for item in kb_ids:
        await get_owned_knowledge_base(item, context.workspace.id, session)

    prompt_version_id = None
    system_prompt = None
    if payload.prompt_version_id is not None:
        version, system_prompt = await resolve_conversation_prompt(
            session,
            workspace_id=context.workspace.id,
            version_id=payload.prompt_version_id,
            variables=payload.prompt_variables,
        )
        prompt_version_id = version.id
    elif payload.prompt_variables:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "prompt_version_required",
                "message": "prompt_variables require a prompt_version_id",
            },
        )
    if project is not None and project.instructions and custom_agent is None:
        system_prompt = (
            f"{project.instructions}\n\n{system_prompt}"
            if system_prompt
            else project.instructions
        )

    conversation = Conversation(
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        project_id=project.id if project is not None else None,
        custom_agent_id=custom_agent.id if custom_agent is not None else None,
        title="",
        provider_id=provider_id,
        model=model,
        kb_id=kb_id,
        agent=agent,
        prompt_version_id=prompt_version_id,
        system_prompt=system_prompt,
        generation_settings=(
            normalize_generation_settings(custom_agent.generation_settings)
            if custom_agent is not None
            else {}
        ),
    )
    session.add(conversation)
    await session.flush()
    if custom_agent is not None:
        custom_agent.usage_count += 1
    if kb_ids:
        session.add_all(
            [
                ConversationKnowledgeBase(
                    conversation_id=conversation.id, kb_id=item
                )
                for item in kb_ids
            ]
        )
    if payload.attachment_ids:
        try:
            attachments = await claim_attachments(
                session,
                workspace_id=context.workspace.id,
                user_id=context.user.id,
                attachment_ids=payload.attachment_ids,
                conversation_id=conversation.id,
            )
        except AttachmentError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND
                if exc.code == "attachment_not_found"
                else status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": exc.code, "message": exc.message},
            ) from None
        await _validate_attachment_images(
            session,
            context,
            provider_id=provider_id,
            model=model,
            agent=agent,
            attachments=attachments,
        )
    if plugin_ids:
        try:
            await set_conversation_plugins(
                session,
                conversation,
                plugin_ids,
                confirmed_ids=confirmed_ids,
            )
        except PluginError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": exc.code, "message": exc.message},
            ) from None
    await session.commit()
    await session.refresh(conversation)
    return conversation


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    context: ReadContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: UUID | None = None,
    q: str | None = None,
    project_id: str | None = None,
    custom_agent_id: str | None = None,
    archived: Literal["false", "true", "all"] = "false",
    pinned: bool | None = None,
) -> list[Conversation]:
    conditions = [Conversation.workspace_id == context.workspace.id]
    if archived != "all":
        conditions.append(
            Conversation.archived_at.is_(None)
            if archived == "false"
            else Conversation.archived_at.is_not(None)
        )
    if before is not None:
        conditions.append(Conversation.id < before)
    if pinned is not None:
        conditions.append(Conversation.pinned.is_(pinned))
    if project_id is not None:
        if project_id == "none":
            conditions.append(Conversation.project_id.is_(None))
        else:
            try:
                conditions.append(Conversation.project_id == UUID(project_id))
            except ValueError:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    {"code": "invalid_project", "message": "Invalid project_id"},
                ) from None
    if custom_agent_id is not None:
        try:
            conditions.append(Conversation.custom_agent_id == UUID(custom_agent_id))
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "invalid_agent", "message": "Invalid custom_agent_id"},
            ) from None
    if q is not None and q.strip() != "":
        term = f"%{_escape_like(q.strip())}%"
        conditions.append(
            or_(
                Conversation.title.ilike(term, escape="\\"),
                exists(
                    select(Message.id).where(
                        Message.conversation_id == Conversation.id,
                        Message.content.ilike(term, escape="\\"),
                    )
                ),
            )
        )
    result = await session.execute(
        select(Conversation)
        .where(*conditions)
        .order_by(Conversation.pinned.desc(), Conversation.id.desc())
        .limit(limit)
    )
    return list(result.scalars())


async def _conversation_kb_ids(
    session: AsyncSession, conversation: Conversation
) -> list[UUID]:
    ids = list(
        (
            await session.execute(
                select(ConversationKnowledgeBase.kb_id).where(
                    ConversationKnowledgeBase.conversation_id == conversation.id
                )
            )
        ).scalars()
    )
    if not ids and conversation.kb_id is not None:
        ids = [conversation.kb_id]
    return ids


async def _conversation_detail(
    conversation: Conversation,
    session: AsyncSession,
    user_id: UUID | None = None,
) -> ConversationDetailOut:
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
    )
    messages = list(result.scalars())

    citations_by_message: dict[UUID, list[MessageCitation]] = defaultdict(list)
    feedback_by_message: dict[UUID, MessageFeedbackOut] = {}
    if messages:
        message_ids = [message.id for message in messages]
        citation_rows = (
            await session.execute(
                select(MessageCitation)
                .where(MessageCitation.message_id.in_(message_ids))
                .order_by(MessageCitation.message_id, MessageCitation.citation_index)
            )
        ).scalars()
        for citation in citation_rows:
            citations_by_message[citation.message_id].append(citation)
        if user_id is not None:
            feedback_rows = (
                await session.execute(
                    select(MessageFeedback).where(
                        MessageFeedback.message_id.in_(message_ids),
                        MessageFeedback.user_id == user_id,
                    )
                )
            ).scalars()
            for feedback in feedback_rows:
                feedback_by_message[feedback.message_id] = MessageFeedbackOut(
                    message_id=feedback.message_id,
                    rating=feedback.rating,
                    reason=feedback.reason,
                    updated_at=feedback.updated_at,
                )

    attachment_map = await attachments_by_message(
        session,
        workspace_id=conversation.workspace_id,
        conversation_id=conversation.id,
        message_ids=[message.id for message in messages],
    )
    kb_ids = list(
        (
            await session.execute(
                select(ConversationKnowledgeBase.kb_id).where(
                    ConversationKnowledgeBase.conversation_id == conversation.id
                )
            )
        ).scalars()
    )
    if not kb_ids and conversation.kb_id is not None:
        kb_ids = [conversation.kb_id]

    plugin_rows = await list_conversation_plugins(session, conversation.id)
    base = ConversationOut.model_validate(conversation).model_dump()
    base["kb_ids"] = kb_ids
    return ConversationDetailOut(
        **base,
        plugins=[
            ConversationPluginOut(
                plugin_id=definition.id,
                slug=definition.slug,
                name=definition.name,
                sensitive=definition.sensitive,
                confirmed_at=link.confirmed_at,
            )
            for link, definition in plugin_rows
        ],
        messages=[
            MessageOut.model_validate(message).model_copy(
                update={
                    "citations": [
                        CitationOut(
                            index=citation.citation_index,
                            document_id=citation.document_id,
                            chunk_id=citation.chunk_id,
                            page_no=citation.page_no,
                            snippet=citation.snippet,
                        )
                        for citation in citations_by_message.get(message.id, [])
                    ],
                    "feedback": feedback_by_message.get(message.id),
                    "attachments": [
                        AttachmentOut.model_validate(item)
                        for item in attachment_map.get(message.id, [])
                    ],
                }
            )
            for message in messages
        ],
    )


async def _delete_conversations(
    session: AsyncSession, conversation_ids: list[UUID]
) -> None:
    await delete_attachment_rows(session, conversation_ids)
    await session.execute(
        delete(ConversationKnowledgeBase).where(
            ConversationKnowledgeBase.conversation_id.in_(conversation_ids)
        )
    )
    message_ids = select(Message.id).where(Message.conversation_id.in_(conversation_ids))
    await session.execute(
        delete(MessageCitation).where(MessageCitation.message_id.in_(message_ids))
    )
    await session.execute(
        delete(MessageFeedback).where(MessageFeedback.message_id.in_(message_ids))
    )
    await session.execute(
        delete(Message).where(Message.conversation_id.in_(conversation_ids))
    )
    await session.execute(
        delete(ConversationPlugin).where(
            ConversationPlugin.conversation_id.in_(conversation_ids)
        )
    )
    await session.execute(
        delete(Conversation).where(Conversation.id.in_(conversation_ids))
    )


@router.get("/{conversation_id}", response_model=ConversationDetailOut)
async def get_conversation(
    conversation_id: UUID, context: ReadContext, session: SessionDep
) -> ConversationDetailOut:
    conversation = await _get_owned_conversation(conversation_id, context.workspace.id, session)
    return await _conversation_detail(conversation, session, context.user.id)


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update_conversation(
    conversation_id: UUID,
    payload: ConversationUpdate,
    context: JwtContext,
    session: SessionDep,
    registry: Annotated[ProviderRegistry, Depends(get_scoped_registry)],
) -> Conversation:
    conversation = await _get_workspace_conversation(
        conversation_id, context.workspace.id, session, include_archived=True
    )
    data = payload.model_dump(exclude_unset=True)

    if "archived" in data:
        archived = data.pop("archived")
        conversation.archived_at = datetime.now(UTC) if archived else None
    if "project_id" in data:
        project_id = data.pop("project_id")
        if project_id is not None:
            await _require_project(session, context.workspace.id, project_id)
        conversation.project_id = project_id
    if "generation_settings" in data:
        conversation.generation_settings = _normalize_generation_settings(
            data.pop("generation_settings")
        )
    if "memory_enabled" in data:
        conversation.memory_enabled = data.pop("memory_enabled")
    if "excluded_memory_ids" in data:
        excluded = data.pop("excluded_memory_ids") or []
        conversation.excluded_memory_ids = [str(item) for item in excluded][:50]
    if "title" in data:
        conversation.title = data.pop("title") or ""
    if "pinned" in data:
        conversation.pinned = bool(data.pop("pinned"))
    if "provider_id" in data or "model" in data:
        provider_id = data.pop("provider_id", conversation.provider_id)
        model = data.pop("model", conversation.model)
        if provider_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "invalid_model", "message": "provider_id is required"},
            )
        if provider_id == "auto":
            model = "auto"
        elif not model:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "invalid_model", "message": "model is required"},
            )
        await _validate_model_choice(
            session,
            registry,
            context,
            provider_id=provider_id,
            model=model,
            agent=conversation.agent,
        )
        conversation.provider_id = provider_id
        conversation.model = model

    await session.commit()
    await session.refresh(conversation)
    return conversation


@router.patch(
    "/{conversation_id}/messages/{message_id}", response_model=MessageEditOut
)
async def edit_message(
    conversation_id: UUID,
    message_id: UUID,
    payload: MessageUpdateIn,
    context: JwtContext,
    session: SessionDep,
) -> MessageEditOut:
    conversation = await _get_owned_conversation(
        conversation_id, context.workspace.id, session
    )
    target = await session.get(Message, message_id)
    if (
        target is None
        or target.conversation_id != conversation.id
        or target.role != "user"
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    if target.status != "completed":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "message_not_editable", "message": "Message cannot be edited"},
        )

    later_rows = (
        await session.execute(
            select(Message).where(
                Message.conversation_id == conversation.id,
                or_(
                    Message.created_at > target.created_at,
                    and_(
                        Message.created_at == target.created_at,
                        Message.id > target.id,
                    ),
                ),
            )
        )
    ).scalars()
    later = list(later_rows)
    if any(message.status == "streaming" for message in later):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "conversation_busy", "message": "A reply is still streaming"},
        )

    target.content = payload.content
    if later:
        later_ids = [message.id for message in later]
        later_attachments = list(
            (
                await session.execute(
                    select(ChatAttachment).where(
                        ChatAttachment.message_id.in_(later_ids)
                    )
                )
            ).scalars()
        )
        for row in later_attachments:
            Path(row.storage_path).unlink(missing_ok=True)
        if later_attachments:
            await session.execute(
                delete(ChatAttachment).where(
                    ChatAttachment.id.in_([row.id for row in later_attachments])
                )
            )
        await session.execute(
            delete(MessageCitation).where(MessageCitation.message_id.in_(later_ids))
        )
        await session.execute(
            delete(MessageFeedback).where(MessageFeedback.message_id.in_(later_ids))
        )
        await session.execute(delete(Message).where(Message.id.in_(later_ids)))
    conversation.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(target)
    return MessageEditOut(
        message=MessageOut.model_validate(target).model_copy(
            update={"citations": [], "feedback": None}
        ),
        removed=len(later),
    )


@router.post("/{conversation_id}/messages/{message_id}/reply")
async def reply_to_message(
    conversation_id: UUID,
    message_id: UUID,
    context: ChatContext,
    session: SessionDep,
    registry: Annotated[ProviderRegistry, Depends(get_scoped_registry)],
    redis: RedisDep,
    tool_registry: ToolRegistryDep,
    agent_registry: AgentRegistryDep,
) -> StreamingResponse:
    conversation = await _get_owned_conversation(
        conversation_id, context.workspace.id, session
    )
    target = await session.get(Message, message_id)
    if (
        target is None
        or target.conversation_id != conversation.id
        or target.role != "user"
        or target.status != "completed"
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    current_attachments = await attachments_for_message(
        session, workspace_id=context.workspace.id, message_id=target.id
    )
    return await _start_chat_turn(
        conversation=conversation,
        content=target.content,
        context=context,
        session=session,
        registry=registry,
        redis=redis,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        history_before=target.created_at,
        persist_user_message=False,
        current_attachments=current_attachments,
    )


@router.post("/batch", response_model=ConversationBatchOut)
async def batch_conversations(
    payload: ConversationBatchIn,
    context: JwtContext,
    session: SessionDep,
) -> ConversationBatchOut:
    conversation_ids = list(dict.fromkeys(payload.conversation_ids))
    result = await session.execute(
        select(Conversation).where(
            Conversation.id.in_(conversation_ids),
            Conversation.workspace_id == context.workspace.id,
        )
    )
    conversations = list(result.scalars())
    if len(conversations) != len(conversation_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    if payload.action == "delete":
        await _delete_conversations(session, conversation_ids)
        await session.commit()
        return ConversationBatchOut(updated=len(conversations))

    project_id = payload.project_id
    if payload.action == "move" and project_id is not None:
        await _require_project(session, context.workspace.id, project_id)

    now = datetime.now(UTC)
    for conversation in conversations:
        if payload.action == "archive":
            conversation.archived_at = conversation.archived_at or now
        elif payload.action == "unarchive":
            conversation.archived_at = None
        else:
            conversation.project_id = project_id
    await session.commit()
    return ConversationBatchOut(updated=len(conversations))


def _conversation_plugins_out(rows) -> list[ConversationPluginOut]:
    return [
        ConversationPluginOut(
            plugin_id=definition.id,
            slug=definition.slug,
            name=definition.name,
            sensitive=definition.sensitive,
            confirmed_at=link.confirmed_at,
        )
        for link, definition in rows
    ]


@router.get("/{conversation_id}/plugins", response_model=list[ConversationPluginOut])
async def get_conversation_plugins(
    conversation_id: UUID, context: JwtContext, session: SessionDep
) -> list[ConversationPluginOut]:
    conversation = await _get_workspace_conversation(
        conversation_id, context.workspace.id, session, include_archived=True
    )
    return _conversation_plugins_out(
        await list_conversation_plugins(session, conversation.id)
    )


@router.put("/{conversation_id}/plugins", response_model=list[ConversationPluginOut])
async def put_conversation_plugins(
    conversation_id: UUID,
    payload: ConversationPluginsIn,
    context: JwtContext,
    session: SessionDep,
) -> list[ConversationPluginOut]:
    conversation = await _get_workspace_conversation(
        conversation_id, context.workspace.id, session, include_archived=True
    )
    if payload.plugin_ids and not conversation.agent:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "agent_required", "message": "Plugins require agent mode"},
        )
    try:
        rows = await set_conversation_plugins(
            session, conversation, list(dict.fromkeys(payload.plugin_ids))
        )
    except PluginError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": exc.code, "message": exc.message},
        ) from None
    await session.commit()
    return _conversation_plugins_out(rows)


@router.post(
    "/{conversation_id}/plugins/{plugin_id}/confirm",
    response_model=list[ConversationPluginOut],
)
async def confirm_conversation_plugin_endpoint(
    conversation_id: UUID, plugin_id: UUID, context: JwtContext, session: SessionDep
) -> list[ConversationPluginOut]:
    conversation = await _get_workspace_conversation(
        conversation_id, context.workspace.id, session, include_archived=True
    )
    try:
        await confirm_conversation_plugin(session, conversation.id, plugin_id, True)
    except PluginError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    await session.commit()
    return _conversation_plugins_out(
        await list_conversation_plugins(session, conversation.id)
    )


@router.delete(
    "/{conversation_id}/plugins/{plugin_id}/confirm",
    response_model=list[ConversationPluginOut],
)
async def unconfirm_conversation_plugin_endpoint(
    conversation_id: UUID, plugin_id: UUID, context: JwtContext, session: SessionDep
) -> list[ConversationPluginOut]:
    conversation = await _get_workspace_conversation(
        conversation_id, context.workspace.id, session, include_archived=True
    )
    try:
        await confirm_conversation_plugin(session, conversation.id, plugin_id, False)
    except PluginError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    await session.commit()
    return _conversation_plugins_out(
        await list_conversation_plugins(session, conversation.id)
    )


@router.get("/{conversation_id}/plugin-calls", response_model=list[PluginCallOut])
async def get_conversation_plugin_calls(
    conversation_id: UUID, context: JwtContext, session: SessionDep
) -> list:
    conversation = await _get_workspace_conversation(
        conversation_id, context.workspace.id, session, include_archived=True
    )
    return await list_plugin_calls(session, context.workspace.id, conversation.id)


def _markdown_export(detail: ConversationDetailOut, filenames: dict[UUID, str]) -> str:
    lines = [f"# {detail.title or 'Conversation'}", ""]
    lines.append(f"- Provider: {detail.provider_id}")
    lines.append(f"- Model: {detail.model}")
    lines.append(f"- Created: {detail.created_at.isoformat()}")
    if detail.kb_id is not None:
        lines.append(f"- Knowledge base: {detail.kb_id}")
    lines.append("")
    for message in detail.messages:
        lines.append("## 用户" if message.role == "user" else "## 助手")
        lines.append("")
        lines.append(message.content or "")
        lines.append("")
        if message.citations:
            lines.append("### 引用")
            lines.append("")
            for citation in message.citations:
                source = filenames.get(citation.document_id, str(citation.document_id))
                page = f" · 第 {citation.page_no} 页" if citation.page_no is not None else ""
                lines.append(f"- [{citation.index}] {source}{page} — {citation.snippet}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


@router.get("/{conversation_id}/export")
async def export_conversation(
    conversation_id: UUID,
    context: ReadContext,
    session: SessionDep,
    export_format: Annotated[Literal["markdown", "json"], Query(alias="format")] = "markdown",
) -> Response:
    conversation = await _get_owned_conversation(conversation_id, context.workspace.id, session)
    detail = await _conversation_detail(conversation, session, context.user.id)
    document_ids = {
        citation.document_id for message in detail.messages for citation in message.citations
    }
    filenames: dict[UUID, str] = {}
    if document_ids:
        rows = (
            await session.execute(
                select(Document.id, Document.filename).where(Document.id.in_(document_ids))
            )
        ).all()
        filenames = {row.id: row.filename for row in rows}
    if export_format == "json":
        body = json.dumps(detail.model_dump(mode="json"), ensure_ascii=False, indent=2)
        media_type = "application/json; charset=utf-8"
        suffix = "json"
    else:
        body = _markdown_export(detail, filenames)
        media_type = "text/markdown; charset=utf-8"
        suffix = "md"
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="conversation-{conversation.id}.{suffix}"'
        },
    )


@router.delete("/{conversation_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation_permanently(
    conversation_id: UUID, context: JwtContext, session: SessionDep
) -> Response:
    conversation = await _get_workspace_conversation(
        conversation_id, context.workspace.id, session, include_archived=True
    )
    await _delete_conversations(session, [conversation.id])
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_conversation(
    conversation_id: UUID, context: JwtContext, session: SessionDep
) -> Response:
    conversation = await _get_owned_conversation(conversation_id, context.workspace.id, session)
    conversation.archived_at = datetime.now(UTC)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _open_auto_stream(
    registry: ProviderRegistry,
    candidates: Sequence[tuple[str, str]],
    history: Sequence[ChatMessage],
    redis: RedisLike,
    opts: dict[str, object] | None = None,
) -> tuple[LLMProvider, str, AsyncIterator[ChatChunk], ChatChunk, int]:
    attempts = 0
    for provider_id, model in candidates:
        try:
            provider = registry.get(provider_id)
        except ProviderError:
            continue
        attempts += 1
        stream = provider.stream_chat(list(history), model, **(opts or {}))
        try:
            first = await asyncio.wait_for(
                anext(stream), timeout=get_settings().provider_timeout_seconds
            )
        except Exception as exc:
            logger.warning("provider %s failed before first token: %s", provider_id, exc)
            await record_failure(redis, provider_id)
            continue
        await reset_failures(redis, provider_id)
        return provider, model, stream, first, attempts

    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        {"code": "no_provider_available", "message": "No provider is currently available"},
    )


async def _start_chat_turn(
    *,
    conversation: Conversation,
    content: str,
    context: AuthContext,
    session: AsyncSession,
    registry: ProviderRegistry,
    redis: RedisLike,
    tool_registry: ToolRegistry,
    agent_registry: AgentRegistry,
    reply_to_message_id: UUID | None = None,
    exclude_message_id: UUID | None = None,
    history_before: datetime | None = None,
    persist_user_message: bool = True,
    attachment_ids: Sequence[UUID] = (),
    current_attachments: Sequence[ChatAttachment] | None = None,
) -> StreamingResponse:
    await enforce_quota(redis, context)
    started = time.perf_counter()
    request_id = request_id_var.get()
    retrieval_ms: float | None = None
    opts = _generation_opts(conversation)
    provider: LLMProvider | None = None
    if conversation.provider_id != "auto":
        try:
            provider = registry.get(conversation.provider_id)
        except ProviderError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from None

    history_conditions = [
        Message.conversation_id == conversation.id,
        Message.status.in_(("completed", "cancelled")),
    ]
    if exclude_message_id is not None:
        history_conditions.append(Message.id != exclude_message_id)
    if history_before is not None:
        history_conditions.append(Message.created_at < history_before)
    history_result = await session.execute(
        select(Message).where(*history_conditions).order_by(Message.created_at)
    )
    prior_messages = list(history_result.scalars())

    history_attachments = await attachments_by_message(
        session,
        workspace_id=context.workspace.id,
        conversation_id=conversation.id,
        message_ids=[message.id for message in prior_messages],
    )
    chat_history = [
        ChatMessage(
            role=message.role,
            content=build_user_content(
                message.content,
                history_attachments.get(message.id, []),
                include_images=False,
            ),
        )
        for message in prior_messages
        if message.content
    ]

    current_rows = list(current_attachments or [])
    if persist_user_message:
        unlinked = await unlinked_conversation_attachments(
            session,
            workspace_id=context.workspace.id,
            conversation_id=conversation.id,
            user_id=context.user.id,
        )
        known_ids = {item.id for item in current_rows}
        current_rows.extend(item for item in unlinked if item.id not in known_ids)
    if attachment_ids:
        try:
            current_rows.extend(
                await claim_attachments(
                    session,
                    workspace_id=context.workspace.id,
                    user_id=context.user.id,
                    attachment_ids=attachment_ids,
                    conversation_id=conversation.id,
                )
            )
        except AttachmentError as exc:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND
                if exc.code == "attachment_not_found"
                else status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": exc.code, "message": exc.message},
            ) from None
    await _validate_attachment_images(
        session,
        context,
        provider_id=conversation.provider_id,
        model=conversation.model,
        agent=conversation.agent,
        attachments=current_rows,
    )

    chat_history.append(
        ChatMessage(
            role="user",
            content=build_user_content(
                content,
                current_rows,
                include_images=not conversation.agent,
            ),
        )
    )
    chat_history = chat_history[-HISTORY_MESSAGE_LIMIT:]

    citations: list[Citation] = []
    conversation_kbs = await _conversation_kb_ids(session, conversation)
    if conversation_kbs and not conversation.agent:
        retrieval_started = time.perf_counter()
        try:
            retrieved = await retrieve_chunks(
                session,
                workspace_id=context.workspace.id,
                kb_ids=conversation_kbs,
                query=content,
            )
        except ProviderError:
            logger.warning("retrieval failed for conversation %s", conversation.id)
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                {"code": "retrieval_failed", "message": "Retrieval failed"},
            ) from None
        retrieval_ms = round((time.perf_counter() - retrieval_started) * 1000, 1)
        used_chunks = fit_context(retrieved, get_settings().retrieval_max_context_chars)
        citations = build_citations(used_chunks)
        chat_history = build_rag_messages(
            used_chunks, chat_history, base_prompt=conversation.system_prompt
        )
    elif conversation.system_prompt and not conversation.agent:
        chat_history = [
            ChatMessage(role="system", content=conversation.system_prompt),
            *chat_history,
        ]

    stream: AsyncIterator[ChatChunk] | None = None
    first_chunk: ChatChunk | None = None
    routed_model = conversation.model
    attempts = 1

    if provider is None and conversation.agent:
        candidates = await route_candidates(session, registry, redis)
        for provider_id, candidate_model in candidates:
            try:
                provider = registry.get(provider_id)
            except ProviderError:
                continue
            routed_model = candidate_model
            break
        if provider is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                {
                    "code": "no_provider_available",
                    "message": "No provider is currently available",
                },
            )
    elif provider is None:
        candidates = await route_candidates(session, registry, redis)
        provider, routed_model, stream, first_chunk, attempts = await _open_auto_stream(
            registry, candidates, chat_history, redis, opts
        )

    custom_agent = None
    if conversation.custom_agent_id is not None:
        candidate = await session.get(CustomAgent, conversation.custom_agent_id)
        if candidate is not None and candidate.archived_at is None:
            custom_agent = candidate
    plugin_tools = await build_plugin_tools(session, conversation)
    effective_tools = (
        tool_registry.with_tools(plugin_tools) if plugin_tools else tool_registry
    )
    if custom_agent is not None:
        mcp_tools = await build_mcp_tool_specs(session, custom_agent.tools)
        if mcp_tools:
            effective_tools = effective_tools.with_tools(mcp_tools)
    effective_agents = agent_registry
    root_agent = SUPERVISOR_AGENT

    memory_settings = await get_memory_settings(
        session, context.workspace.id, context.user.id
    )
    conversation_project: Project | None = None
    if conversation.project_id is not None:
        candidate_project = await session.get(Project, conversation.project_id)
        if (
            candidate_project is not None
            and candidate_project.workspace_id == context.workspace.id
            and candidate_project.archived_at is None
        ):
            conversation_project = candidate_project
    memory_allowed = (
        conversation.memory_enabled
        if conversation.memory_enabled is not None
        else memory_settings.enabled
    )
    if not memory_settings.enabled:
        memory_allowed = False
    if (
        conversation_project is not None
        and project_memory_allowed(conversation_project) is False
    ):
        memory_allowed = False
    agent_access: MemoryAccess | None = None
    if custom_agent is not None:
        agent_access = agent_memory_access(custom_agent)
        if not custom_agent.memory_enabled:
            memory_allowed = False
    memory_block = ""
    memory_items = []
    if memory_allowed:
        excluded: list[UUID] = []
        for item in conversation.excluded_memory_ids or []:
            try:
                excluded.append(UUID(str(item)))
            except ValueError:
                continue
        if agent_access is None:
            read_scopes = {"global", "project"}
        else:
            read_scopes = set(agent_access.read_scopes)
            if conversation_project is None:
                read_scopes.discard("project")
        if (
            conversation_project is not None
            and not project_allows_global(conversation_project)
        ):
            read_scopes.discard("global")
        selection = await select_memories(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            agent_id=custom_agent.id if custom_agent is not None else conversation.custom_agent_id,
            project_id=conversation.project_id,
            query=content,
            limit=memory_settings.max_inject_items,
            max_chars=memory_settings.max_inject_chars,
            excluded_ids=excluded,
            provider_id=provider.id if provider is not None else None,
            model=routed_model,
            allow_cross_model=memory_settings.allow_cross_model,
            allowed_scopes=read_scopes,
            allowed_provider_ids=memory_settings.allowed_provider_ids,
            allowed_models=memory_settings.allowed_models,
            allowed_agent_ids=memory_settings.allowed_agent_ids,
        )
        memory_block = selection.block
        memory_items = selection.items

    if custom_agent is not None:
        extra_tools = list(plugin_tool_names(plugin_tools))
        if conversation_kbs and "kb_search" not in extra_tools:
            extra_tools.append("kb_search")
        spec = build_agent_spec(custom_agent, tuple(extra_tools))
        if memory_block:
            spec = AgentSpec(
                name=spec.name,
                system_prompt=f"{spec.system_prompt}\n\n{memory_block}",
                tools=spec.tools,
            )
        effective_agents = AgentRegistry([*agent_registry.all(), spec])
        root_agent = spec.name
    elif plugin_tools:
        supervisor = agent_registry.get(SUPERVISOR_AGENT)
        specs = [spec for spec in agent_registry.all() if spec.name != SUPERVISOR_AGENT]
        specs.insert(
            0,
            AgentSpec(
                name=supervisor.name,
                system_prompt=supervisor.system_prompt,
                tools=plugin_tool_names(plugin_tools),
            ),
        )
        effective_agents = AgentRegistry(specs)
    if memory_block and custom_agent is None:
        supervisor = effective_agents.get(SUPERVISOR_AGENT)
        specs = [
            spec for spec in effective_agents.all() if spec.name != SUPERVISOR_AGENT
        ]
        specs.insert(
            0,
            AgentSpec(
                name=supervisor.name,
                system_prompt=f"{supervisor.system_prompt}\n\n{memory_block}",
                tools=supervisor.tools,
            ),
        )
        effective_agents = AgentRegistry(specs)

    if memory_block and not conversation.agent:
        if chat_history and chat_history[0].role == "system":
            chat_history[0] = ChatMessage(
                role="system",
                content=f"{chat_history[0].content}\n\n{memory_block}",
            )
        else:
            chat_history.insert(0, ChatMessage(role="system", content=memory_block))

    if persist_user_message and not conversation.title:
        conversation.title = content[:TITLE_MAX_LENGTH]

    messages_to_add: list[object] = []
    user_message: Message | None = None
    if persist_user_message:
        user_message = Message(
            conversation_id=conversation.id,
            user_id=context.user.id,
            role="user",
            content=content,
            status="completed",
            provider_id=provider.id,
            model=routed_model,
            request_id=request_id,
        )
        messages_to_add.append(user_message)
    assistant_message = Message(
        conversation_id=conversation.id,
        user_id=context.user.id,
        role="assistant",
        content="",
        status="streaming",
        provider_id=provider.id,
        model=routed_model,
        request_id=request_id,
        memory_refs=(
            [
                {
                    "id": str(item.memory.id),
                    "title": item.memory.title,
                    "category": item.memory.category,
                    "scope_type": item.memory.scope_type,
                    "relevance": round(item.score, 4),
                    "injected_chars": item.injected_chars,
                }
                for item in memory_items
            ]
            if memory_items
            else []
        ),
        reply_to_message_id=reply_to_message_id,
    )
    trace = Trace(
        request_id=request_id,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        conversation_id=conversation.id,
        provider_id=provider.id,
        model=routed_model,
        retrieval_ms=retrieval_ms,
        attempts=attempts,
        status="streaming",
    )
    messages_to_add.extend([assistant_message, trace])
    session.add_all(messages_to_add)
    await session.flush()
    if user_message is not None:
        for row in current_rows:
            if row.message_id is None:
                row.message_id = user_message.id
    trace.message_id = assistant_message.id
    if memory_items:
        await record_memory_usage(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            memories=[
                (item.memory, item.score, item.injected_chars)
                for item in memory_items
            ],
            context_type="agent" if conversation.agent else "chat",
            context_id=str(assistant_message.id),
            provider_id=provider.id,
            model=routed_model,
        )
    await session.commit()
    await session.refresh(assistant_message)

    # Streaming responses outlive the endpoint; release the request connection now so
    # long-running streams cannot exhaust the pool under concurrency.
    await session.close()

    if conversation.agent:
        response_stream = _stream_agent_reply(
            provider=provider,
            conversation_id=conversation.id,
            assistant_id=assistant_message.id,
            history=chat_history,
            model=routed_model,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            kb_id=conversation.kb_id,
            kb_ids=conversation_kbs,
            context=context,
            redis=redis,
            tool_registry=effective_tools,
            agent_registry=effective_agents,
            root_agent=root_agent,
            system_prompt=conversation.system_prompt,
            citations=citations,
            trace_id=trace.id,
            started=started,
            generation_opts=opts,
            agent_id=custom_agent.id if custom_agent is not None else None,
            project_id=conversation.project_id,
            memory_access=agent_access,
        )
    else:
        response_stream = _stream_reply(
            provider=provider,
            conversation_id=conversation.id,
            assistant_id=assistant_message.id,
            history=chat_history,
            model=routed_model,
            workspace_id=context.workspace.id,
            citations=citations,
            stream=stream,
            first_chunk=first_chunk,
            opts=opts,
            redis=redis,
            trace_id=trace.id,
            started=started,
            api_key_id=context.api_key_id,
        )

    return StreamingResponse(
        track_sse_stream(response_stream),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/{conversation_id}/messages",
    responses={
        401: {"model": ErrorOut, "description": "Missing or invalid credentials"},
        404: {"model": ErrorOut, "description": "Conversation not found"},
        429: {
            "model": ErrorOut,
            "description": "Quota exceeded; includes Retry-After and X-Quota-* headers",
        },
        503: {"model": ErrorOut, "description": "No provider available"},
    },
)
async def send_message(
    conversation_id: UUID,
    payload: SendMessageIn,
    context: ChatContext,
    session: SessionDep,
    registry: Annotated[ProviderRegistry, Depends(get_scoped_registry)],
    redis: RedisDep,
    tool_registry: ToolRegistryDep,
    agent_registry: AgentRegistryDep,
) -> StreamingResponse:
    conversation = await _get_owned_conversation(conversation_id, context.workspace.id, session)
    return await _start_chat_turn(
        conversation=conversation,
        content=payload.content,
        context=context,
        session=session,
        registry=registry,
        redis=redis,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        attachment_ids=payload.attachment_ids,
    )


@router.post(
    "/{conversation_id}/messages/{message_id}/regenerate",
    responses={
        401: {"model": ErrorOut, "description": "Missing or invalid credentials"},
        404: {"model": ErrorOut, "description": "Conversation or message not found"},
        409: {"model": ErrorOut, "description": "Message cannot be regenerated"},
        429: {
            "model": ErrorOut,
            "description": "Quota exceeded; includes Retry-After and X-Quota-* headers",
        },
        503: {"model": ErrorOut, "description": "No provider available"},
    },
)
async def regenerate_message(
    conversation_id: UUID,
    message_id: UUID,
    context: ChatContext,
    session: SessionDep,
    registry: Annotated[ProviderRegistry, Depends(get_scoped_registry)],
    redis: RedisDep,
    tool_registry: ToolRegistryDep,
    agent_registry: AgentRegistryDep,
) -> StreamingResponse:
    conversation = await _get_owned_conversation(conversation_id, context.workspace.id, session)
    target = await session.get(Message, message_id)
    if (
        target is None
        or target.conversation_id != conversation.id
        or target.role != "assistant"
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    if target.status not in ("completed", "cancelled"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Message cannot be regenerated")
    user_message = (
        await session.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.role == "user",
                Message.created_at <= target.created_at,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if user_message is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "No user message to regenerate")
    current_attachments = await attachments_for_message(
        session, workspace_id=context.workspace.id, message_id=user_message.id
    )
    return await _start_chat_turn(
        conversation=conversation,
        content=user_message.content,
        context=context,
        session=session,
        registry=registry,
        redis=redis,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        reply_to_message_id=target.id,
        exclude_message_id=target.id,
        history_before=user_message.created_at,
        persist_user_message=False,
        current_attachments=current_attachments,
    )


async def _feedback_message(
    message_id: UUID, context: AuthContext, session: AsyncSession
) -> Message:
    message = await session.get(Message, message_id)
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    conversation = await session.get(Conversation, message.conversation_id)
    if conversation is None or conversation.workspace_id != context.workspace.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    if message.role != "assistant" or message.status not in ("completed", "cancelled"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "invalid_message", "message": "Feedback is only for assistant messages"},
        )
    return message


@messages_router.put("/{message_id}/feedback", response_model=MessageFeedbackOut)
async def put_message_feedback(
    message_id: UUID,
    payload: MessageFeedbackIn,
    context: JwtContext,
    session: SessionDep,
) -> MessageFeedbackOut:
    message = await _feedback_message(message_id, context, session)
    feedback = (
        await session.execute(
            select(MessageFeedback).where(
                MessageFeedback.message_id == message.id,
                MessageFeedback.user_id == context.user.id,
            )
        )
    ).scalar_one_or_none()
    if feedback is None:
        feedback = MessageFeedback(
            message_id=message.id,
            user_id=context.user.id,
            rating=payload.rating,
            reason=payload.reason,
        )
        session.add(feedback)
    else:
        feedback.rating = payload.rating
        feedback.reason = payload.reason
    await session.commit()
    await session.refresh(feedback)
    return MessageFeedbackOut(
        message_id=feedback.message_id,
        rating=feedback.rating,
        reason=feedback.reason,
        updated_at=feedback.updated_at,
    )


@messages_router.delete("/{message_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message_feedback(
    message_id: UUID, context: JwtContext, session: SessionDep
) -> Response:
    await _feedback_message(message_id, context, session)
    await session.execute(
        delete(MessageFeedback).where(
            MessageFeedback.message_id == message_id,
            MessageFeedback.user_id == context.user.id,
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
