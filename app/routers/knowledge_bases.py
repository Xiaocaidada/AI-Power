from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import get_current_user
from app.models import KnowledgeBase, User
from app.schemas import KnowledgeBaseCreate, KnowledgeBaseOut
from app.services.access import get_owned_knowledge_base

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("", response_model=KnowledgeBaseOut, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate, current_user: CurrentUser, session: SessionDep
) -> KnowledgeBase:
    kb = KnowledgeBase(user_id=current_user.id, name=payload.name)
    session.add(kb)
    await session.commit()
    await session.refresh(kb)
    return kb


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_knowledge_bases(
    current_user: CurrentUser, session: SessionDep
) -> list[KnowledgeBase]:
    result = await session.execute(
        select(KnowledgeBase)
        .where(
            KnowledgeBase.user_id == current_user.id,
            KnowledgeBase.deleted_at.is_(None),
        )
        .order_by(KnowledgeBase.created_at.desc())
    )
    return list(result.scalars())


@router.get("/{kb_id}", response_model=KnowledgeBaseOut)
async def get_knowledge_base(
    kb_id: UUID, current_user: CurrentUser, session: SessionDep
) -> KnowledgeBase:
    return await get_owned_knowledge_base(kb_id, current_user.id, session)


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(
    kb_id: UUID, current_user: CurrentUser, session: SessionDep
) -> Response:
    kb = await get_owned_knowledge_base(kb_id, current_user.id, session)
    kb.deleted_at = datetime.now(UTC)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
