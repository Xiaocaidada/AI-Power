from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.schemas import SearchOut, SearchResultOut
from app.services.search import global_search

router = APIRouter(tags=["search"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


@router.get("/search", response_model=SearchOut)
async def search_workspace(
    context: JwtContext,
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=100)],
) -> SearchOut:
    results = await global_search(
        session, context.workspace.id, context.user.id, q
    )
    return SearchOut(
        query=q,
        results=[SearchResultOut(**result) for result in results],
    )