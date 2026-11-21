import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.models import Chunk, ChunkEmbedding, Document, IngestionJob
from app.providers.base import ProviderError
from app.services.chunking import chunk_pages
from app.services.embedding_factory import build_embedder
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

        job = await _get_or_create_job(session, document.id)
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
            parsed = _parse(document, settings)
            if len(parsed.pages) > settings.max_document_pages:
                raise IngestionError(
                    "too_many_pages",
                    f"Document has {len(parsed.pages)} pages (limit {settings.max_document_pages})",
                )
            document.page_count = len(parsed.pages)
            chunks = chunk_pages(
                parsed.pages,
                settings.chunk_max_chars,
                settings.chunk_overlap_chars,
            )
            if not chunks:
                raise IngestionError("empty_document", "Document produced no text chunks")

            document.status = "embedding"
            await session.commit()

            embedder = build_embedder()
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
                            user_id=document.user_id,
                            kb_id=document.kb_id,
                            page_no=chunk.page_no,
                            chunk_index=chunk.chunk_index,
                            text=chunk.text,
                        )
                    )
                    embeddings.append(vector)

            await _delete_chunks(session, document.id)
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
            await _mark_failed(session, document.id, exc.code)
            return IngestionOutcome(status="failed", error_code=exc.code, attempts=attempts)
        except ProviderError:
            await session.rollback()
            await _mark_failed(session, document.id, "embedding_failed")
            return IngestionOutcome(
                status="failed", error_code="embedding_failed", attempts=attempts
            )
        except Exception:
            logger.exception("ingestion failed for document %s", document.id)
            await session.rollback()
            await _mark_failed(session, document.id, "ingestion_failed")
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
