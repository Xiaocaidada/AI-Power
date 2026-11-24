from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.schemas import (
    ConversationDetailOut,
    ConversationShareCreate,
    ConversationShareCreatedOut,
    ConversationShareOut,
)
from app.services.reuse import (
    ReuseError,
    create_share,
    list_shares,
    resolve_share,
    revoke_share,
)

router = APIRouter(tags=["shares"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


async def _owned_conversation(session: AsyncSession, conversation_id: UUID, context: AuthContext):
    from sqlalchemy import select

    from app.models import Conversation

    conversation = (
        await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == context.workspace.id,
                Conversation.user_id == context.user.id,
                Conversation.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


def _share_out(share) -> ConversationShareOut:
    return ConversationShareOut(
        id=share.id,
        conversation_id=share.conversation_id,
        expires_at=share.expires_at,
        revoked_at=share.revoked_at,
        created_at=share.created_at,
        active=share.revoked_at is None,
    )


@router.post(
    "/conversations/{conversation_id}/shares",
    response_model=ConversationShareCreatedOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation_share(
    conversation_id: UUID,
    payload: ConversationShareCreate,
    context: JwtContext,
    session: SessionDep,
) -> ConversationShareCreatedOut:
    conversation = await _owned_conversation(session, conversation_id, context)
    share, token = await create_share(
        session,
        conversation=conversation,
        user_id=context.user.id,
        expires_in_days=payload.expires_in_days,
    )
    await session.commit()
    await session.refresh(share)
    return ConversationShareCreatedOut(
        **_share_out(share).model_dump(),
        token=token,
    )


@router.get(
    "/conversations/{conversation_id}/shares",
    response_model=list[ConversationShareOut],
)
async def list_conversation_shares(
    conversation_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> list[ConversationShareOut]:
    await _owned_conversation(session, conversation_id, context)
    return [_share_out(share) for share in await list_shares(session, conversation_id)]


@router.delete(
    "/conversations/{conversation_id}/shares/{share_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_conversation_share(
    conversation_id: UUID,
    share_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> Response:
    await _owned_conversation(session, conversation_id, context)
    from app.models import ConversationShare

    share = await session.get(ConversationShare, share_id)
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Share link not found")
    try:
        await revoke_share(
            session,
            share,
            conversation_id=conversation_id,
            user_id=context.user.id,
            role=context.role,
        )
    except ReuseError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message}
        ) from None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/shares/{token}", response_model=ConversationDetailOut)
async def read_shared_conversation(
    token: str,
    context: JwtContext,
    session: SessionDep,
) -> ConversationDetailOut:
    from app.routers.conversations import _conversation_detail

    try:
        conversation = await resolve_share(session, token, context.user.id)
    except ReuseError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message}
        ) from None
    detail = await _conversation_detail(conversation, session, context.user.id)
    detail.messages = [
        message.model_copy(update={"feedback": None, "memory_refs": []})
        for message in detail.messages
    ]
    return detail
