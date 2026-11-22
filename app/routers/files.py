from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.deps import AuthContext, require_scope
from app.models import Document, KnowledgeBase
from app.schemas import FileOut
from app.services.access import get_owned_document

router = APIRouter(tags=["files"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReadContext = Annotated[AuthContext, Depends(require_scope("kb:read"))]


@router.get("/files", response_model=list[FileOut])
async def list_files(
    context: ReadContext,
    session: SessionDep,
    q: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: UUID | None = None,
) -> list[FileOut]:
    conditions = [
        Document.workspace_id == context.workspace.id,
        Document.deleted_at.is_(None),
        KnowledgeBase.deleted_at.is_(None),
    ]
    if q and q.strip() != "":
        escaped = (
            q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        conditions.append(Document.filename.ilike(f"%{escaped}%", escape="\\"))
    if status_filter:
        conditions.append(Document.status == status_filter)
    if before is not None:
        conditions.append(Document.id < before)
    rows = (
        await session.execute(
            select(Document, KnowledgeBase.name)
            .join(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
            .where(*conditions)
            .order_by(Document.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        FileOut(
            id=document.id,
            filename=document.filename,
            mime=document.mime,
            size_bytes=document.size_bytes,
            status=document.status,
            error_code=document.error_code,
            page_count=document.page_count,
            kb_id=document.kb_id,
            kb_name=kb_name,
            created_at=document.created_at,
        )
        for document, kb_name in rows
    ]


@router.get("/documents/{document_id}/download")
async def download_document(
    document_id: UUID, context: ReadContext, session: SessionDep
) -> FileResponse:
    document = await get_owned_document(document_id, context.workspace.id, session)
    base = Path(get_settings().upload_dir).resolve()
    path = (base / document.storage_path).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document file not found")
    return FileResponse(path, media_type=document.mime, filename=document.filename)