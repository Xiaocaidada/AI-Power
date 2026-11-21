from sqlalchemy import select


async def _seed_document(text="hello world", suffix=".txt", mime="text/plain"):
    from pathlib import Path

    from uuid6 import uuid7

    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import Document, IngestionJob, KnowledgeBase, User

    settings = get_settings()
    async with SessionLocal() as session:
        user = User(email=f"{uuid7()}@ingest.local", password_hash="x")
        session.add(user)
        await session.flush()
        kb = KnowledgeBase(user_id=user.id, name="KB")
        session.add(kb)
        await session.flush()
        path = Path(settings.upload_dir) / f"{uuid7()}{suffix}"
        path.write_text(text, encoding="utf-8")
        document = Document(
            kb_id=kb.id,
            user_id=user.id,
            filename=f"doc{suffix}",
            mime=mime,
            size_bytes=len(text.encode("utf-8")),
            content_hash=str(uuid7()),
            status="uploaded",
            storage_path=path.name,
        )
        session.add(document)
        await session.flush()
        job = IngestionJob(document_id=document.id, status="queued")
        session.add(job)
        await session.commit()
        return document.id, job.id


async def _load(document_id, job_id):
    from app.db import SessionLocal
    from app.models import Chunk, ChunkEmbedding, Document, IngestionJob

    async with SessionLocal() as session:
        document = await session.get(Document, document_id)
        job = await session.get(IngestionJob, job_id)
        chunks = (
            (await session.execute(select(Chunk).where(Chunk.document_id == document_id)))
            .scalars()
            .all()
        )
        embeddings = (
            (
                await session.execute(
                    select(ChunkEmbedding).where(
                        ChunkEmbedding.chunk_id.in_([chunk.id for chunk in chunks])
                    )
                )
            )
            .scalars()
            .all()
        )
        return document, job, chunks, embeddings


async def test_ingest_document_marks_ready_and_stores_chunks(fake_ingestion):
    from app.services.ingestion import ingest_document

    document_id, job_id = await _seed_document()

    await ingest_document(document_id)

    document, job, chunks, embeddings = await _load(document_id, job_id)
    assert document.status == "ready"
    assert document.page_count == 1
    assert document.error_code is None
    assert job.status == "succeeded"
    assert len(chunks) == 1
    assert len(embeddings) == 1
    assert len(embeddings[0].embedding) == 1024


async def test_ingest_document_marks_failed_on_parse_error(fake_ingestion):
    from app.services.ingestion import ingest_document

    fake_ingestion.parser.error = RuntimeError("bad document")
    document_id, job_id = await _seed_document()

    await ingest_document(document_id)

    document, job, chunks, _embeddings = await _load(document_id, job_id)
    assert document.status == "failed"
    assert document.error_code == "parse_failed"
    assert job.status == "failed"
    assert chunks == []


async def test_ingest_document_marks_failed_on_embedding_error(fake_ingestion):
    from app.providers.base import ProviderError
    from app.services.ingestion import ingest_document

    fake_ingestion.embedder.error = ProviderError("embedding_http_error", "down")
    document_id, job_id = await _seed_document()

    await ingest_document(document_id)

    document, job, chunks, _embeddings = await _load(document_id, job_id)
    assert document.status == "failed"
    assert document.error_code == "embedding_failed"
    assert job.status == "failed"
    assert chunks == []


async def test_ingest_document_enforces_page_limit(fake_ingestion):
    from app.services.ingestion import ingest_document
    from app.services.parsing import ParsedPage

    fake_ingestion.parser.pages = [ParsedPage(page_no=index + 1, text="x") for index in range(201)]
    document_id, job_id = await _seed_document()

    await ingest_document(document_id)

    document, job, _chunks, _embeddings = await _load(document_id, job_id)
    assert document.status == "failed"
    assert document.error_code == "too_many_pages"
    assert job.status == "failed"


async def test_ingest_document_is_idempotent_on_retry(fake_ingestion):
    from app.services.ingestion import ingest_document

    document_id, job_id = await _seed_document()

    await ingest_document(document_id)
    await ingest_document(document_id)

    _document, _job, chunks, embeddings = await _load(document_id, job_id)
    assert len(chunks) == 1
    assert len(embeddings) == 1


async def test_ingest_document_ignores_deleted_document(fake_ingestion):
    from app.db import SessionLocal
    from app.models import Document
    from app.services.ingestion import ingest_document

    document_id, job_id = await _seed_document()
    async with SessionLocal() as session:
        document = await session.get(Document, document_id)
        document.deleted_at = document.created_at
        await session.commit()

    await ingest_document(document_id)

    _document, _job, chunks, _embeddings = await _load(document_id, job_id)
    assert chunks == []


async def test_ingest_document_batches_embeddings(fake_ingestion):
    from app.services.ingestion import ingest_document
    from app.services.parsing import ParsedPage

    fake_ingestion.parser.pages = [ParsedPage(page_no=1, text="a" * 250)]
    document_id, _job_id = await _seed_document()

    await ingest_document(document_id)

    assert [len(batch) for batch in fake_ingestion.embedder.batches] == [2, 1]
