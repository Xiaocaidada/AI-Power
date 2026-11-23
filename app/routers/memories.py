from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.schemas import MemoryIn, MemoryOut, MemoryUpdate
from app.services.memories import (
    MemoryError,
    create_memory,
    delete_memory,
    get_memory,
    list_memories,
    update_memory,
)

router = APIRouter(prefix="/memories", tags=["memories"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


def _error(exc: MemoryError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND
        if exc.code == "not_found"
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(code, {"code": exc.code, "message": exc.message})


@router.get("", response_model=list[MemoryOut])
async def list_workspace_memories(
    context: JwtContext,
    session: SessionDep,
    q: str = "",
    agent_id: UUID | None = None,
    scope: Literal["user", "workspace"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[MemoryOut]:
    rows = await list_memories(
        session,
        context.workspace.id,
        context.user.id,
        query=q,
        agent_id=agent_id,
        scope=scope,
        limit=limit,
    )
    return [MemoryOut.model_validate(row) for row in rows]


@router.post("", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_workspace_memory(
    payload: MemoryIn, context: JwtContext, session: SessionDep
) -> MemoryOut:
    try:
        memory = await create_memory(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            content=payload.content,
            title=payload.title,
            scope=payload.scope,
            kind=payload.kind,
            agent_id=payload.agent_id,
            importance=payload.importance,
        )
    except MemoryError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(memory)
    return MemoryOut.model_validate(memory)


@router.patch("/{memory_id}", response_model=MemoryOut)
async def update_workspace_memory(
    memory_id: UUID,
    payload: MemoryUpdate,
    context: JwtContext,
    session: SessionDep,
) -> MemoryOut:
    try:
        memory = await get_memory(
            session, context.workspace.id, context.user.id, memory_id
        )
        memory = await update_memory(
            session,
            memory,
            content=payload.content,
            title=payload.title,
            scope=payload.scope,
            kind=payload.kind,
            importance=payload.importance,
        )
    except MemoryError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(memory)
    return MemoryOut.model_validate(memory)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_memory(
    memory_id: UUID, context: JwtContext, session: SessionDep
) -> Response:
    try:
        memory = await get_memory(
            session, context.workspace.id, context.user.id, memory_id
        )
        await delete_memory(session, memory)
    except MemoryError as exc:
        raise _error(exc) from None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)