import asyncio
import json
import logging
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import AgentRegistry
from app.clients import RedisLike, get_redis
from app.config import get_settings
from app.db import SessionLocal, get_session
from app.deps import (
    AuthContext,
    get_agent_registry,
    get_jwt_context,
    get_registry,
    get_tool_registry,
    require_scope,
)
from app.metrics import record_usage_metrics, track_sse_stream
from app.models import Conversation, Message, MessageCitation, Trace, UsageEvent
from app.observability import request_id_var
from app.providers.base import ChatChunk, ChatMessage, LLMProvider, ProviderError, Usage
from app.providers.registry import ProviderRegistry
from app.schemas import (
    CitationOut,
    ConversationCreate,
    ConversationDetailOut,
    ConversationOut,
    ErrorOut,
    MessageOut,
    SendMessageIn,
)
from app.services.access import get_owned_knowledge_base
from app.services.agent import AgentFailure, AgentRunner
from app.services.budget import check_workspace_budget
from app.services.costs import compute_cost, price_snapshot
from app.services.prompts import resolve_conversation_prompt
from app.services.quotas import add_token_usage, enforce_quota
from app.services.rag import build_rag_messages, fit_context
from app.services.retrieval import Citation, build_citations, retrieve_chunks
from app.services.routing import record_failure, reset_failures, route_candidates
from app.services.webhooks import enqueue_event
from app.tools.base import ToolContext, ToolRegistry

router = APIRouter(prefix="/conversations", tags=["conversations"])
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


async def _get_owned_conversation(
    conversation_id: UUID, workspace_id: UUID, session: AsyncSession
) -> Conversation:
    result = await session.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.workspace_id == workspace_id,
            Conversation.archived_at.is_(None),
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


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
                existing_event = await session.execute(
                    select(UsageEvent.id).where(UsageEvent.message_id == message_id)
                )
                if existing_event.scalar_one_or_none() is None:
                    input_price, output_price = await price_snapshot(
                        session, message.provider_id, message.model
                    )
                    cost = compute_cost(
                        message.prompt_tokens,
                        message.completion_tokens,
                        input_price,
                        output_price,
                    )
                    cost_value = cost
                    session.add(
                        UsageEvent(
                            workspace_id=workspace_id,
                            user_id=message.user_id,
                            conversation_id=message.conversation_id,
                            message_id=message.id,
                            provider_id=message.provider_id,
                            model=message.model,
                            prompt_tokens=message.prompt_tokens,
                            completion_tokens=message.completion_tokens,
                            input_price=input_price,
                            output_price=output_price,
                            cost=cost,
                            unpriced=input_price is None or output_price is None,
                        )
                    )
                    record_usage_metrics(
                        prompt_tokens=message.prompt_tokens,
                        completion_tokens=message.completion_tokens,
                        cost=cost,
                        provider_id=message.provider_id,
                        model=message.model,
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
    redis: RedisLike | None = None,
    trace_id: UUID | None = None,
    started: float | None = None,
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
        chunk_stream = stream if stream is not None else provider.stream_chat(history, model)

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
            assistant_id, "".join(parts), "completed", usage, workspace_id, citations, redis=redis
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
            assistant_id, "".join(parts), "cancelled", usage, workspace_id, citations, redis=redis
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
            assistant_id, "".join(parts), "failed", usage, workspace_id, citations, redis=redis
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
            assistant_id, "".join(parts), "failed", usage, workspace_id, citations, redis=redis
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
    context: AuthContext,
    redis: RedisLike,
    tool_registry: ToolRegistry,
    agent_registry: AgentRegistry,
    system_prompt: str | None = None,
    citations: Sequence[Citation] = (),
    trace_id: UUID | None = None,
    started: float | None = None,
) -> AsyncIterator[str]:
    tool_citations: list[Citation] = []
    runner = AgentRunner(
        provider=provider,
        model=model,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        context=ToolContext(
            workspace_id=workspace_id,
            user_id=user_id,
            kb_id=kb_id,
            redis=redis,
            citations=tool_citations,
        ),
        quota_guard=lambda: enforce_quota(redis, context),
        system_prompt=system_prompt,
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
            assistant_id, "".join(parts), "completed", usage, workspace_id, tool_citations
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
            assistant_id, "".join(parts), "cancelled", usage, workspace_id, tool_citations
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
            assistant_id, "".join(parts), "failed", usage, workspace_id, tool_citations, redis=redis
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
            assistant_id, "".join(parts), "failed", usage, workspace_id, tool_citations, redis=redis
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
            assistant_id, "".join(parts), "failed", usage, workspace_id, tool_citations, redis=redis
        )


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    context: ChatContext,
    session: SessionDep,
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
) -> Conversation:
    if payload.provider_id != "auto":
        try:
            registry.get(payload.provider_id)
        except ProviderError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None

    if payload.kb_id is not None:
        await get_owned_knowledge_base(payload.kb_id, context.workspace.id, session)

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

    conversation = Conversation(
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        title="",
        provider_id=payload.provider_id,
        model="auto" if payload.provider_id == "auto" else payload.model,
        kb_id=payload.kb_id,
        agent=payload.agent,
        prompt_version_id=prompt_version_id,
        system_prompt=system_prompt,
    )
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    context: ReadContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: UUID | None = None,
) -> list[Conversation]:
    conditions = [
        Conversation.workspace_id == context.workspace.id,
        Conversation.archived_at.is_(None),
    ]
    if before is not None:
        conditions.append(Conversation.id < before)
    result = await session.execute(
        select(Conversation).where(*conditions).order_by(Conversation.id.desc()).limit(limit)
    )
    return list(result.scalars())


