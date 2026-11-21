from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Document, IngestionJob, KnowledgeBase, User, Workspace


class FakePool:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple, dict]] = []

    async def enqueue_job(self, name, *args, **kwargs):
        self.jobs.append((name, args, kwargs))


async def _seed_job(status="running", lease=None, attempts=1):
    async with SessionLocal() as session:
        user = User(email=f"{uuid4()}@queue.local", password_hash="x")
        session.add(user)
        await session.flush()
        workspace = Workspace(name="KB", plan="free", is_personal=False)
        session.add(workspace)
        await session.flush()
        kb = KnowledgeBase(workspace_id=workspace.id, user_id=user.id, name="KB")
        session.add(kb)
        await session.flush()
        document = Document(
            workspace_id=workspace.id,
            kb_id=kb.id,
            user_id=user.id,
            filename="a.txt",
            mime="text/plain",
            size_bytes=1,
            content_hash=str(uuid4()),
            storage_path="a.txt",
            status="parsing" if status == "running" else "failed",
        )
        session.add(document)
        await session.flush()
        job = IngestionJob(
            workspace_id=workspace.id,
            document_id=document.id,
            status=status,
            attempts=attempts,
            lease_expires_at=lease,
        )
        session.add(job)
        await session.commit()
        return document.id, job.id


async def test_arq_queue_enqueues_with_deduplicated_job_id():
    from app.services.queue import ArqJobQueue

    pool = FakePool()
    document_id = uuid4()

    await ArqJobQueue(pool).enqueue_ingestion(document_id)

    name, args, kwargs = pool.jobs[0]
    assert name == "ingest_document_job"
    assert args == (str(document_id),)
    assert kwargs["_job_id"] == f"ingest:{document_id}"


async def test_arq_queue_unique_enqueue_uses_fresh_job_id():
    from app.services.queue import ArqJobQueue

    pool = FakePool()
    document_id = uuid4()

    await ArqJobQueue(pool).enqueue_ingestion(document_id, unique=True)

    _name, _args, kwargs = pool.jobs[0]
    assert kwargs["_job_id"].startswith(f"ingest:{document_id}:")
    assert kwargs["_job_id"] != f"ingest:{document_id}"


async def test_recover_stale_jobs_requeues_only_expired_leases():
    from app.services.queue import ArqJobQueue, recover_stale_jobs

    now = datetime.now(UTC)
    expired_document, expired_job_id = await _seed_job("running", now - timedelta(minutes=1))
    _active_document, active_job_id = await _seed_job("running", now + timedelta(minutes=10))
    queued_document, _ = await _seed_job("queued", None)
    pool = FakePool()

    async with SessionLocal() as session:
        recovered = await recover_stale_jobs(session, ArqJobQueue(pool), now=now)
        await session.commit()

    assert recovered == 1
    assert [args[0] for _, args, _ in pool.jobs] == [str(expired_document)]

    async with SessionLocal() as session:
        expired_job = await session.get(IngestionJob, expired_job_id)
        active_job = await session.get(IngestionJob, active_job_id)
        queued_job = (
            await session.execute(
                select(IngestionJob).where(IngestionJob.document_id == queued_document)
            )
        ).scalar_one()

    assert expired_job.status == "queued"
    assert expired_job.lease_expires_at is None
    assert active_job.status == "running"
    assert queued_job.status == "queued"


async def test_mark_job_dead_sets_dead_and_finished_at():
    from app.services.ingestion import mark_job_dead

    document_id, job_id = await _seed_job("failed", None, attempts=3)

    await mark_job_dead(document_id)

    async with SessionLocal() as session:
        job = await session.get(IngestionJob, job_id)
        document = await session.get(Document, document_id)

    assert job.status == "dead"
    assert job.finished_at is not None
    assert job.lease_expires_at is None
    assert document.status == "failed"


async def test_schedule_retry_resets_job_and_document():
    from app.services.ingestion import schedule_retry

    document_id, job_id = await _seed_job("failed", None, attempts=1)

    await schedule_retry(document_id)

    async with SessionLocal() as session:
        job = await session.get(IngestionJob, job_id)
        document = await session.get(Document, document_id)

    assert job.status == "queued"
    assert job.lease_expires_at is None
    assert job.finished_at is None
    assert document.status == "uploaded"
    assert document.error_code is None
