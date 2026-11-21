import asyncio
import json
import logging
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
from app.deps import get_current_user, get_registry
from app.models import Conversation, Message, User
from app.providers.base import ChatMessage, LLMProvider, ProviderError, Usage
from app.providers.registry import ProviderRegistry
from app.schemas import (
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
CurrentUser = Annotated[User, Depends(get_current_user)]

HISTORY_MESSAGE_LIMIT = 12
TITLE_MAX_LENGTH = 30


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _get_owned_conversation(
    conversation_id: UUID, user_id: UUID, session: AsyncSession
) -> Conversation:
    result = await session.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
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
        await _finalize(assistant_id, "".join(parts), "completed", usage)
    except asyncio.CancelledError:
        await _finalize(assistant_id, "".join(parts), "cancelled", usage)
        raise
    except ProviderError as exc:
        yield _sse("error", {"code": exc.code, "message": exc.message})
        await _finalize(assistant_id, "".join(parts), "failed", usage)
    except Exception:
        logger.exception("streaming failed for message %s", assistant_id)
        yield _sse("error", {"code": "internal_error", "message": "Streaming failed"})
        await _finalize(assistant_id, "".join(parts), "failed", usage)


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    current_user: CurrentUser,
    session: SessionDep,
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
) -> Conversation:
    try:
        registry.get(payload.provider_id)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None

    if payload.kb_id is not None:
        await get_owned_knowledge_base(payload.kb_id, current_user.id, session)

    conversation = Conversation(
        user_id=current_user.id,
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
async def list_conversations(current_user: CurrentUser, session: SessionDep) -> list[Conversation]:
    result = await session.execute(
        select(Conversation)
        .where(
            Conversation.user_id == current_user.id,
            Conversation.archived_at.is_(None),
        )
        .order_by(Conversation.created_at.desc())
    )
    return list(result.scalars())


@router.get("/{conversation_id}", response_model=ConversationDetailOut)
async def get_conversation(
    conversation_id: UUID, current_user: CurrentUser, session: SessionDep
) -> ConversationDetailOut:
    conversation = await _get_owned_conversation(conversation_id, current_user.id, session)
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
    )
    messages = list(result.scalars())
    return ConversationDetailOut(
        **ConversationOut.model_validate(conversation).model_dump(),
        messages=[MessageOut.model_validate(message) for message in messages],
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_conversation(
    conversation_id: UUID, current_user: CurrentUser, session: SessionDep
) -> Response:
    conversation = await _get_owned_conversation(conversation_id, current_user.id, session)
    conversation.archived_at = datetime.now(UTC)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: UUID,
    payload: SendMessageIn,
    current_user: CurrentUser,
    session: SessionDep,
    registry: Annotated[ProviderRegistry, Depends(get_registry)],
) -> StreamingResponse:
    conversation = await _get_owned_conversation(conversation_id, current_user.id, session)
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
                user_id=current_user.id,
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
        user_id=current_user.id,
        role="user",
        content=payload.content,
        status="completed",
        provider_id=conversation.provider_id,
        model=conversation.model,
    )
    assistant_message = Message(
        conversation_id=conversation.id,
        user_id=current_user.id,
        role="assistant",
        content="",
        status="streaming",
        provider_id=conversation.provider_id,
        model=conversation.model,
    )
    session.add_all([user_message, assistant_message])
    await session.commit()
    await session.refresh(assistant_message)

    return StreamingResponse(
        _stream_reply(
            provider=provider,
            conversation_id=conversation.id,
            assistant_id=assistant_message.id,
            history=chat_history,
            model=conversation.model,
            citations=citations,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