@router.get("/{conversation_id}", response_model=ConversationDetailOut)
async def get_conversation(
    conversation_id: UUID, context: ReadContext, session: SessionDep
) -> ConversationDetailOut:
    conversation = await _get_owned_conversation(conversation_id, context.workspace.id, session)
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
    )
    messages = list(result.scalars())

    citations_by_message: dict[UUID, list[MessageCitation]] = defaultdict(list)
    if messages:
        citation_rows = (
            await session.execute(
                select(MessageCitation)
                .where(MessageCitation.message_id.in_([message.id for message in messages]))
                .order_by(MessageCitation.message_id, MessageCitation.citation_index)
            )
        ).scalars()
        for citation in citation_rows:
            citations_by_message[citation.message_id].append(citation)

    return ConversationDetailOut(
        **ConversationOut.model_validate(conversation).model_dump(),
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
                    ]
                }
            )
            for message in messages
        ],
    )


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
) -> tuple[LLMProvider, str, AsyncIterator[ChatChunk], ChatChunk, int]:
    attempts = 0
    for provider_id, model in candidates:
        try:
            provider = registry.get(provider_id)
        except ProviderError:
            continue
        attempts += 1
        stream = provider.stream_chat(list(history), model)
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
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
    redis: RedisDep,
    tool_registry: ToolRegistryDep,
    agent_registry: AgentRegistryDep,
) -> StreamingResponse:
    conversation = await _get_owned_conversation(conversation_id, context.workspace.id, session)
    await enforce_quota(redis, context)
    started = time.perf_counter()
    request_id = request_id_var.get()
    retrieval_ms: float | None = None
    provider: LLMProvider | None = None
    if conversation.provider_id != "auto":
        try:
            provider = registry.get(conversation.provider_id)
        except ProviderError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from None

    history_result = await session.execute(
        select(Message)
        .where(
            Message.conversation_id == conversation.id,
            Message.status.in_(("completed", "cancelled")),
        )
        .order_by(Message.created_at)
    )
    prior_messages = list(history_result.scalars())

    chat_history = [
        ChatMessage(role=message.role, content=message.content)
        for message in prior_messages
        if message.content
    ]
    chat_history.append(ChatMessage(role="user", content=payload.content))
    chat_history = chat_history[-HISTORY_MESSAGE_LIMIT:]

    citations: list[Citation] = []
    if conversation.kb_id is not None and not conversation.agent:
        retrieval_started = time.perf_counter()
        try:
            retrieved = await retrieve_chunks(
                session,
                workspace_id=context.workspace.id,
                kb_id=conversation.kb_id,
                query=payload.content,
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
            registry, candidates, chat_history, redis
        )

    if not conversation.title:
        conversation.title = payload.content[:TITLE_MAX_LENGTH]

    user_message = Message(
        conversation_id=conversation.id,
        user_id=context.user.id,
        role="user",
        content=payload.content,
        status="completed",
        provider_id=provider.id,
        model=routed_model,
        request_id=request_id,
    )
    assistant_message = Message(
        conversation_id=conversation.id,
        user_id=context.user.id,
        role="assistant",
        content="",
        status="streaming",
        provider_id=provider.id,
        model=routed_model,
        request_id=request_id,
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
    session.add_all([user_message, assistant_message, trace])
    await session.flush()
    trace.message_id = assistant_message.id
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
            context=context,
            redis=redis,
            tool_registry=tool_registry,
            agent_registry=agent_registry,
            system_prompt=conversation.system_prompt,
            citations=citations,
            trace_id=trace.id,
            started=started,
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
            redis=redis,
            trace_id=trace.id,
            started=started,
        )

    return StreamingResponse(
        track_sse_stream(response_stream),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
