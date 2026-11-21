from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import Trace
from app.schemas import TraceOut

router = APIRouter(prefix="/traces", tags=["traces"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


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
