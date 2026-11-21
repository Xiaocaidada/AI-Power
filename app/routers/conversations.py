import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal, get_session
from app.deps import AuthContext, get_jwt_context, get_registry, require_scope
from app.models import Conversation, Message, MessageCitation, UsageEvent
from app.providers.base import ChatMessage, LLMProvider, ProviderError, Usage
from app.providers.registry import ProviderRegistry
from app.schemas import (
    CitationOut,
    ConversationCreate,
    ConversationDetailOut,
    ConversationOut,
    MessageOut,
    SendMessageIn,
)
from app.services.access import get_owned_knowledge_base
from app.services.rag import build_rag_messages, fit_context
from app.services.retrieval import Citation, build_citations, retrieve_chunks

router = APIRouter(prefix="/conversations", tags=["conversations"])
logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
ChatContext = Annotated[AuthContext, Depends(require_scope("chat:write"))]
ReadContext = Annotated[AuthContext, Depends(require_scope("kb:read"))]

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


async def _finalize(
    message_id: UUID,
    content: str,
    message_status: str,
    usage: Usage | None,
    workspace_id: UUID,
    citations: Sequence[Citation] = (),
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

            if message.role == "assistant":
                existing_event = await session.execute(
                    select(UsageEvent.id).where(UsageEvent.message_id == message_id)
                )
                if existing_event.scalar_one_or_none() is None:
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
                        )
                    )
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
) -> AsyncIterator[str]:
    parts: list[str] = []
    usage: Usage | None = None
    finish_reason: str | None = None
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
        async for chunk in provider.stream_chat(history, model):
            if chunk.delta:
                parts.append(chunk.delta)
                yield _sse("delta", {"text": chunk.delta})
            if chunk.usage is not None:
                usage = chunk.usage
            if chunk.finish_reason is not None:
                finish_reason = chunk.finish_reason

        yield _sse(
            "usage",
            {
                "prompt_tokens": usage.prompt_tokens if usage else None,
                "completion_tokens": usage.completion_tokens if usage else None,
            },
        )
        yield _sse("done", {"finish_reason": finish_reason})
        await _finalize(assistant_id, "".join(parts), "completed", usage, workspace_id, citations)
    except asyncio.CancelledError:
        await _finalize(assistant_id, "".join(parts), "cancelled", usage, workspace_id, citations)
        raise
    except ProviderError as exc:
        yield _sse("error", {"code": exc.code, "message": exc.message})
        await _finalize(assistant_id, "".join(parts), "failed", usage, workspace_id, citations)
    except Exception:
        logger.exception("streaming failed for message %s", assistant_id)
        yield _sse("error", {"code": "internal_error", "message": "Streaming failed"})
        await _finalize(assistant_id, "".join(parts), "failed", usage, workspace_id, citations)


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    context: ChatContext,
    session: SessionDep,
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
) -> Conversation:
    try:
        registry.get(payload.provider_id)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None

    if payload.kb_id is not None:
        await get_owned_knowledge_base(payload.kb_id, context.workspace.id, session)

    conversation = Conversation(
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        title="",
        provider_id=payload.provider_id,
        model=payload.model,
        kb_id=payload.kb_id,
    )
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return conversation


@router.get("", response_model=list[ConversationOut])
async def list_conversations(context: ReadContext, session: SessionDep) -> list[Conversation]:
    result = await session.execute(
        select(Conversation)
        .where(
            Conversation.workspace_id == context.workspace.id,
            Conversation.archived_at.is_(None),
        )
        .order_by(Conversation.created_at.desc())
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


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: UUID,
    payload: SendMessageIn,
    context: ChatContext,
    session: SessionDep,
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
) -> StreamingResponse:
    conversation = await _get_owned_conversation(conversation_id, context.workspace.id, session)
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
    if conversation.kb_id is not None:
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
        used_chunks = fit_context(retrieved, get_settings().retrieval_max_context_chars)
        citations = build_citations(used_chunks)
        chat_history = build_rag_messages(used_chunks, chat_history)

    if not conversation.title:
        conversation.title = payload.content[:TITLE_MAX_LENGTH]

    user_message = Message(
        conversation_id=conversation.id,
        user_id=context.user.id,
        role="user",
        content=payload.content,
        status="completed",
        provider_id=conversation.provider_id,
        model=conversation.model,
    )
    assistant_message = Message(
        conversation_id=conversation.id,
        user_id=context.user.id,
        role="assistant",
        content="",
        status="streaming",
        provider_id=conversation.provider_id,
        model=conversation.model,
    )
    session.add_all([user_message, assistant_message])
    await session.commit()
    await session.refresh(assistant_message)

    # Streaming responses outlive the endpoint; release the request connection now so
    # long-running streams cannot exhaust the pool under concurrency.
    await session.close()

    return StreamingResponse(
        _stream_reply(
            provider=provider,
            conversation_id=conversation.id,
            assistant_id=assistant_message.id,
            history=chat_history,
            model=conversation.model,
            workspace_id=context.workspace.id,
            citations=citations,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
