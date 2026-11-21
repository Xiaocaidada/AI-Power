from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import Trace
from app.schemas import TraceOut

router = APIRouter(prefix="/traces", tags=["traces"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


@router.get("", response_model=list[TraceOut])
async def list_traces(
    context: JwtContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: UUID | None = None,
) -> list[Trace]:
    conditions = [Trace.workspace_id == context.workspace.id]
    if before is not None:
        conditions.append(Trace.id < before)
    result = await session.execute(
        select(Trace).where(*conditions).order_by(Trace.id.desc()).limit(limit)
    )
    return list(result.scalars())


@router.get("/{request_id}", response_model=TraceOut)
async def get_trace(request_id: str, context: JwtContext, session: SessionDep) -> Trace:
    trace = (
        await session.execute(
            select(Trace)
            .where(
                Trace.request_id == request_id,
                Trace.workspace_id == context.workspace.id,
            )
            .order_by(Trace.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if trace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Trace not found")
    return trace
