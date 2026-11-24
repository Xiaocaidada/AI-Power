import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import build_agent_registry
from app.clients import RedisLike, get_redis
from app.db import SessionLocal, get_session
from app.deps import (
    AuthContext,
    get_jwt_context,
    get_scoped_registry,
    require_scope,
)
from app.metrics import track_sse_stream
from app.models import (
    AuditLog,
    Document,
    Workflow,
    WorkflowNodeRun,
    WorkflowReview,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowVersion,
)
from app.providers.registry import ProviderRegistry
from app.schemas import (
    RunAcceptedOut,
    RunCancelOut,
    WorkflowCreate,
    WorkflowDraftIn,
    WorkflowDraftOut,
    WorkflowNodeDebugIn,
    WorkflowNodeDebugOut,
    WorkflowNodeRunOut,
    WorkflowOut,
    WorkflowRunCreate,
    WorkflowRunOut,
    WorkflowVersionCreate,
    WorkflowVersionOut,
)
from app.services.access import get_owned_knowledge_base
from app.services.knowledge.catalog import (
    build_knowledge_process_catalog,
    build_template,
)
from app.services.knowledge.retrieval_catalog import (
    build_knowledge_retrieval_catalog,
)
from app.services.knowledge.retrieval_schema import (
    RetrievalValidationError,
    validate_knowledge_retrieval,
)
from app.services.knowledge.schema import (
    KnowledgeValidationError,
    validate_knowledge_process,
)
from app.services.queue import JobQueue, get_queue
from app.services.quotas import enforce_quota
from app.services.run_events import (
    KEEPALIVE_SECONDS,
    PAUSED_STATUSES,
    POLL_INTERVAL_SECONDS,
    TERMINAL_EVENTS,
    TERMINAL_STATUSES,
    append_workflow_event,
    format_sse,
    list_workflow_events,
)
from app.services.workflow.catalog import build_node_catalog
from app.services.workflow.runner import NodeFailure, WorkflowRunner
from app.services.workflow.schema import (
    WorkflowDefinition,
    WorkflowValidationError,
    validate_definition,
)
from app.tools.registry import build_tool_registry

router = APIRouter(prefix="/workflows", tags=["workflows"])
logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ChatContext = Annotated[AuthContext, Depends(require_scope("chat:write"))]
RunContext = Annotated[AuthContext, Depends(require_scope("workflow:run"))]
RedisDep = Annotated[RedisLike, Depends(get_redis)]
QueueDep = Annotated[JobQueue, Depends(get_queue)]
ScopedRegistryDep = Annotated[ProviderRegistry, Depends(get_scoped_registry)]


def _invalid_workflow(exc: WorkflowValidationError) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {
            "code": "invalid_workflow",
            "message": str(exc),
            "errors": exc.messages,
        },
    )


def _parse_definition(raw: object, kind: str = "agent") -> WorkflowDefinition:
    if kind == "knowledge_process":
        try:
            definition = validate_knowledge_process(raw)
        except KnowledgeValidationError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {
                    "code": "invalid_workflow",
                    "message": str(exc),
                    "errors": exc.messages,
                },
            ) from None
        return WorkflowDefinition.model_construct(
            nodes=definition.nodes, edges=definition.edges
        )
    if kind == "knowledge_retrieval":
        try:
            retrieval = validate_knowledge_retrieval(raw)
        except RetrievalValidationError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {
                    "code": "invalid_workflow",
                    "message": str(exc),
                    "errors": exc.messages,
                },
            ) from None
        return WorkflowDefinition.model_construct(
            nodes=retrieval.nodes, edges=retrieval.edges
        )
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
        kind=workflow.kind,
        created_at=workflow.created_at,
        versions=[WorkflowVersionOut.model_validate(version) for version in versions],
        draft_definition=workflow.draft_definition,
        draft_saved_at=workflow.draft_saved_at,
    )


