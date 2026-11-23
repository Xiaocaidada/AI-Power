import hashlib
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
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import String, cast, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid6 import uuid7

from app.clients import RedisLike, get_redis
from app.config import get_settings
from app.db import get_session
from app.deps import AuthContext, get_jwt_context, require_scope
from app.metrics import metrics
from app.models import Chunk, ChunkEmbedding, Document, IngestionJob, KnowledgeBase
from app.schemas import (
    DocumentFolderOut,
    DocumentOut,
    DocumentUpdate,
    DocumentUploadOut,
    ErrorOut,
    FolderRenameIn,
    FolderRenameOut,
    SiteImportFailureOut,
    SiteImportIn,
    SiteImportOut,
    UrlImportIn,
)
from app.services.access import get_owned_document, get_owned_knowledge_base
from app.services.parsing import UnsupportedDocumentType, detect_mime, parser_for_mime
from app.services.queue import JobQueue, get_queue
from app.services.quotas import enforce_kb_document_quota, enforce_quota
from app.services.storage import EmptyUpload, UploadTooLarge, save_upload
from app.services.url_import import (
    FetchedUrl,
    UrlImportError,
    crawl_site,
    fetch_url_document,
)

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
    responses={
        404: {"model": ErrorOut, "description": "Knowledge base not found"},
        413: {"model": ErrorOut, "description": "Upload exceeds MAX_UPLOAD_BYTES"},
        415: {"model": ErrorOut, "description": "Unsupported document type"},
        429: {"model": ErrorOut, "description": "Quota exceeded"},
        503: {"model": ErrorOut, "description": "Ingestion queue unavailable"},
    },
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
        parser_for_mime(detect_mime(file.filename, file.content_type))
    except UnsupportedDocumentType as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from None
    try:
        saved = await save_upload(file, settings.upload_dir, settings.max_upload_bytes)
    except UnsupportedDocumentType as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from None
    except UploadTooLarge:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File too large") from None
    except EmptyUpload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file") from None
    try:
        await enforce_kb_document_quota(
            session, context, kb_id=kb_id, additional_bytes=saved.size_bytes
        )
    except HTTPException:
        saved.path.unlink(missing_ok=True)
        raise

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
        metrics.inc_counter(
            "ai_power_knowledge_imports_total", kind="upload", status="duplicate"
        )
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
    metrics.inc_counter(
        "ai_power_knowledge_imports_total", kind="upload", status="created"
    )
    return DocumentUploadOut(id=document.id, status=document.status, duplicate=False)


URL_MIME_SUFFIX = {
    "text/html": ".html",
    "text/plain": ".txt",
    "text/markdown": ".md",
}
URL_ERROR_STATUS = {
    "invalid_url": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "host_not_allowed": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "url_import_disabled": status.HTTP_403_FORBIDDEN,
    "unsupported_content_type": status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    "url_too_large": status.HTTP_413_CONTENT_TOO_LARGE,
    "empty_url": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "http_status": status.HTTP_502_BAD_GATEWAY,
    "http_timeout": status.HTTP_502_BAD_GATEWAY,
    "http_unreachable": status.HTTP_502_BAD_GATEWAY,
    "too_many_redirects": status.HTTP_502_BAD_GATEWAY,
}


