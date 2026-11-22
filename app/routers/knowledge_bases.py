from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, require_scope
from app.models import Chunk, Document, KnowledgeBase
from app.providers.base import ProviderError
from app.schemas import (
    ChunkOut,
    ChunkPageOut,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseSettingsOut,
    KnowledgeBaseSettingsUpdate,
    KnowledgeBaseStatsOut,
    KnowledgeBaseUpdate,
    RetrievalHitOut,
    RetrievalSearchIn,
    RetrievalSearchOut,
    RetrievalTimingsOut,
)
from app.services.access import get_owned_knowledge_base
from app.services.knowledge_settings import KnowledgeBaseSettings, resolve_kb_settings
from app.services.retrieval import retrieve_with_diagnostics

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
        description=payload.description,
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


@router.patch("/{kb_id}", response_model=KnowledgeBaseOut)
async def update_knowledge_base(
    kb_id: UUID,
    payload: KnowledgeBaseUpdate,
    context: JwtContext,
    session: SessionDep,
) -> KnowledgeBase:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        kb.name = str(data["name"])
    if "description" in data:
        kb.description = str(data["description"] or "")
    await session.commit()
    await session.refresh(kb)
    return kb


@router.get("/{kb_id}/settings", response_model=KnowledgeBaseSettingsOut)
async def get_knowledge_base_settings(
    kb_id: UUID, context: ReadContext, session: SessionDep
) -> KnowledgeBaseSettingsOut:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    return KnowledgeBaseSettingsOut(**resolve_kb_settings(kb).model_dump())


@router.patch("/{kb_id}/settings", response_model=KnowledgeBaseSettingsOut)
async def update_knowledge_base_settings(
    kb_id: UUID,
    payload: KnowledgeBaseSettingsUpdate,
    context: JwtContext,
    session: SessionDep,
) -> KnowledgeBaseSettingsOut:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    current = resolve_kb_settings(kb).model_dump(mode="json")
    updates = payload.model_dump(exclude_unset=True, mode="json")
    for section in ("chunking", "retrieval", "embedding", "rerank"):
        section_updates = updates.get(section)
        if isinstance(section_updates, dict):
            for key, value in section_updates.items():
                if value is not None or section in {"embedding", "rerank"}:
                    current[section][key] = value
    try:
        settings = KnowledgeBaseSettings.model_validate(current)
    except ValidationError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "invalid_settings", "message": "Invalid knowledge base settings"},
        ) from None
    kb.settings = settings.model_dump(mode="json")
    await session.commit()
    return KnowledgeBaseSettingsOut(**settings.model_dump())


@router.get("/{kb_id}/chunks", response_model=ChunkPageOut)
async def list_chunks(
    kb_id: UUID,
    context: ReadContext,
    session: SessionDep,
    document_id: UUID | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChunkPageOut:
    await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    conditions = [
        Chunk.workspace_id == context.workspace.id,
        Chunk.kb_id == kb_id,
        Document.deleted_at.is_(None),
    ]
    if document_id is not None:
        conditions.append(Chunk.document_id == document_id)
    if q is not None and q.strip():
        conditions.append(Chunk.text.contains(q.strip(), autoescape=True))

    total = (
        await session.execute(
            select(func.count())
            .select_from(Chunk)
            .join(Document, Document.id == Chunk.document_id)
            .where(*conditions)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(Chunk, Document.filename)
            .join(Document, Document.id == Chunk.document_id)
            .where(*conditions)
            .order_by(Chunk.document_id.desc(), Chunk.chunk_index, Chunk.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items = [
        ChunkOut(
            id=chunk.id,
            document_id=chunk.document_id,
            filename=filename,
            chunk_index=chunk.chunk_index,
            page_no=chunk.page_no,
            text=chunk.text,
            token_count=chunk.token_count,
            char_count=len(chunk.text),
            created_at=chunk.created_at,
        )
        for chunk, filename in rows
    ]
    return ChunkPageOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/{kb_id}/stats", response_model=KnowledgeBaseStatsOut)
async def get_knowledge_base_stats(
    kb_id: UUID, context: ReadContext, session: SessionDep
) -> KnowledgeBaseStatsOut:
    await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    document_conditions = (
        Document.workspace_id == context.workspace.id,
        Document.kb_id == kb_id,
        Document.deleted_at.is_(None),
    )

    async def count_documents(*extra) -> int:
        return (
            await session.execute(
                select(func.count()).select_from(Document).where(*document_conditions, *extra)
            )
        ).scalar_one()

    document_count = await count_documents()
    ready_count = await count_documents(Document.status == "ready")
    processing_count = await count_documents(
        Document.status.in_(("uploaded", "parsing", "embedding"))
    )
    failed_count = await count_documents(Document.status == "failed")
    chunk_count = (
        await session.execute(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.workspace_id == context.workspace.id, Chunk.kb_id == kb_id)
        )
    ).scalar_one()
    char_count = (
        await session.execute(
            select(func.coalesce(func.sum(func.length(Chunk.text)), 0)).where(
                Chunk.workspace_id == context.workspace.id, Chunk.kb_id == kb_id
            )
        )
    ).scalar_one()
    return KnowledgeBaseStatsOut(
        document_count=document_count,
        ready_count=ready_count,
        processing_count=processing_count,
        failed_count=failed_count,
        chunk_count=chunk_count,
        char_count=int(char_count),
    )


@router.post("/{kb_id}/retrieval/search", response_model=RetrievalSearchOut)
async def search_knowledge_base(
    kb_id: UUID,
    payload: RetrievalSearchIn,
    context: JwtContext,
    session: SessionDep,
) -> RetrievalSearchOut:
    await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    try:
        outcome = await retrieve_with_diagnostics(
            session,
            workspace_id=context.workspace.id,
            kb_id=kb_id,
            query=payload.query,
            top_k=payload.top_k,
            candidate_k=payload.candidate_k,
            hybrid_enabled=payload.hybrid_enabled,
            rerank_enabled=payload.rerank_enabled,
        )
    except ProviderError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            {"code": "retrieval_failed", "message": "Retrieval failed"},
        ) from None
    return RetrievalSearchOut(
        query=payload.query,
        mode=outcome.mode,
        hybrid_enabled=outcome.options.hybrid_enabled,
        rerank_enabled=outcome.options.rerank_enabled,
        results=[
            RetrievalHitOut(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                filename=chunk.filename,
                page_no=chunk.page_no,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                distance=chunk.distance,
                vector_rank=chunk.vector_rank,
                lexical_rank=chunk.lexical_rank,
                fused_score=chunk.fused_score,
                rerank_score=chunk.rerank_score,
            )
            for chunk in outcome.chunks
        ],
        timings=RetrievalTimingsOut(**outcome.timings),
    )


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(kb_id: UUID, context: JwtContext, session: SessionDep) -> Response:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    kb.deleted_at = datetime.now(UTC)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
