from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.schemas import CodeSnippetCreate, CodeSnippetOut
from app.services.reuse import (
    ReuseError,
    create_snippet,
    delete_snippet,
    list_snippets,
)

router = APIRouter(prefix="/code-snippets", tags=["reuse"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


def _error(exc: ReuseError) -> HTTPException:
    if exc.code in {
        "conversation_not_found",
        "message_not_found",
        "project_not_found",
        "snippet_not_found",
    }:
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"code": exc.code, "message": exc.message},
    )


@router.get("", response_model=list[CodeSnippetOut])
async def list_code_snippets(context: JwtContext, session: SessionDep) -> list[CodeSnippetOut]:
    rows = await list_snippets(session, context.workspace.id, context.user.id)
    return [CodeSnippetOut.model_validate(row) for row in rows]


@router.post("", response_model=CodeSnippetOut, status_code=status.HTTP_201_CREATED)
async def create_code_snippet(
    payload: CodeSnippetCreate,
    context: JwtContext,
    session: SessionDep,
) -> CodeSnippetOut:
    try:
        snippet = await create_snippet(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            conversation_id=payload.conversation_id,
            message_id=payload.message_id,
            project_id=payload.project_id,
            title=payload.title,
            language=payload.language,
            code=payload.code,
        )
    except ReuseError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(snippet)
    return CodeSnippetOut.model_validate(snippet)


@router.delete("/{snippet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_code_snippet(
    snippet_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> Response:
    from app.models import CodeSnippet

    snippet = await session.get(CodeSnippet, snippet_id)
    if snippet is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Code snippet not found")
    try:
        await delete_snippet(session, snippet, context.workspace.id, context.user.id)
    except ReuseError as exc:
        raise _error(exc) from None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
