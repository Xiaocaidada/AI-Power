import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import AgentRegistry
from app.clients import RedisLike, get_redis
from app.db import get_session
from app.deps import (
    AuthContext,
    get_agent_registry,
    get_jwt_context,
    get_registry,
    get_tool_registry,
    require_scope,
)
from app.models import Workflow, WorkflowNodeRun, WorkflowRun, WorkflowVersion
from app.providers.registry import ProviderRegistry
from app.schemas import (
    WorkflowCreate,
    WorkflowNodeRunOut,
    WorkflowOut,
    WorkflowRunCreate,
    WorkflowRunOut,
    WorkflowVersionCreate,
    WorkflowVersionOut,
)
from app.services.access import get_owned_knowledge_base
from app.services.quotas import enforce_quota
from app.services.workflow.runner import WorkflowRunner
from app.services.workflow.schema import (
    WorkflowDefinition,
    WorkflowValidationError,
    validate_definition,
)
from app.tools.base import ToolRegistry

router = APIRouter(prefix="/workflows", tags=["workflows"])
logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ChatContext = Annotated[AuthContext, Depends(require_scope("chat:write"))]
RedisDep = Annotated[RedisLike, Depends(get_redis)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_registry)]
ToolRegistryDep = Annotated[ToolRegistry, Depends(get_tool_registry)]
AgentRegistryDep = Annotated[AgentRegistry, Depends(get_agent_registry)]


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _invalid_workflow(exc: WorkflowValidationError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {
            "code": "invalid_workflow",
            "message": str(exc),
            "errors": exc.messages,
        },
    )


def _parse_definition(raw: object) -> WorkflowDefinition:
    try:
        return validate_definition(raw)
    except WorkflowValidationError as exc:
        raise _invalid_workflow(exc) from None


