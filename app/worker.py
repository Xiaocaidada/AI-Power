import logging
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from arq import cron
from arq.connections import RedisSettings

from app.config import get_settings
from app.db import SessionLocal
from app.models import Document
from app.services.chat_tasks import execute_chat_task, requeue_stale_tasks
from app.services.evaluation_runner import run_evaluation
from app.services.ingestion import ingest_document, mark_job_dead, schedule_retry
from app.services.maintenance import (
    cleanup_audit_logs,
    cleanup_media_assets,
    cleanup_orphan_files,
    cleanup_traces,
)
from app.services.memories import expire_retention_memories
from app.services.memory_extraction import (
    run_document_memory_extraction,
    run_memory_extraction_for_message,
    run_workflow_memory_extraction,
    schedule_document_memory_extraction,
)
from app.services.memory_quality import nightly_consolidation
from app.services.model_eval import run_model_eval_job
from app.services.queue import ArqJobQueue, recover_stale_jobs
from app.services.run_execution import (
    execute_collaboration_run,
    execute_workflow_run,
    requeue_waiting_reviews,
)
from app.services.webhooks import deliver_due_deliveries, enqueue_event

logger = logging.getLogger(__name__)


async def _emit_document_event(document_id: UUID, event: str) -> None:
    async with SessionLocal() as session:
        document = await session.get(Document, document_id)
        if document is None:
            return
        await enqueue_event(
            document.workspace_id,
            event,
            {
                "document_id": str(document.id),
                "kb_id": str(document.kb_id),
                "filename": document.filename,
                "status": document.status,
                "error_code": document.error_code,
                "page_count": document.page_count,
            },
        )


async def ingest_document_job(ctx: dict[str, Any], document_id: str) -> None:
    document_uuid = UUID(document_id)
    outcome = await ingest_document(document_uuid)
    if outcome.status == "ready":
        await _emit_document_event(document_uuid, "document.ready")
        await schedule_document_memory_extraction(document_uuid)
        return
    if outcome.status != "failed":
        return

    settings = get_settings()
    if outcome.attempts >= settings.ingestion_max_attempts:
        await _emit_document_event(document_uuid, "document.failed")
        await mark_job_dead(document_uuid)
        return

    await schedule_retry(document_uuid)
    await ctx["redis"].enqueue_job(
        "ingest_document_job",
        str(document_uuid),
        _job_id=f"ingest:{document_uuid}:retry:{uuid4().hex[:12]}",
        _defer_by=2**outcome.attempts,
    )


async def run_evaluation_job(ctx: dict[str, Any], run_id: str) -> None:
    await run_evaluation(UUID(run_id))


async def run_workflow_job(ctx: dict[str, Any], run_id: str) -> None:
    await execute_workflow_run(UUID(run_id), redis=ctx["redis"])


async def run_collaboration_job(ctx: dict[str, Any], run_id: str) -> None:
    await execute_collaboration_run(UUID(run_id), redis=ctx["redis"])


async def consolidate_memories_job(ctx: dict[str, Any]) -> None:
    async with SessionLocal() as session:
        result = await nightly_consolidation(session)
        await session.commit()
    logger.info("memory consolidation complete: %s", result)


async def expire_memories_job(ctx: dict[str, Any]) -> None:
    async with SessionLocal() as session:
        result = await expire_retention_memories(session)
        await session.commit()
    logger.info("memory retention complete: %s", result)


async def run_memory_extraction_job(ctx: dict[str, Any], message_id: str) -> None:
    await run_memory_extraction_for_message(UUID(message_id))


async def run_workflow_memory_extraction_job(ctx: dict[str, Any], run_id: str) -> None:
    await run_workflow_memory_extraction(UUID(run_id))


async def run_document_memory_extraction_job(ctx: dict[str, Any], document_id: str) -> None:
    await run_document_memory_extraction(UUID(document_id))


async def run_chat_task_job(ctx: dict[str, Any], task_id: str) -> None:
    await execute_chat_task(UUID(task_id))


async def requeue_stale_chat_tasks_job(ctx: dict[str, Any]) -> None:
    queue = ArqJobQueue(ctx["redis"])
    async with SessionLocal() as session:
        task_ids = await requeue_stale_tasks(session)
    for task_id in task_ids:
        await queue.enqueue_chat_task(task_id)
    if task_ids:
        logger.info("requeued %s stale chat tasks", len(task_ids))


async def deliver_webhooks_job(ctx: dict[str, Any]) -> None:
    delivered = await deliver_due_deliveries()
    if delivered:
        logger.info("delivered %s webhook events", delivered)


async def recover_stale_jobs_job(ctx: dict[str, Any]) -> None:
    queue = ArqJobQueue(ctx["redis"])
    async with SessionLocal() as session:
        recovered = await recover_stale_jobs(session, queue)
        await session.commit()
    if recovered:
        logger.warning("requeued %s stale ingestion jobs", recovered)


async def requeue_waiting_reviews_job(ctx: dict[str, Any]) -> None:
    queue = ArqJobQueue(ctx["redis"])
    requeued = await requeue_waiting_reviews(queue)
    if requeued:
        logger.info("requeued %s paused workflow reviews", requeued)


async def startup_requeue_reviews(ctx: dict[str, Any]) -> None:
    try:
        await requeue_waiting_reviews_job(ctx)
    except Exception:
        logger.warning("startup review requeue failed", exc_info=True)
    try:
        await requeue_stale_chat_tasks_job(ctx)
    except Exception:
        logger.warning("startup chat task requeue failed", exc_info=True)


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


async def cleanup_media_assets_job(ctx: dict[str, Any]) -> None:
    async with SessionLocal() as session:
        removed = await cleanup_media_assets(
            session, Path(get_settings().upload_dir)
        )
    if removed:
        logger.info("removed %s expired media assets", removed)


async def cleanup_audit_logs_job(ctx: dict[str, Any]) -> None:
    async with SessionLocal() as session:
        removed = await cleanup_audit_logs(session)
    if removed:
        logger.info("removed %s expired audit logs", removed)


class WorkerSettings:
    functions = [
        ingest_document_job,
        run_evaluation_job,
        run_model_eval_job,
        run_workflow_job,
        run_collaboration_job,
        run_memory_extraction_job,
        run_workflow_memory_extraction_job,
        run_document_memory_extraction_job,
        run_chat_task_job,
    ]
    cron_jobs = [
        cron(recover_stale_jobs_job, minute=set(range(60))),
        cron(requeue_waiting_reviews_job, minute=set(range(60))),
        cron(requeue_stale_chat_tasks_job, minute=set(range(60))),
        cron(deliver_webhooks_job, minute=set(range(60))),
        cron(cleanup_orphan_files_job, hour=3, minute=0),
        cron(cleanup_traces_job, hour=3, minute=15),
        cron(cleanup_audit_logs_job, hour=3, minute=30),
        cron(cleanup_media_assets_job, hour=3, minute=45),
        cron(consolidate_memories_job, hour=4, minute=0),
        cron(expire_memories_job, hour=4, minute=30),
    ]
    on_startup = startup_requeue_reviews
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 1
    job_timeout = 3600
    keep_result = 3600