@router.get("", response_model=list[WorkflowOut])
async def list_workflows(
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
    kind: str | None = None,
) -> list[WorkflowOut]:
    statement = select(Workflow).where(
        Workflow.workspace_id == context.workspace.id,
        Workflow.deleted_at.is_(None),
    )
    if kind is not None:
        statement = statement.where(Workflow.kind == kind)
    workflows = (
        await session.execute(
            statement.order_by(Workflow.created_at.desc(), Workflow.id.desc())
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
    definition = _parse_definition(payload.definition, payload.kind)
    workflow = Workflow(
        workspace_id=context.workspace.id,
        created_by=context.user.id,
        name=payload.name,
        description=payload.description,
        kind=payload.kind,
    )
    session.add(workflow)
    await session.flush()
    version = WorkflowVersion(
        workflow_id=workflow.id,
        version=1,
        definition=definition.model_dump(by_alias=True),
    )
    session.add(version)
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="workflow.publish",
            target_type="workflow",
            target_id=str(workflow.id),
            detail={"version": 1, "name": workflow.name},
        )
    )
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


@router.get("/catalog")
async def get_workflow_catalog(
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    kind: str = "agent",
) -> dict[str, object]:
    if kind == "knowledge_process":
        catalog = build_knowledge_process_catalog()
        catalog["templates"] = [
            build_template(name) for name in ("general", "technical", "markdown")
        ]
        return catalog
    if kind == "knowledge_retrieval":
        return build_knowledge_retrieval_catalog()
    return build_node_catalog()


@router.get("/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(
    workflow_id: UUID,
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
) -> WorkflowOut:
    workflow = await _get_owned_workflow(workflow_id, context.workspace.id, session)
    return _workflow_out(workflow, await _versions(session, workflow.id))


def _draft_definition(payload: dict[str, object]) -> dict[str, object]:
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "invalid_draft", "message": "Draft needs nodes and edges lists"},
        )
    if len(nodes) > 200 or len(edges) > 400:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "invalid_draft", "message": "Draft is too large"},
        )
    return payload


@router.get(
    "/{workflow_id}/versions", response_model=list[WorkflowVersionOut]
)
async def list_workflow_versions(
    workflow_id: UUID,
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
) -> list[WorkflowVersionOut]:
    workflow = await _get_owned_workflow(workflow_id, context.workspace.id, session)
    return [
        WorkflowVersionOut.model_validate(version)
        for version in await _versions(session, workflow.id)
    ]


@router.post(
    "/{workflow_id}/versions/{version}/restore",
    response_model=WorkflowVersionOut,
    status_code=status.HTTP_201_CREATED,
)
async def restore_workflow_version(
    workflow_id: UUID,
    version: int,
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
) -> WorkflowVersionOut:
    workflow = await _get_owned_workflow(workflow_id, context.workspace.id, session)
    target = (
        await session.execute(
            select(WorkflowVersion).where(
                WorkflowVersion.workflow_id == workflow.id,
                WorkflowVersion.version == version,
            )
        )
    ).scalar_one_or_none()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow version not found")
    latest = (
        await session.execute(
            select(func.max(WorkflowVersion.version)).where(
                WorkflowVersion.workflow_id == workflow.id
            )
        )
    ).scalar_one()
    restored = WorkflowVersion(
        workflow_id=workflow.id,
        version=(latest or 0) + 1,
        schema_version=target.schema_version,
        definition=target.definition,
    )
    session.add(restored)
    workflow.draft_definition = None
    workflow.draft_saved_at = None
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="workflow.restore",
            target_type="workflow",
            target_id=str(workflow.id),
            detail={"restored_version": version, "new_version": restored.version},
        )
    )
    await session.commit()
    await session.refresh(restored)
    return WorkflowVersionOut.model_validate(restored)


@router.get("/{workflow_id}/draft", response_model=WorkflowDraftOut)
async def get_workflow_draft(
    workflow_id: UUID,
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
) -> WorkflowDraftOut:
    workflow = await _get_owned_workflow(workflow_id, context.workspace.id, session)
    return WorkflowDraftOut(
        definition=workflow.draft_definition,
        saved_at=workflow.draft_saved_at,
    )


