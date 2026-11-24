from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import IngestionJob


class JobQueue(Protocol):
    async def enqueue_ingestion(self, document_id: UUID, *, unique: bool = False) -> None: ...

    async def enqueue_evaluation(self, run_id: UUID) -> None: ...

    async def enqueue_model_eval(self, run_id: UUID) -> None: ...

    async def enqueue_workflow_run(self, run_id: UUID) -> None: ...

    async def enqueue_workflow_resume(self, run_id: UUID) -> None: ...

    async def enqueue_collaboration_run(self, run_id: UUID) -> None: ...

    async def enqueue_memory_extraction(self, message_id: UUID) -> None: ...

    async def enqueue_workflow_memory_extraction(self, run_id: UUID) -> None: ...

    async def enqueue_document_memory_extraction(self, document_id: UUID) -> None: ...


class ArqJobQueue:
    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def enqueue_ingestion(self, document_id: UUID, *, unique: bool = False) -> None:
        job_id = f"ingest:{document_id}:{uuid4().hex[:12]}" if unique else f"ingest:{document_id}"
        await self._pool.enqueue_job(
            "ingest_document_job",
            str(document_id),
            _job_id=job_id,
        )

    async def enqueue_evaluation(self, run_id: UUID) -> None:
        await self._pool.enqueue_job(
            "run_evaluation_job",
            str(run_id),
            _job_id=f"eval:{run_id}",
        )

    async def enqueue_model_eval(self, run_id: UUID) -> None:
        await self._pool.enqueue_job(
            "run_model_eval_job",
            str(run_id),
            _job_id=f"modeleval:{run_id}:{uuid4().hex[:12]}",
        )

    async def enqueue_workflow_run(self, run_id: UUID) -> None:
        await self._pool.enqueue_job(
            "run_workflow_job",
            str(run_id),
            _job_id=f"wfrun:{run_id}",
        )

    async def enqueue_workflow_resume(self, run_id: UUID) -> None:
        # A paused run may still have the original job id retained by Arq, so
        # resumes use a fresh id and rely on the DB claim for idempotency.
        await self._pool.enqueue_job(
            "run_workflow_job",
            str(run_id),
            _job_id=f"wfrun:{run_id}:{uuid4().hex[:12]}",
        )

    async def enqueue_collaboration_run(self, run_id: UUID) -> None:
        await self._pool.enqueue_job(
            "run_collaboration_job",
            str(run_id),
            _job_id=f"collab:{run_id}",
        )

    async def enqueue_memory_extraction(self, message_id: UUID) -> None:
        await self._pool.enqueue_job(
            "run_memory_extraction_job",
            str(message_id),
            _job_id=f"memextract:{message_id}",
        )

    async def enqueue_workflow_memory_extraction(self, run_id: UUID) -> None:
        await self._pool.enqueue_job(
            "run_workflow_memory_extraction_job",
            str(run_id),
            _job_id=f"memextract:workflow:{run_id}",
        )

    async def enqueue_document_memory_extraction(self, document_id: UUID) -> None:
        await self._pool.enqueue_job(
            "run_document_memory_extraction_job",
            str(document_id),
            _job_id=f"memextract:document:{document_id}",
        )


_pool: ArqRedis | None = None


async def get_queue() -> JobQueue:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return ArqJobQueue(_pool)


async def close_queue() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def recover_stale_jobs(
    session: AsyncSession,
    queue: JobQueue,
    *,
    now: datetime | None = None,
) -> int:
    """Requeue jobs whose worker lease expired (e.g. the worker crashed)."""
    reference = now or datetime.now(UTC)
    result = await session.execute(
        select(IngestionJob).where(
            IngestionJob.status == "running",
            IngestionJob.lease_expires_at.is_not(None),
            IngestionJob.lease_expires_at < reference,
        )
    )
    stale = list(result.scalars())
    for job in stale:
        job.status = "queued"
        job.lease_expires_at = None
    await session.flush()

    for job in stale:
        await queue.enqueue_ingestion(job.document_id, unique=True)
    return len(stale)
