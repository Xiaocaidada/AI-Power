from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, require_scope
from app.models import KnowledgeBase
from app.schemas import KnowledgeBaseCreate, KnowledgeBaseOut
from app.services.access import get_owned_knowledge_base

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
ReadContext = Annotated[AuthContext, Depends(require_scope("kb:read"))]


@router.post("", response_model=KnowledgeBaseOut, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate, context: JwtContext, session: SessionDep
) -> KnowledgeBase:
    kb = KnowledgeBase(
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        name=payload.name,
    )
    session.add(kb)
    await session.commit()
    await session.refresh(kb)
    return kb


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_knowledge_bases(context: ReadContext, session: SessionDep) -> list[KnowledgeBase]:
    result = await session.execute(
        select(KnowledgeBase)
        .where(
            KnowledgeBase.workspace_id == context.workspace.id,
            KnowledgeBase.deleted_at.is_(None),
        )
        .order_by(KnowledgeBase.created_at.desc())
    )
    return list(result.scalars())


@router.get("/{kb_id}", response_model=KnowledgeBaseOut)
async def get_knowledge_base(
    kb_id: UUID, context: ReadContext, session: SessionDep
) -> KnowledgeBase:
    return await get_owned_knowledge_base(kb_id, context.workspace.id, session)


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(kb_id: UUID, context: JwtContext, session: SessionDep) -> Response:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    kb.deleted_at = datetime.now(UTC)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
