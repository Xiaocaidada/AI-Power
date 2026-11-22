import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import build_agent_registry
from app.clients import RedisLike
from app.db import SessionLocal
from app.deps import AuthContext
from app.models import (
    CollaborationRun,
    User,
    Workflow,
    WorkflowRun,
    WorkflowVersion,
    Workspace,
)
from app.providers.registry import ProviderRegistry
from app.services.collaboration import CollaborationRunner
from app.services.provider_configs import build_user_registry
from app.services.quotas import enforce_quota
from app.services.run_events import (
    append_collaboration_event,
    append_workflow_event,
)
from app.services.workflow.runner import WorkflowRunner
from app.services.workflow.schema import WorkflowValidationError, validate_definition
from app.tools.registry import build_tool_registry

logger = logging.getLogger(__name__)


async def _append_workflow(run_id: UUID, event: str, data: dict[str, object]) -> None:
    try:
        await append_workflow_event(run_id, event, data)
    except Exception:
        logger.exception("failed to append workflow event %s", event)


async def _append_collaboration(run_id: UUID, event: str, data: dict[str, object]) -> None:
    try:
        await append_collaboration_event(run_id, event, data)
    except Exception:
        logger.exception("failed to append collaboration event %s", event)


async def _claim_workflow(session: AsyncSession, run_id: UUID) -> bool:
    result = await session.execute(
        update(WorkflowRun)
        .where(WorkflowRun.id == run_id, WorkflowRun.status == "queued")
        .values(status="running")
    )
    return result.rowcount == 1


async def _claim_collaboration(session: AsyncSession, run_id: UUID) -> bool:
    result = await session.execute(
        update(CollaborationRun)
        .where(CollaborationRun.id == run_id, CollaborationRun.status == "queued")
        .values(status="running")
    )
    return result.rowcount == 1


async def _mark_failed(
    model: type[WorkflowRun] | type[CollaborationRun], run_id: UUID, error_code: str
) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(model)
            .where(model.id == run_id, model.status.in_(("running", "queued")))
            .values(status="failed", error_code=error_code, finished_at=datetime.now(UTC))
        )
        await session.commit()


async def _mark_cancelled(model: type[WorkflowRun] | type[CollaborationRun], run_id: UUID) -> None:
    async with SessionLocal() as session:
        await session.execute(
            update(model)
            .where(model.id == run_id, model.status.in_(("running", "queued")))
            .values(status="cancelled", error_code="cancelled", finished_at=datetime.now(UTC))
        )
        await session.commit()


def _context(user: User, workspace: Workspace, api_key_id: UUID | None) -> AuthContext:
    return AuthContext(user=user, workspace=workspace, role="member", api_key_id=api_key_id)