async def _import_fetched_document(
    *,
    session: AsyncSession,
    queue: JobQueue,
    context: AuthContext,
    kb_id: UUID,
    fetched: FetchedUrl,
    folder: str,
    tags: list[str],
    source_url: str,
    settings,
) -> DocumentUploadOut:
    if len(fetched.content) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, "URL content too large"
        )
    await enforce_kb_document_quota(
        session, context, kb_id=kb_id, additional_bytes=len(fetched.content)
    )
    content_hash = hashlib.sha256(fetched.content).hexdigest()
    existing = (
        await session.execute(
            select(Document).where(
                Document.workspace_id == context.workspace.id,
                Document.kb_id == kb_id,
                Document.content_hash == content_hash,
                Document.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return DocumentUploadOut(
            id=existing.id, status=existing.status, duplicate=True
        )

    directory = Path(settings.upload_dir)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = URL_MIME_SUFFIX.get(fetched.mime, ".txt")
    storage_name = f"{uuid7()}{suffix}"
    stored_path = directory / storage_name
    try:
        stored_path.write_bytes(fetched.content)
    except OSError:
        logger.exception("failed to store imported URL content")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": "storage_unavailable", "message": "Storage unavailable"},
        ) from None

    document = Document(
        kb_id=kb_id,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        filename=fetched.filename,
        mime=fetched.mime,
        size_bytes=len(fetched.content),
        content_hash=content_hash,
        status="uploaded",
        storage_path=storage_name,
        folder=folder,
        tags=tags,
        source_url=source_url,
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
        stored_path.unlink(missing_ok=True)
        raise

    await _enqueue_or_fail(session, document, job, queue)
    return DocumentUploadOut(id=document.id, status=document.status, duplicate=False)


@router.post(
    "/knowledge-bases/{kb_id}/documents/import-url",
    response_model=DocumentUploadOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        404: {"model": ErrorOut, "description": "Knowledge base not found"},
        413: {"model": ErrorOut, "description": "URL content exceeds limits"},
        415: {"model": ErrorOut, "description": "Unsupported URL content type"},
        422: {"model": ErrorOut, "description": "Invalid or blocked URL"},
        502: {"model": ErrorOut, "description": "URL fetch failed"},
        503: {"model": ErrorOut, "description": "Ingestion queue unavailable"},
    },
)
async def import_document_from_url(
    kb_id: UUID,
    payload: UrlImportIn,
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
        fetched = await fetch_url_document(payload.url, settings=settings)
    except UrlImportError as exc:
        raise HTTPException(
            URL_ERROR_STATUS.get(exc.code, status.HTTP_502_BAD_GATEWAY),
            {"code": exc.code, "message": exc.message},
        ) from None
    result = await _import_fetched_document(
        session=session,
        queue=queue,
        context=context,
        kb_id=kb_id,
        fetched=fetched,
        folder=payload.folder,
        tags=payload.tags,
        source_url=payload.url,
        settings=settings,
    )
    metrics.inc_counter(
        "ai_power_knowledge_imports_total",
        kind="url",
        status="duplicate" if result.duplicate else "created",
    )
    if result.duplicate:
        response.status_code = status.HTTP_200_OK
    return result


@router.post(
    "/knowledge-bases/{kb_id}/documents/import-site",
    response_model=SiteImportOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def import_documents_from_site(
    kb_id: UUID,
    payload: SiteImportIn,
    context: JwtContext,
    session: SessionDep,
    queue: QueueDep,
    redis: RedisDep,
) -> SiteImportOut:
    await enforce_quota(redis, context)
    await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    settings = get_settings()
    outcome = await crawl_site(
        payload.url,
        max_pages=payload.max_pages,
        same_origin=payload.same_origin,
        settings=settings,
    )
    if not outcome.pages:
        failed = [
            SiteImportFailureOut(url=url, code=code)
            for url, code in outcome.failures[:20]
        ]
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            {
                "code": "site_import_failed",
                "message": "No pages could be imported",
                "failed": [item.model_dump() for item in failed],
            },
        )
    created: list[DocumentUploadOut] = []
    duplicates: list[DocumentUploadOut] = []
    failed = [
        SiteImportFailureOut(url=url, code=code)
        for url, code in outcome.failures[:20]
    ]
    for page in outcome.pages:
        try:
            result = await _import_fetched_document(
                session=session,
                queue=queue,
                context=context,
                kb_id=kb_id,
                fetched=page,
                folder=payload.folder,
                tags=payload.tags,
                source_url=page.url or payload.url,
                settings=settings,
            )
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            failed.append(
                SiteImportFailureOut(
                    url=page.url or payload.url,
                    code=str(detail.get("code") or exc.status_code),
                )
            )
            continue
        metrics.inc_counter(
            "ai_power_knowledge_imports_total",
            kind="site",
            status="duplicate" if result.duplicate else "created",
        )
        if result.duplicate:
            duplicates.append(result)
        else:
            created.append(result)
    for item in failed:
        metrics.inc_counter(
            "ai_power_knowledge_imports_total",
            kind="site",
            status="failed",
            code=item.code,
        )
    return SiteImportOut(
        pages=len(outcome.pages),
        created=created,
        duplicates=duplicates,
        failed=failed,
    )


@router.get("/knowledge-bases/{kb_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    kb_id: UUID,
    context: ReadContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: UUID | None = None,
    q: str | None = None,
    tag: str | None = None,
    folder: str | None = None,
) -> list[Document]:
    await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    conditions = [
        Document.kb_id == kb_id,
        Document.workspace_id == context.workspace.id,
        Document.deleted_at.is_(None),
    ]
    if before is not None:
        conditions.append(Document.id < before)
    if q is not None and q.strip():
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        conditions.append(Document.filename.ilike(f"%{term}%", escape="\\"))
    if tag is not None and tag.strip():
        conditions.append(cast(Document.tags, String).ilike(f'%"{tag.strip()}"%'))
    if folder is not None:
        normalized = "/".join(
            segment.strip()
            for segment in folder.replace("\\", "/").split("/")
            if segment.strip()
        )
        conditions.append(Document.folder == normalized)
    result = await session.execute(
        select(Document).where(*conditions).order_by(Document.id.desc()).limit(limit)
    )
    return list(result.scalars())


@router.get(
    "/knowledge-bases/{kb_id}/folders", response_model=list[DocumentFolderOut]
)
async def list_document_folders(
    kb_id: UUID, context: ReadContext, session: SessionDep
) -> list[DocumentFolderOut]:
    await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    rows = (
        await session.execute(
            select(Document.folder, func.count())
            .where(
                Document.kb_id == kb_id,
                Document.workspace_id == context.workspace.id,
                Document.deleted_at.is_(None),
            )
            .group_by(Document.folder)
            .order_by(Document.folder)
        )
    ).all()
    return [
        DocumentFolderOut(folder=folder or "", count=count) for folder, count in rows
    ]


@router.post(
    "/knowledge-bases/{kb_id}/folders/rename", response_model=FolderRenameOut
)
async def rename_document_folder(
    kb_id: UUID,
    payload: FolderRenameIn,
    context: JwtContext,
    session: SessionDep,
) -> FolderRenameOut:
    await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    source = payload.from_folder
    target = payload.to_folder
    if target == source or target.startswith(f"{source}/"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "invalid_target_folder",
                "message": "Target folder must not be inside the source folder",
            },
        )
    rows = list(
        (
            await session.execute(
                select(Document).where(
                    Document.kb_id == kb_id,
                    Document.workspace_id == context.workspace.id,
                    Document.deleted_at.is_(None),
                    (
                        (Document.folder == source)
                        | Document.folder.startswith(f"{source}/", autoescape=True)
                    ),
                )
            )
        ).scalars()
    )
    for document in rows:
        if document.folder == source:
            document.folder = target
        else:
            document.folder = target + document.folder[len(source) :]
    await session.commit()
    return FolderRenameOut(updated=len(rows))


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


@router.post(
    "/documents/{document_id}/reprocess",
    response_model=DocumentUploadOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reprocess_document(
    document_id: UUID,
    context: JwtContext,
    session: SessionDep,
    queue: QueueDep,
) -> DocumentUploadOut:
    document = await get_owned_document(document_id, context.workspace.id, session)
    if document.status in {"parsing", "embedding"}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "document_busy", "message": "Document is currently being processed"},
        )

    kb = await session.get(KnowledgeBase, document.kb_id)
    bound_workflow = (
        kb is not None and kb.process_workflow_version_id is not None
    )
    if not bound_workflow:
        chunk_ids = select(Chunk.id).where(Chunk.document_id == document.id)
        await session.execute(
            delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id.in_(chunk_ids))
        )
        await session.execute(delete(Chunk).where(Chunk.document_id == document.id))

    document.status = "uploaded"
    document.error_code = None
    document.page_count = None
    job = (
        await session.execute(select(IngestionJob).where(IngestionJob.document_id == document.id))
    ).scalar_one_or_none()
    if job is None:
        job = IngestionJob(
            workspace_id=document.workspace_id,
            document_id=document.id,
            status="queued",
        )
        session.add(job)
    else:
        job.status = "queued"
        job.attempts = 0
        job.error = None
        job.started_at = None
        job.finished_at = None
        job.lease_expires_at = None
    await session.commit()

    await _enqueue_or_fail(session, document, job, queue, unique=True)
    return DocumentUploadOut(id=document.id, status=document.status, duplicate=False)


@router.patch("/documents/{document_id}", response_model=DocumentOut)
async def update_document(
    document_id: UUID,
    payload: DocumentUpdate,
    context: JwtContext,
    session: SessionDep,
) -> Document:
    document = await get_owned_document(document_id, context.workspace.id, session)
    if payload.tags is not None:
        document.tags = payload.tags
    if payload.folder is not None:
        document.folder = payload.folder
    if payload.doc_metadata is not None:
        document.doc_metadata = payload.doc_metadata
    await session.commit()
    await session.refresh(document)
    return document


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
