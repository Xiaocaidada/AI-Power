from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.deps import get_current_user
from app.models import Chunk, ChunkEmbedding, Document, IngestionJob, User
from app.schemas import DocumentOut, DocumentUploadOut
from app.services.access import get_owned_document, get_owned_knowledge_base
from app.services.ingestion import ingest_document
from app.services.parsing import UnsupportedDocumentType
from app.services.storage import EmptyUpload, UploadTooLarge, save_upload

router = APIRouter(tags=["documents"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post(
    "/knowledge-bases/{kb_id}/documents",
    response_model=DocumentUploadOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    kb_id: UUID,
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    current_user: CurrentUser,
    session: SessionDep,
    response: Response,
) -> DocumentUploadOut:
    await get_owned_knowledge_base(kb_id, current_user.id, session)
    settings = get_settings()
    try:
        saved = await save_upload(file, settings.upload_dir, settings.max_upload_bytes)
    except UnsupportedDocumentType as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from None
    except UploadTooLarge:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File too large") from None
    except EmptyUpload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file") from None

    existing_result = await session.execute(
        select(Document).where(
            Document.user_id == current_user.id,
            Document.kb_id == kb_id,
            Document.content_hash == saved.content_hash,
            Document.deleted_at.is_(None),
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        saved.path.unlink(missing_ok=True)
        response.status_code = status.HTTP_200_OK
        return DocumentUploadOut(id=existing.id, status=existing.status, duplicate=True)

    document = Document(
        kb_id=kb_id,
        user_id=current_user.id,
        filename=file.filename or saved.storage_name,
        mime=saved.mime,
        size_bytes=saved.size_bytes,
        content_hash=saved.content_hash,
        status="uploaded",
        storage_path=saved.storage_name,
    )
    try:
        session.add(document)
        await session.flush()
        session.add(IngestionJob(document_id=document.id, status="queued"))
        await session.commit()
        await session.refresh(document)
    except Exception:
        await session.rollback()
        saved.path.unlink(missing_ok=True)
        raise

    background_tasks.add_task(ingest_document, document.id)
    return DocumentUploadOut(id=document.id, status=document.status, duplicate=False)


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: UUID, current_user: CurrentUser, session: SessionDep
) -> Document:
    return await get_owned_document(document_id, current_user.id, session)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: UUID, current_user: CurrentUser, session: SessionDep
) -> Response:
    document = await get_owned_document(document_id, current_user.id, session)
    document.deleted_at = datetime.now(UTC)
    chunk_ids = select(Chunk.id).where(Chunk.document_id == document.id)
    await session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id.in_(chunk_ids)))
    await session.execute(delete(Chunk).where(Chunk.document_id == document.id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