async def _get_owned_workflow(
    workflow_id: UUID, workspace_id: UUID, session: AsyncSession
) -> Workflow:
    workflow = (
        await session.execute(
            select(Workflow).where(
                Workflow.id == workflow_id,
                Workflow.workspace_id == workspace_id,
                Workflow.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow not found")
    return workflow


async def _versions(session: AsyncSession, workflow_id: UUID) -> list[WorkflowVersion]:
    result = await session.execute(
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version.desc())
    )
    return list(result.scalars())


def _workflow_out(workflow: Workflow, versions: list[WorkflowVersion]) -> WorkflowOut:
    return WorkflowOut(
        id=workflow.id,
        name=workflow.name,
        description=workflow.description,
        created_at=workflow.created_at,
        versions=[WorkflowVersionOut.model_validate(version) for version in versions],
    )


@router.get("", response_model=list[WorkflowOut])
async def list_workflows(
    context: Annotated[AuthContext, Depends(get_jwt_context)], session: SessionDep
) -> list[WorkflowOut]:
    workflows = (
        await session.execute(
            select(Workflow)
            .where(
                Workflow.workspace_id == context.workspace.id,
                Workflow.deleted_at.is_(None),
            )
            .order_by(Workflow.created_at.desc(), Workflow.id.desc())
        )
    ).scalars()
    return [
        _workflow_out(workflow, await _versions(session, workflow.id)) for workflow in workflows
    ]


@router.post("", response_model=WorkflowOut, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    payload: WorkflowCreate,
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
) -> WorkflowOut:
    definition = _parse_definition(payload.definition)
    workflow = Workflow(
        workspace_id=context.workspace.id,
        created_by=context.user.id,
        name=payload.name,
        description=payload.description,
    )
    session.add(workflow)
    await session.flush()
    version = WorkflowVersion(
        workflow_id=workflow.id,
        version=1,
        definition=definition.model_dump(by_alias=True),
    )
    session.add(version)
    await session.commit()
    await session.refresh(workflow)
    await session.refresh(version)
    return _workflow_out(workflow, [version])


@router.get("/runs/{run_id}", response_model=WorkflowRunOut)
async def get_workflow_run(
    run_id: UUID,
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
) -> WorkflowRunOut:
    run = (
        await session.execute(
            select(WorkflowRun).where(
                WorkflowRun.id == run_id,
                WorkflowRun.workspace_id == context.workspace.id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow run not found")
    nodes = (
        await session.execute(
            select(WorkflowNodeRun)
            .where(WorkflowNodeRun.run_id == run.id)
            .order_by(WorkflowNodeRun.created_at, WorkflowNodeRun.id)
        )
    ).scalars()
    return WorkflowRunOut(
        **WorkflowRunOut.model_validate(run).model_dump(exclude={"nodes"}),
        nodes=[WorkflowNodeRunOut.model_validate(node) for node in nodes],
    )


@router.get("/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(
    workflow_id: UUID,
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
) -> WorkflowOut:
    workflow = await _get_owned_workflow(workflow_id, context.workspace.id, session)
    return _workflow_out(workflow, await _versions(session, workflow.id))


@router.post(
    "/{workflow_id}/versions",
    response_model=WorkflowVersionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_workflow_version(
    workflow_id: UUID,
    payload: WorkflowVersionCreate,
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
) -> WorkflowVersionOut:
    workflow = await _get_owned_workflow(workflow_id, context.workspace.id, session)
    definition = _parse_definition(payload.definition)
    latest = (
        await session.execute(
            select(func.max(WorkflowVersion.version)).where(
                WorkflowVersion.workflow_id == workflow.id
            )
        )
    ).scalar_one()
    version = WorkflowVersion(
        workflow_id=workflow.id,
        version=(latest or 0) + 1,
        definition=definition.model_dump(by_alias=True),
    )
    session.add(version)
    await session.commit()
    await session.refresh(version)
    return WorkflowVersionOut.model_validate(version)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    workflow_id: UUID,
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
) -> Response:
    workflow = await _get_owned_workflow(workflow_id, context.workspace.id, session)
    workflow.deleted_at = datetime.now(UTC)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{workflow_id}/runs", response_model=list[WorkflowRunOut])
async def list_workflow_runs(
    workflow_id: UUID,
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: UUID | None = None,
) -> list[WorkflowRunOut]:
    workflow = await _get_owned_workflow(workflow_id, context.workspace.id, session)
    conditions = [
        WorkflowRun.workflow_id == workflow.id,
        WorkflowRun.workspace_id == context.workspace.id,
    ]
    if before is not None:
        conditions.append(WorkflowRun.id < before)
    runs = (
        await session.execute(
            select(WorkflowRun).where(*conditions).order_by(WorkflowRun.id.desc()).limit(limit)
        )
    ).scalars()
    return [WorkflowRunOut.model_validate(run) for run in runs]


@router.post("/{workflow_id}/runs")
async def create_workflow_run(
    workflow_id: UUID,
    payload: WorkflowRunCreate,
    context: ChatContext,
    session: SessionDep,
    registry: RegistryDep,
    tool_registry: ToolRegistryDep,
    agent_registry: AgentRegistryDep,
    redis: RedisDep,
) -> StreamingResponse:
    workflow = await _get_owned_workflow(workflow_id, context.workspace.id, session)
    version_statement = select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)
    if payload.version is None:
        version_statement = version_statement.order_by(WorkflowVersion.version.desc()).limit(1)
    else:
        version_statement = version_statement.where(WorkflowVersion.version == payload.version)
    version = (await session.execute(version_statement)).scalar_one_or_none()
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow version not found")
    if payload.kb_id is not None:
        await get_owned_knowledge_base(payload.kb_id, context.workspace.id, session)
    await enforce_quota(redis, context)

    definition = _parse_definition(version.definition)
    run = WorkflowRun(
        workflow_id=workflow.id,
        version_id=version.id,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        status="running",
        input_text=payload.input,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    run_id = run.id
    await session.close()

    runner = WorkflowRunner(
        run_id=run_id,
        workflow_id=workflow.id,
        version=version.version,
        definition=definition,
        provider_registry=registry,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        kb_id=payload.kb_id,
        redis=redis,
        input_text=payload.input,
        quota_guard=lambda: enforce_quota(redis, context),
    )

    async def stream():
        try:
            async for event in runner.run():
                yield _sse(event.kind, event.data)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("workflow stream failed for run %s", run_id)
            yield _sse(
                "workflow_end",
                {
                    "run_id": str(run_id),
                    "status": "failed",
                    "error_code": "internal_error",
                },
            )

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
