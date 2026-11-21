import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.config import get_settings
from app.db import get_session
from app.deps import AuthContext, get_jwt_context, require_scope
from app.models import Chunk, ChunkEmbedding, Document, IngestionJob
from app.schemas import DocumentOut, DocumentUploadOut
from app.services.access import get_owned_document, get_owned_knowledge_base
from app.services.parsing import UnsupportedDocumentType
from app.services.queue import JobQueue, get_queue
from app.services.quotas import enforce_quota
from app.services.storage import EmptyUpload, UploadTooLarge, save_upload

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
ReadContext = Annotated[AuthContext, Depends(require_scope("kb:read"))]
QueueDep = Annotated[JobQueue, Depends(get_queue)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]


async def _enqueue_or_fail(
    session: AsyncSession,
    document: Document,
    job: IngestionJob,
    queue: JobQueue,
    *,
    unique: bool = False,
) -> None:
    try:
        await queue.enqueue_ingestion(document.id, unique=unique)
    except Exception:
        logger.exception("failed to enqueue ingestion for %s", document.id)
        document.status = "failed"
        document.error_code = "queue_unavailable"
        job.status = "failed"
        job.error = "queue_unavailable"
        job.lease_expires_at = None
        job.finished_at = datetime.now(UTC)
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {
                "code": "queue_unavailable",
                "message": "Ingestion queue unavailable",
                "document_id": str(document.id),
            },
        ) from None


@router.post(
    "/knowledge-bases/{kb_id}/documents",
    response_model=DocumentUploadOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    kb_id: UUID,
    file: Annotated[UploadFile, File()],
    context: JwtContext,
    session: SessionDep,
    queue: QueueDep,
    redis: RedisDep,
    response: Response,
) -> DocumentUploadOut:
    await enforce_quota(redis, context)
    await get_owned_knowledge_base(kb_id, context.workspace.id, session)
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
            Document.workspace_id == context.workspace.id,
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
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        filename=file.filename or saved.storage_name,
        mime=saved.mime,
        size_bytes=saved.size_bytes,
        content_hash=saved.content_hash,
        status="uploaded",
        storage_path=saved.storage_name,
    )
    job = IngestionJob(workspace_id=context.workspace.id, status="queued")
    try:
        session.add(document)
        await session.flush()
        job.document_id = document.id
        session.add(job)
        await session.commit()
        await session.refresh(document)
    except Exception:
        await session.rollback()
        saved.path.unlink(missing_ok=True)
        raise

    await _enqueue_or_fail(session, document, job, queue)
    return DocumentUploadOut(id=document.id, status=document.status, duplicate=False)


@router.get("/knowledge-bases/{kb_id}/documents", response_model=list[DocumentOut])
async def list_documents(kb_id: UUID, context: ReadContext, session: SessionDep) -> list[Document]:
    await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    result = await session.execute(
        select(Document)
        .where(
            Document.kb_id == kb_id,
            Document.workspace_id == context.workspace.id,
            Document.deleted_at.is_(None),
        )
        .order_by(Document.created_at.desc(), Document.id.desc())
    )
    return list(result.scalars())


@router.post(
    "/documents/{document_id}/retry",
    response_model=DocumentUploadOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_document(
    document_id: UUID,
    context: JwtContext,
    session: SessionDep,
    queue: QueueDep,
) -> DocumentUploadOut:
    document = await get_owned_document(document_id, context.workspace.id, session)
    job = (
        await session.execute(select(IngestionJob).where(IngestionJob.document_id == document.id))
    ).scalar_one_or_none()
    if document.status != "failed" or job is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "document_not_failed", "message": "Only failed documents can be retried"},
        )

    document.status = "uploaded"
    document.error_code = None
    job.status = "queued"
    job.attempts = 0
    job.error = None
    job.started_at = None
    job.finished_at = None
    job.lease_expires_at = None
    await session.commit()

    await _enqueue_or_fail(session, document, job, queue, unique=True)
    return DocumentUploadOut(id=document.id, status="uploaded", duplicate=False)


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(document_id: UUID, context: ReadContext, session: SessionDep) -> Document:
    return await get_owned_document(document_id, context.workspace.id, session)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: UUID, context: JwtContext, session: SessionDep) -> Response:
    document = await get_owned_document(document_id, context.workspace.id, session)
    document.deleted_at = datetime.now(UTC)
    chunk_ids = select(Chunk.id).where(Chunk.document_id == document.id)
    await session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id.in_(chunk_ids)))
    await session.execute(delete(Chunk).where(Chunk.document_id == document.id))
    await session.commit()

    stored_path = Path(get_settings().upload_dir) / document.storage_path
    try:
        stored_path.unlink(missing_ok=True)
    except OSError:
        logger.warning("failed to delete stored file for document %s", document.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
