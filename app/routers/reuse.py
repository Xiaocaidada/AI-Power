from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.schemas import (
    CodeBlockOut,
    SaveAnswerIn,
    SavedDocumentOut,
    TaskCandidateOut,
)
from app.services.queue import JobQueue, get_queue
from app.services.reuse import (
    ReuseError,
    extract_code_blocks,
    extract_task_candidates,
    get_owned_message,
    save_answer_to_knowledge,
)

router = APIRouter(tags=["reuse"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
QueueDep = Annotated[JobQueue, Depends(get_queue)]


def _error(exc: ReuseError) -> HTTPException:
    if exc.code == "queue_unavailable":
        return HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": exc.code, "message": exc.message},
        )
    if exc.code in {
        "conversation_not_found",
        "message_not_found",
        "knowledge_base_not_found",
        "project_not_found",
    }:
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"code": exc.code, "message": exc.message},
    )


@router.get(
    "/conversations/{conversation_id}/messages/{message_id}/code-blocks",
    response_model=list[CodeBlockOut],
)
async def list_message_code_blocks(
    conversation_id: UUID,
    message_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> list[CodeBlockOut]:
    try:
        _, message = await get_owned_message(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
    except ReuseError as exc:
        raise _error(exc) from None
    return [CodeBlockOut(**item) for item in extract_code_blocks(message.content)]


@router.get(
    "/conversations/{conversation_id}/messages/{message_id}/task-candidates",
    response_model=list[TaskCandidateOut],
)
async def list_message_task_candidates(
    conversation_id: UUID,
    message_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> list[TaskCandidateOut]:
    try:
        _, message = await get_owned_message(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
    except ReuseError as exc:
        raise _error(exc) from None
    return [TaskCandidateOut(**item) for item in extract_task_candidates(message.content)]


@router.post(
    "/conversations/{conversation_id}/messages/{message_id}/save-to-knowledge",
    response_model=SavedDocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def save_message_to_knowledge(
    conversation_id: UUID,
    message_id: UUID,
    payload: SaveAnswerIn,
    context: JwtContext,
    session: SessionDep,
    queue: QueueDep,
) -> SavedDocumentOut:
    try:
        conversation, message = await get_owned_message(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
        result = await save_answer_to_knowledge(
            session,
            queue=queue,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            conversation=conversation,
            message=message,
            kb_id=payload.kb_id,
            title=payload.title,
        )
    except ReuseError as exc:
        raise _error(exc) from None
    return SavedDocumentOut(**result)
