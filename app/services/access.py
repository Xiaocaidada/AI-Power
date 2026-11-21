from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, KnowledgeBase


async def get_owned_knowledge_base(
    kb_id: UUID, user_id: UUID, session: AsyncSession
) -> KnowledgeBase:
    result = await session.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.user_id == user_id,
            KnowledgeBase.deleted_at.is_(None),
        )
    )
    kb = result.scalar_one_or_none()
    if kb is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Knowledge base not found")
    return kb


async def get_owned_document(document_id: UUID, user_id: UUID, session: AsyncSession) -> Document:
    result = await session.execute(
        select(Document).where(
            Document.id == document_id,
            Document.user_id == user_id,
            Document.deleted_at.is_(None),
        )
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return document