async def execute_workflow_run(
    run_id: UUID,
    *,
    provider_registry: ProviderRegistry | None = None,
    redis: RedisLike | None = None,
) -> None:
    async with SessionLocal() as session:
        if not await _claim_workflow(session, run_id):
            await session.rollback()
            return
        await session.commit()
        run = await session.get(WorkflowRun, run_id)
        if run is None:
            return
        workflow = await session.get(Workflow, run.workflow_id)
        version = await session.get(WorkflowVersion, run.version_id)
        workspace = await session.get(Workspace, run.workspace_id)
        user = await session.get(User, run.user_id)
        if workflow is None or version is None or workspace is None or user is None:
            await _mark_failed(WorkflowRun, run_id, "run_context_missing")
            return
        try:
            definition = validate_definition(version.definition)
        except WorkflowValidationError:
            await _mark_failed(WorkflowRun, run_id, "invalid_workflow")
            await _append_workflow(
                run_id,
                "workflow_end",
                {
                    "run_id": str(run_id),
                    "status": "failed",
                    "error_code": "invalid_workflow",
                },
            )
            return
        context = _context(user, workspace, run.api_key_id)
        scoped_registry = provider_registry or await build_user_registry(
            session, run.workspace_id, run.user_id
        )
        input_text = run.input_text
        version_number = version.version
        workflow_id = workflow.id
        kb_id = run.kb_id

    registry = scoped_registry
    tools = build_tool_registry()
    agents = build_agent_registry()
    runner = WorkflowRunner(
        run_id=run_id,
        workflow_id=workflow_id,
        version=version_number,
        definition=definition,
        provider_registry=registry,
        tool_registry=tools,
        agent_registry=agents,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        kb_id=kb_id,
        redis=redis,
        input_text=input_text,
        quota_guard=(lambda: enforce_quota(redis, context)) if redis is not None else None,
        api_key_id=context.api_key_id,
    )
    terminal = False
    try:
        async for event in runner.run():
            await _append_workflow(run_id, event.kind, event.data)
            terminal = event.kind == "workflow_end"
    except asyncio.CancelledError:
        await _mark_cancelled(WorkflowRun, run_id)
        await _append_workflow(
            run_id,
            "workflow_end",
            {"run_id": str(run_id), "status": "cancelled", "error_code": "cancelled"},
        )
        raise
    except Exception:
        logger.exception("workflow execution failed for run %s", run_id)
        if not terminal:
            await _mark_failed(WorkflowRun, run_id, "internal_error")
            await _append_workflow(
                run_id,
                "workflow_end",
                {"run_id": str(run_id), "status": "failed", "error_code": "internal_error"},
            )


async def execute_collaboration_run(
    run_id: UUID,
    *,
    provider_registry: ProviderRegistry | None = None,
    redis: RedisLike | None = None,
) -> None:
    async with SessionLocal() as session:
        if not await _claim_collaboration(session, run_id):
            await session.rollback()
            return
        await session.commit()
        run = await session.get(CollaborationRun, run_id)
        if run is None:
            return
        workspace = await session.get(Workspace, run.workspace_id)
        user = await session.get(User, run.user_id)
        if workspace is None or user is None:
            await _mark_failed(CollaborationRun, run_id, "run_context_missing")
            return
        context = _context(user, workspace, run.api_key_id)
        scoped_registry = provider_registry or await build_user_registry(
            session, run.workspace_id, run.user_id
        )
        provider_id = run.provider_id
        model = run.model
        kb_id = run.kb_id
        input_text = run.input_text

    registry = scoped_registry
    try:
        registry.get(provider_id)
    except Exception:
        await _mark_failed(CollaborationRun, run_id, "provider_not_found")
        await _append_collaboration(
            run_id,
            "collaboration_end",
            {
                "run_id": str(run_id),
                "status": "failed",
                "error_code": "provider_not_found",
            },
        )
        return
    runner = CollaborationRunner(
        run_id=run_id,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        provider_id=provider_id,
        model=model,
        kb_id=kb_id,
        redis=redis,
        input_text=input_text,
        provider_registry=registry,
        tool_registry=build_tool_registry(),
        agent_registry=build_agent_registry(),
        quota_guard=(lambda: enforce_quota(redis, context)) if redis is not None else None,
        api_key_id=context.api_key_id,
    )
    terminal = False
    try:
        async for event in runner.run():
            await _append_collaboration(run_id, event.kind, event.data)
            terminal = event.kind == "collaboration_end"
    except asyncio.CancelledError:
        await _mark_cancelled(CollaborationRun, run_id)
        await _append_collaboration(
            run_id,
            "collaboration_end",
            {"run_id": str(run_id), "status": "cancelled", "error_code": "cancelled"},
        )
        raise
    except Exception:
        logger.exception("collaboration execution failed for run %s", run_id)
        if not terminal:
            await _mark_failed(CollaborationRun, run_id, "internal_error")
            await _append_collaboration(
                run_id,
                "collaboration_end",
                {"run_id": str(run_id), "status": "failed", "error_code": "internal_error"},
            )
