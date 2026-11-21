import logging
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings
from app.db import SessionLocal
from app.services.ingestion import ingest_document, mark_job_dead, schedule_retry
from app.services.maintenance import cleanup_orphan_files, cleanup_traces
from app.services.queue import ArqJobQueue, recover_stale_jobs

logger = logging.getLogger(__name__)


async def ingest_document_job(ctx: dict[str, Any], document_id: str) -> None:
    document_uuid = UUID(document_id)
    outcome = await ingest_document(document_uuid)
    if outcome.status != "failed":
        return

    settings = get_settings()
    if outcome.attempts >= settings.ingestion_max_attempts:
        await mark_job_dead(document_uuid)
        return

    await schedule_retry(document_uuid)
    await ctx["redis"].enqueue_job(
        "ingest_document_job",
        str(document_uuid),
        _job_id=f"ingest:{document_uuid}:retry:{uuid4().hex[:12]}",
        _defer_by=2**outcome.attempts,
    )


async def recover_stale_jobs_job(ctx: dict[str, Any]) -> None:
    queue = ArqJobQueue(ctx["redis"])
    async with SessionLocal() as session:
        recovered = await recover_stale_jobs(session, queue)
        await session.commit()
    if recovered:
        logger.warning("requeued %s stale ingestion jobs", recovered)


async def cleanup_orphan_files_job(ctx: dict[str, Any]) -> None:
    async with SessionLocal() as session:
        removed = await cleanup_orphan_files(session, Path(get_settings().upload_dir))
    if removed:
        logger.info("removed %s orphan upload files", removed)


async def cleanup_traces_job(ctx: dict[str, Any]) -> None:
    async with SessionLocal() as session:
        removed = await cleanup_traces(session)
    if removed:
        logger.info("removed %s expired traces", removed)


class WorkerSettings:
    functions = [ingest_document_job]
    cron_jobs = [
        cron(recover_stale_jobs_job, minute=set(range(60))),
        cron(cleanup_orphan_files_job, hour=3, minute=0),
        cron(cleanup_traces_job, hour=3, minute=15),
    ]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 1
    job_timeout = 900
    keep_result = 3600