@router.put("/{workflow_id}/draft", response_model=WorkflowDraftOut)
async def save_workflow_draft(
    workflow_id: UUID,
    payload: WorkflowDraftIn,
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
) -> WorkflowDraftOut:
    workflow = await _get_owned_workflow(workflow_id, context.workspace.id, session)
    workflow.draft_definition = _draft_definition(payload.definition)
    workflow.draft_saved_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(workflow)
    return WorkflowDraftOut(
        definition=workflow.draft_definition,
        saved_at=workflow.draft_saved_at,
    )


@router.delete("/{workflow_id}/draft", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow_draft(
    workflow_id: UUID,
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
) -> Response:
    workflow = await _get_owned_workflow(workflow_id, context.workspace.id, session)
    workflow.draft_definition = None
    workflow.draft_saved_at = None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    definition = _parse_definition(payload.definition, workflow.kind)
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
    workflow.draft_definition = None
    workflow.draft_saved_at = None
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="workflow.publish",
            target_type="workflow",
            target_id=str(workflow.id),
            detail={"version": version.version, "name": workflow.name},
        )
    )
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


async def _get_owned_run(run_id: UUID, workspace_id: UUID, session: AsyncSession) -> WorkflowRun:
    run = (
        await session.execute(
            select(WorkflowRun).where(
                WorkflowRun.id == run_id,
                WorkflowRun.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow run not found")
    return run


def _resume_cursor(after: int | None, last_event_id: str | None) -> int:
    if after is not None:
        return after
    if last_event_id is not None:
        try:
            return max(int(last_event_id), 0)
        except ValueError:
            return 0
    return 0


@router.post("/{workflow_id}/runs", response_model=RunAcceptedOut, status_code=202)
async def create_workflow_run(
    workflow_id: UUID,
    payload: WorkflowRunCreate,
    context: RunContext,
    session: SessionDep,
    queue: QueueDep,
    redis: RedisDep,
) -> RunAcceptedOut:
    workflow = await _get_owned_workflow(workflow_id, context.workspace.id, session)
    version_statement = select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)
    if payload.version is None:
        version_statement = version_statement.order_by(WorkflowVersion.version.desc()).limit(1)
    else:
        version_statement = version_statement.where(WorkflowVersion.version == payload.version)
    version = (await session.execute(version_statement)).scalar_one_or_none()
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow version not found")
    is_knowledge = workflow.kind == "knowledge_process"
    input_payload: dict[str, object] = {}
    input_text = payload.input.strip()
    kb_id = payload.kb_id
    if workflow.kind == "knowledge_retrieval":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "retrieval_workflow_not_runnable",
                "message": "Use the knowledge base retrieval test endpoint",
            },
        )
    if is_knowledge:
        if payload.start_node_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {
                    "code": "start_node_not_supported",
                    "message": "Start-node runs are only available for agent workflows",
                },
            )
        if payload.document_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "document_required", "message": "document_id is required"},
            )
        document = (
            await session.execute(
                select(Document).where(
                    Document.id == payload.document_id,
                    Document.workspace_id == context.workspace.id,
                    Document.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if document is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
        if kb_id is not None and kb_id != document.kb_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {
                    "code": "document_kb_mismatch",
                    "message": "Document belongs to another knowledge base",
                },
            )
        kb_id = document.kb_id
        input_text = document.filename
        input_payload = {"document_id": str(document.id)}
        _parse_definition(version.definition, "knowledge_process")
    else:
        if not input_text and payload.start_node_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "input_required", "message": "input is required"},
            )
        definition = _parse_definition(version.definition, workflow.kind)
        if payload.start_node_id is not None:
            if definition.node_map().get(payload.start_node_id) is None:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    {"code": "node_not_found", "message": "Start node not found"},
                )
            input_payload["start_node_id"] = payload.start_node_id
            if payload.node_outputs:
                input_payload["node_outputs"] = payload.node_outputs
    if kb_id is not None:
        await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    await enforce_quota(redis, context)

    run = WorkflowRun(
        workflow_id=workflow.id,
        version_id=version.id,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        api_key_id=context.api_key_id,
        kb_id=kb_id,
        status="queued",
        input_text=input_text,
        input_payload=input_payload,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    run_id = run.id
    try:
        await queue.enqueue_workflow_run(run_id)
    except Exception:
        logger.exception("failed to enqueue workflow run %s", run_id)
        run.status = "failed"
        run.error_code = "queue_unavailable"
        run.finished_at = datetime.now(UTC)
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": "queue_unavailable", "message": "Workflow queue is unavailable"},
        ) from None
    return RunAcceptedOut(run_id=run_id, status="queued")


