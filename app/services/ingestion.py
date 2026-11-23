import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Chunk,
    ChunkEmbedding,
    Document,
    IngestionJob,
    KnowledgeBase,
    Workflow,
    WorkflowRun,
    WorkflowVersion,
)
from app.providers.base import ProviderError
from app.services.chunking import chunk_pages
from app.services.kb_models import build_kb_embedder
from app.services.knowledge_settings import resolve_kb_settings
from app.services.parsing import DocumentParser, UnsupportedDocumentType, parser_for_mime

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    status: str
    error_code: str | None = None
    attempts: int = 0


def build_parser(mime: str) -> DocumentParser:
    return parser_for_mime(mime)


async def ingest_document(document_id: UUID) -> IngestionOutcome:
    settings = get_settings()
    async with SessionLocal() as session:
        document = await session.get(Document, document_id)
        if document is None or document.deleted_at is not None:
            return IngestionOutcome(status="skipped")
        document_pk = document.id

        job = await _get_or_create_job(session, document_pk)
        now = datetime.now(UTC)
        document.status = "parsing"
        document.error_code = None
        job.status = "running"
        job.attempts += 1
        job.error = None
        job.started_at = now
        job.finished_at = None
        job.lease_expires_at = now + timedelta(minutes=settings.ingestion_lease_minutes)
        await session.commit()
        attempts = job.attempts

        try:
            kb = await session.get(KnowledgeBase, document.kb_id)
            if kb is None or kb.deleted_at is not None:
                raise IngestionError("kb_not_found", "Knowledge base no longer exists")
            kb_settings = resolve_kb_settings(kb)
            if kb.process_workflow_version_id is not None:
                return await _ingest_with_bound_workflow(
                    session, document, kb, job, attempts
                )
            parsed = _parse(document, settings)
            if len(parsed.pages) > settings.max_document_pages:
                raise IngestionError(
                    "too_many_pages",
                    f"Document has {len(parsed.pages)} pages (limit {settings.max_document_pages})",
                )
            document.page_count = len(parsed.pages)
            chunks = chunk_pages(
                parsed.pages,
                kb_settings.chunking.chunk_size,
                kb_settings.chunking.chunk_overlap,
            )
            if not chunks:
                raise IngestionError("empty_document", "Document produced no text chunks")

            document.status = "embedding"
            await session.commit()

            embedder = await build_kb_embedder(session, kb, kb_settings)
            chunk_rows: list[Chunk] = []
            embeddings: list[list[float]] = []
            for start in range(0, len(chunks), settings.embedding_batch_size):
                batch = chunks[start : start + settings.embedding_batch_size]
                vectors = await embedder.embed([chunk.text for chunk in batch])
                if len(vectors) != len(batch):
                    raise IngestionError(
                        "embedding_count_mismatch",
                        "Embedding count does not match chunk count",
                    )
                for chunk, vector in zip(batch, vectors, strict=True):
                    if len(vector) != settings.embedding_dim:
                        raise IngestionError(
                            "embedding_dimension_mismatch", "Embedding dimension mismatch"
                        )
                    chunk_rows.append(
                        Chunk(
                            document_id=document.id,
                            workspace_id=document.workspace_id,
                            user_id=document.user_id,
                            kb_id=document.kb_id,
                            page_no=chunk.page_no,
                            chunk_index=chunk.chunk_index,
                            text=chunk.text,
                        )
                    )
                    embeddings.append(vector)

            await _delete_chunks(session, document_pk)
            session.add_all(chunk_rows)
            await session.flush()
            session.add_all(
                [
                    ChunkEmbedding(chunk_id=chunk.id, embedding=vector)
                    for chunk, vector in zip(chunk_rows, embeddings, strict=True)
                ]
            )

            document.status = "ready"
            document.error_code = None
            job.status = "succeeded"
            job.error = None
            job.lease_expires_at = None
            job.finished_at = datetime.now(UTC)
            await session.commit()
            return IngestionOutcome(status="ready", attempts=attempts)
        except IngestionError as exc:
            await session.rollback()
            await _mark_failed(session, document_pk, exc.code)
            return IngestionOutcome(status="failed", error_code=exc.code, attempts=attempts)
        except ProviderError:
            await session.rollback()
            await _mark_failed(session, document_pk, "embedding_failed")
            return IngestionOutcome(
                status="failed", error_code="embedding_failed", attempts=attempts
            )
        except Exception:
            logger.exception("ingestion failed for document %s", document_pk)
            await session.rollback()
            await _mark_failed(session, document_pk, "ingestion_failed")
            return IngestionOutcome(
                status="failed", error_code="ingestion_failed", attempts=attempts
            )