@router.post(
    "/{workflow_id}/nodes/{node_id}/debug",
    response_model=WorkflowNodeDebugOut,
)
async def debug_workflow_node(
    workflow_id: UUID,
    node_id: str,
    payload: WorkflowNodeDebugIn,
    context: RunContext,
    session: SessionDep,
    redis: RedisDep,
    registry: ScopedRegistryDep,
) -> WorkflowNodeDebugOut:
    workflow = await _get_owned_workflow(workflow_id, context.workspace.id, session)
    if workflow.kind != "agent":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "node_debug_not_supported",
                "message": "Single-node debug is only available for agent workflows",
            },
        )
    version_statement = select(WorkflowVersion).where(
        WorkflowVersion.workflow_id == workflow.id
    )
    if payload.version is None:
        version_statement = version_statement.order_by(
            WorkflowVersion.version.desc()
        ).limit(1)
    else:
        version_statement = version_statement.where(
            WorkflowVersion.version == payload.version
        )
    version = (await session.execute(version_statement)).scalar_one_or_none()
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow version not found")
    definition = _parse_definition(version.definition, "agent")
    node = definition.node_map().get(node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow node not found")
    if node.type == "review":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "review_node_requires_run",
                "message": "Review nodes need a queued run and human reviewer",
            },
        )
    await enforce_quota(redis, context)
    run = WorkflowRun(
        workflow_id=workflow.id,
        version_id=version.id,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        api_key_id=context.api_key_id,
        status="running",
        input_text=payload.input,
        input_payload={"debug_node": node_id},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    runner = WorkflowRunner(
        run_id=run.id,
        workflow_id=workflow.id,
        version=version.version,
        definition=definition,
        provider_registry=registry,
        tool_registry=build_tool_registry(),
        agent_registry=build_agent_registry(),
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        kb_id=None,
        redis=redis,
        input_text=payload.input,
        quota_guard=lambda: enforce_quota(redis, context),
        api_key_id=context.api_key_id,
        start_node_id=node_id,
        seed_outputs=payload.node_outputs,
    )
    try:
        outcome = await runner.debug_node(node_id)
    except NodeFailure as exc:
        run.status = "failed"
        run.error_code = exc.code
        run.finished_at = datetime.now(UTC)
        await session.commit()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": exc.code, "message": exc.message},
        ) from None
    run.status = "completed" if outcome.status == "completed" else "failed"
    run.error_code = outcome.error_code
    run.total_ms = outcome.duration_ms
    run.finished_at = datetime.now(UTC)
    await session.commit()
    node_run = (
        await session.execute(
            select(WorkflowNodeRun)
            .where(
                WorkflowNodeRun.run_id == run.id,
                WorkflowNodeRun.node_id == node_id,
            )
            .order_by(WorkflowNodeRun.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return WorkflowNodeDebugOut(
        run_id=run.id,
        node_id=node_id,
        node_type=node.type,
        status=outcome.status,
        output=outcome.output,
        input_summary=outcome.input_summary,
        error_code=outcome.error_code,
        duration_ms=outcome.duration_ms,
        node_run_id=node_run.id if node_run is not None else None,
    )


@router.get("/runs/{run_id}/events")
async def workflow_run_events(
    run_id: UUID,
    context: RunContext,
    session: SessionDep,
    after: Annotated[int | None, Query(ge=0)] = None,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    await _get_owned_run(run_id, context.workspace.id, session)
    cursor = _resume_cursor(after, last_event_id)

    async def stream():
        position = cursor
        last_ping = time.monotonic()
        missing_terminal_polls = 0
        while True:
            async with SessionLocal() as poll:
                run = await poll.get(WorkflowRun, run_id)
                if run is None:
                    return
                events = await list_workflow_events(poll, run_id, position)
                terminal_rows = (
                    await poll.execute(
                        select(func.count())
                        .select_from(WorkflowRunEvent)
                        .where(
                            WorkflowRunEvent.run_id == run_id,
                            WorkflowRunEvent.event.in_(TERMINAL_EVENTS),
                        )
                    )
                ).scalar_one()
            terminal_seen = False
            for event in events:
                yield format_sse(event)
                position = event.seq
                if event.event in TERMINAL_EVENTS:
                    terminal_seen = True
            if run.status in PAUSED_STATUSES:
                return
            if run.status in TERMINAL_STATUSES:
                if not terminal_seen and terminal_rows == 0:
                    missing_terminal_polls += 1
                    if missing_terminal_polls < 2:
                        await asyncio.sleep(POLL_INTERVAL_SECONDS)
                        continue
                    payload = {
                        "run_id": str(run.id),
                        "status": run.status,
                        "error_code": run.error_code,
                        "total_ms": run.total_ms,
                        "prompt_tokens": run.prompt_tokens,
                        "completion_tokens": run.completion_tokens,
                        "cost": run.cost,
                    }
                    yield (
                        f"event: workflow_end\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    )
                return
            missing_terminal_polls = 0
            now = time.monotonic()
            if now - last_ping >= KEEPALIVE_SECONDS:
                yield ": keepalive\n\n"
                last_ping = now
            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    return StreamingResponse(
        track_sse_stream(stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/runs/{run_id}/cancel", response_model=RunCancelOut)
async def cancel_workflow_run(
    run_id: UUID,
    context: RunContext,
    session: SessionDep,
) -> RunCancelOut:
    run = await _get_owned_run(run_id, context.workspace.id, session)
    if run.status == "waiting_review":
        now = datetime.now(UTC)
        run.status = "cancelled"
        run.error_code = "cancelled"
        run.finished_at = now
        run.paused_at = None
        run.checkpoint = {}
        await session.execute(
            update(WorkflowReview)
            .where(
                WorkflowReview.run_id == run_id,
                WorkflowReview.status == "pending",
            )
            .values(status="cancelled", decision="cancelled", resolved_at=now)
        )
        await session.commit()
        try:
            await append_workflow_event(
                run_id,
                "workflow_end",
                {"run_id": str(run_id), "status": "cancelled", "error_code": "cancelled"},
            )
        except Exception:
            logger.exception("failed to append workflow cancel event %s", run_id)
        await session.refresh(run)
        return RunCancelOut(
            run_id=run.id,
            status=run.status,
            cancel_requested_at=run.cancel_requested_at,
        )
    if run.status not in TERMINAL_STATUSES:
        now = datetime.now(UTC)
        cancelled = await session.execute(
            update(WorkflowRun)
            .where(
                WorkflowRun.id == run_id,
                WorkflowRun.workspace_id == context.workspace.id,
                WorkflowRun.status == "queued",
            )
            .values(status="cancelled", error_code="cancelled", finished_at=now)
        )
        await session.commit()
        if cancelled.rowcount == 1:
            try:
                await append_workflow_event(
                    run_id,
                    "workflow_end",
                    {"run_id": str(run_id), "status": "cancelled", "error_code": "cancelled"},
                )
            except Exception:
                logger.exception("failed to append workflow cancel event %s", run_id)
        else:
            await session.execute(
                update(WorkflowRun)
                .where(
                    WorkflowRun.id == run_id,
                    WorkflowRun.workspace_id == context.workspace.id,
                    WorkflowRun.status == "running",
                )
                .values(cancel_requested_at=now)
            )
            await session.commit()
        await session.refresh(run)
    return RunCancelOut(
        run_id=run.id,
        status=run.status,
        cancel_requested_at=run.cancel_requested_at,
    )