async def schedule_retry(document_id: UUID) -> None:
    """Reset a failed document/job so the worker can run another attempt."""
    async with SessionLocal() as session:
        document = await session.get(Document, document_id)
        if document is None or document.deleted_at is not None:
            return
        job = await _get_or_create_job(session, document_id)
        document.status = "uploaded"
        document.error_code = None
        job.status = "queued"
        job.error = None
        job.lease_expires_at = None
        job.finished_at = None
        await session.commit()


async def mark_job_dead(document_id: UUID) -> None:
    async with SessionLocal() as session:
        job = await _get_or_create_job(session, document_id)
        job.status = "dead"
        job.lease_expires_at = None
        job.finished_at = datetime.now(UTC)
        await session.commit()


def _parse(document: Document, settings) -> object:
    try:
        parser = build_parser(document.mime)
    except UnsupportedDocumentType:
        raise IngestionError("unsupported_type", "Unsupported document type") from None
    try:
        return parser.parse(Path(settings.upload_dir) / document.storage_path, document.mime)
    except IngestionError:
        raise
    except Exception as exc:
        raise IngestionError("parse_failed", "Document parsing failed") from exc


async def _get_or_create_job(session: AsyncSession, document_id: UUID) -> IngestionJob:
    result = await session.execute(
        select(IngestionJob).where(IngestionJob.document_id == document_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        job = IngestionJob(document_id=document_id, status="queued")
        session.add(job)
        await session.flush()
    return job


async def _delete_chunks(session: AsyncSession, document_id: UUID) -> None:
    chunk_ids = select(Chunk.id).where(Chunk.document_id == document_id)
    await session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id.in_(chunk_ids)))
    await session.execute(delete(Chunk).where(Chunk.document_id == document_id))


async def _mark_failed(session: AsyncSession, document_id: UUID, code: str) -> None:
    document = await session.get(Document, document_id)
    if document is not None:
        document.status = "failed"
        document.error_code = code
    result = await session.execute(
        select(IngestionJob).where(IngestionJob.document_id == document_id)
    )
    job = result.scalar_one_or_none()
    if job is not None:
        job.status = "failed"
        job.error = code
        job.lease_expires_at = None
        job.finished_at = datetime.now(UTC)
    await session.commit()


async def _ingest_with_bound_workflow(
    session: AsyncSession,
    document: Document,
    kb: KnowledgeBase,
    job: IngestionJob,
    attempts: int,
) -> IngestionOutcome:
    """Run the KB's published processing workflow and apply its staged chunks."""
    from app.services.knowledge.apply import KnowledgeApplyError, apply_knowledge_run
    from app.services.run_execution import execute_knowledge_process_run

    version = await session.get(WorkflowVersion, kb.process_workflow_version_id)
    workflow = await session.get(Workflow, version.workflow_id) if version else None
    if (
        version is None
        or workflow is None
        or workflow.deleted_at is not None
        or workflow.kind != "knowledge_process"
    ):
        raise IngestionError(
            "processing_workflow_invalid",
            "The knowledge processing workflow is no longer available",
        )
    run = WorkflowRun(
        workflow_id=workflow.id,
        version_id=version.id,
        workspace_id=document.workspace_id,
        user_id=document.user_id,
        kb_id=document.kb_id,
        status="running",
        input_text=document.filename,
        input_payload={"document_id": str(document.id)},
    )
    session.add(run)
    document.status = "embedding"
    document.error_code = None
    await session.commit()
    run_id = run.id

    await execute_knowledge_process_run(run_id)

    async with SessionLocal() as apply_session:
        finished = await apply_session.get(WorkflowRun, run_id)
        target = await apply_session.get(Document, document.id)
        if finished is None or target is None:
            raise IngestionError("processing_failed", "Processing run disappeared")
        if finished.status != "completed":
            raise IngestionError(
                finished.error_code or "processing_failed",
                "Knowledge processing failed",
            )
        try:
            await apply_knowledge_run(apply_session, finished, target)
        except KnowledgeApplyError as exc:
            raise IngestionError(exc.code, exc.message) from None
        page_count = target.page_count
        process_version_id = target.process_version_id

    document.status = "ready"
    document.error_code = None
    document.page_count = page_count
    document.process_version_id = process_version_id
    job.status = "succeeded"
    job.error = None
    job.lease_expires_at = None
    job.finished_at = datetime.now(UTC)
    await session.commit()
    return IngestionOutcome(status="ready", attempts=attempts)
