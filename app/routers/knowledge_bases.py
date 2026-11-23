from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, get_registry, require_scope
from app.models import (
    Chunk,
    Document,
    EvalRun,
    KnowledgeBase,
    KnowledgeChunkDraft,
    KnowledgeOptimization,
    Workflow,
    WorkflowArtifact,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowVersion,
)
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas import (
    ChunkOut,
    ChunkPageOut,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBaseSettingsOut,
    KnowledgeBaseSettingsUpdate,
    KnowledgeBaseStatsOut,
    KnowledgeBaseUpdate,
    KnowledgeOptimizationCreate,
    KnowledgeOptimizationDetailOut,
    KnowledgeOptimizationOut,
    KnowledgeProcessApplyOut,
    KnowledgeProcessArtifactOut,
    KnowledgeProcessBindingIn,
    KnowledgeProcessBindingOut,
    KnowledgeProcessPreviewOut,
    KnowledgeRetrievalTestIn,
    KnowledgeRetrievalTestOut,
    RetrievalHitOut,
    RetrievalSearchIn,
    RetrievalSearchOut,
    RetrievalTimingsOut,
    WorkflowNodeRunOut,
    WorkflowRunOut,
)
from app.services.access import get_owned_knowledge_base
from app.services.knowledge.apply import (
    KnowledgeApplyError,
    apply_knowledge_run,
    draft_preview,
    run_document_id,
)
from app.services.knowledge.optimizer import (
    KnowledgeOptimizerError,
    apply_optimization,
    dismiss_optimization,
    generate_optimization,
    get_optimization,
    list_optimizations,
    rollback_optimization,
)
from app.services.knowledge.retrieval_pipeline import (
    RetrievalWorkflowError,
    run_retrieval_workflow,
)
from app.services.knowledge.retrieval_schema import validate_knowledge_retrieval
from app.services.knowledge_settings import KnowledgeBaseSettings, resolve_kb_settings
from app.services.quotas import enforce_knowledge_base_creation
from app.services.rag import fit_context
from app.services.retrieval import build_citations, retrieve_with_diagnostics

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
ReadContext = Annotated[AuthContext, Depends(require_scope("kb:read"))]
RegistryDep = Annotated[ProviderRegistry, Depends(get_registry)]


@router.post("", response_model=KnowledgeBaseOut, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate, context: JwtContext, session: SessionDep
) -> KnowledgeBase:
    await enforce_knowledge_base_creation(session, context)
    kb = KnowledgeBase(
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        name=payload.name,
        description=payload.description,
    )
    session.add(kb)
    await session.commit()
    await session.refresh(kb)
    return kb


@router.get("", response_model=list[KnowledgeBaseOut])
async def list_knowledge_bases(context: ReadContext, session: SessionDep) -> list[KnowledgeBase]:
    result = await session.execute(
        select(KnowledgeBase)
        .where(
            KnowledgeBase.workspace_id == context.workspace.id,
            KnowledgeBase.deleted_at.is_(None),
        )
        .order_by(KnowledgeBase.created_at.desc())
    )
    return list(result.scalars())


@router.get("/{kb_id}", response_model=KnowledgeBaseOut)
async def get_knowledge_base(
    kb_id: UUID, context: ReadContext, session: SessionDep
) -> KnowledgeBase:
    return await get_owned_knowledge_base(kb_id, context.workspace.id, session)


@router.patch("/{kb_id}", response_model=KnowledgeBaseOut)
async def update_knowledge_base(
    kb_id: UUID,
    payload: KnowledgeBaseUpdate,
    context: JwtContext,
    session: SessionDep,
) -> KnowledgeBase:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        kb.name = str(data["name"])
    if "description" in data:
        kb.description = str(data["description"] or "")
    await session.commit()
    await session.refresh(kb)
    return kb


@router.get("/{kb_id}/settings", response_model=KnowledgeBaseSettingsOut)
async def get_knowledge_base_settings(
    kb_id: UUID, context: ReadContext, session: SessionDep
) -> KnowledgeBaseSettingsOut:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    return KnowledgeBaseSettingsOut(**resolve_kb_settings(kb).model_dump())


@router.patch("/{kb_id}/settings", response_model=KnowledgeBaseSettingsOut)
async def update_knowledge_base_settings(
    kb_id: UUID,
    payload: KnowledgeBaseSettingsUpdate,
    context: JwtContext,
    session: SessionDep,
) -> KnowledgeBaseSettingsOut:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    current = resolve_kb_settings(kb).model_dump(mode="json")
    updates = payload.model_dump(exclude_unset=True, mode="json")
    for section in ("chunking", "retrieval", "embedding", "rerank"):
        section_updates = updates.get(section)
        if isinstance(section_updates, dict):
            for key, value in section_updates.items():
                if value is not None or section in {"embedding", "rerank"}:
                    current[section][key] = value
    try:
        settings = KnowledgeBaseSettings.model_validate(current)
    except ValidationError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "invalid_settings", "message": "Invalid knowledge base settings"},
        ) from None
    kb.settings = settings.model_dump(mode="json")
    await session.commit()
    return KnowledgeBaseSettingsOut(**settings.model_dump())


@router.get("/{kb_id}/chunks", response_model=ChunkPageOut)
async def list_chunks(
    kb_id: UUID,
    context: ReadContext,
    session: SessionDep,
    document_id: UUID | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChunkPageOut:
    await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    conditions = [
        Chunk.workspace_id == context.workspace.id,
        Chunk.kb_id == kb_id,
        Document.deleted_at.is_(None),
    ]
    if document_id is not None:
        conditions.append(Chunk.document_id == document_id)
    if q is not None and q.strip():
        conditions.append(Chunk.text.contains(q.strip(), autoescape=True))

    total = (
        await session.execute(
            select(func.count())
            .select_from(Chunk)
            .join(Document, Document.id == Chunk.document_id)
            .where(*conditions)
        )
    ).scalar_one()
    rows = (
        await session.execute(
            select(Chunk, Document.filename)
            .join(Document, Document.id == Chunk.document_id)
            .where(*conditions)
            .order_by(Chunk.document_id.desc(), Chunk.chunk_index, Chunk.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    items = [
        ChunkOut(
            id=chunk.id,
            document_id=chunk.document_id,
            filename=filename,
            chunk_index=chunk.chunk_index,
            page_no=chunk.page_no,
            text=chunk.text,
            token_count=chunk.token_count,
            char_count=len(chunk.text),
            created_at=chunk.created_at,
        )
        for chunk, filename in rows
    ]
    return ChunkPageOut(items=items, total=total, limit=limit, offset=offset)


@router.get("/{kb_id}/stats", response_model=KnowledgeBaseStatsOut)
async def get_knowledge_base_stats(
    kb_id: UUID, context: ReadContext, session: SessionDep
) -> KnowledgeBaseStatsOut:
    await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    document_conditions = (
        Document.workspace_id == context.workspace.id,
        Document.kb_id == kb_id,
        Document.deleted_at.is_(None),
    )

    async def count_documents(*extra) -> int:
        return (
            await session.execute(
                select(func.count()).select_from(Document).where(*document_conditions, *extra)
            )
        ).scalar_one()

    document_count = await count_documents()
    ready_count = await count_documents(Document.status == "ready")
    processing_count = await count_documents(
        Document.status.in_(("uploaded", "parsing", "embedding"))
    )
    failed_count = await count_documents(Document.status == "failed")
    chunk_count = (
        await session.execute(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.workspace_id == context.workspace.id, Chunk.kb_id == kb_id)
        )
    ).scalar_one()
    char_count = (
        await session.execute(
            select(func.coalesce(func.sum(func.length(Chunk.text)), 0)).where(
                Chunk.workspace_id == context.workspace.id, Chunk.kb_id == kb_id
            )
        )
    ).scalar_one()
    return KnowledgeBaseStatsOut(
        document_count=document_count,
        ready_count=ready_count,
        processing_count=processing_count,
        failed_count=failed_count,
        chunk_count=chunk_count,
        char_count=int(char_count),
    )


@router.post("/{kb_id}/retrieval/search", response_model=RetrievalSearchOut)
async def search_knowledge_base(
    kb_id: UUID,
    payload: RetrievalSearchIn,
    context: JwtContext,
    session: SessionDep,
) -> RetrievalSearchOut:
    await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    try:
        outcome = await retrieve_with_diagnostics(
            session,
            workspace_id=context.workspace.id,
            kb_id=kb_id,
            query=payload.query,
            top_k=payload.top_k,
            candidate_k=payload.candidate_k,
            hybrid_enabled=payload.hybrid_enabled,
            rerank_enabled=payload.rerank_enabled,
        )
    except ProviderError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            {"code": "retrieval_failed", "message": "Retrieval failed"},
        ) from None
    return RetrievalSearchOut(
        query=payload.query,
        mode=outcome.mode,
        hybrid_enabled=outcome.options.hybrid_enabled,
        rerank_enabled=outcome.options.rerank_enabled,
        results=[
            RetrievalHitOut(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                filename=chunk.filename,
                page_no=chunk.page_no,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                distance=chunk.distance,
                vector_rank=chunk.vector_rank,
                lexical_rank=chunk.lexical_rank,
                fused_score=chunk.fused_score,
                rerank_score=chunk.rerank_score,
            )
            for chunk in outcome.chunks
        ],
        timings=RetrievalTimingsOut(**outcome.timings),
    )


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_base(kb_id: UUID, context: JwtContext, session: SessionDep) -> Response:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    kb.deleted_at = datetime.now(UTC)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{kb_id}/processing/binding", response_model=KnowledgeProcessBindingOut
)
async def get_processing_binding(
    kb_id: UUID, context: JwtContext, session: SessionDep
) -> KnowledgeProcessBindingOut:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    if kb.process_workflow_version_id is None:
        return KnowledgeProcessBindingOut()
    version = await session.get(WorkflowVersion, kb.process_workflow_version_id)
    if version is None:
        return KnowledgeProcessBindingOut()
    workflow = await session.get(Workflow, version.workflow_id)
    return KnowledgeProcessBindingOut(
        workflow_version_id=version.id,
        workflow_id=version.workflow_id,
        version=version.version,
        kind=workflow.kind if workflow is not None else "knowledge_process",
        name=workflow.name if workflow is not None else "",
    )


@router.put(
    "/{kb_id}/processing/binding", response_model=KnowledgeProcessBindingOut
)
async def bind_processing_workflow(
    kb_id: UUID,
    payload: KnowledgeProcessBindingIn,
    context: JwtContext,
    session: SessionDep,
) -> KnowledgeProcessBindingOut:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    if payload.workflow_version_id is None:
        kb.process_workflow_version_id = None
        await session.commit()
        return KnowledgeProcessBindingOut()
    version = await session.get(WorkflowVersion, payload.workflow_version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow version not found")
    workflow = await session.get(Workflow, version.workflow_id)
    if (
        workflow is None
        or workflow.workspace_id != context.workspace.id
        or workflow.deleted_at is not None
        or workflow.kind != "knowledge_process"
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "invalid_workflow", "message": "Not a knowledge processing workflow"},
        )
    kb.process_workflow_version_id = version.id
    await session.commit()
    return KnowledgeProcessBindingOut(
        workflow_version_id=version.id,
        workflow_id=workflow.id,
        version=version.version,
        kind=workflow.kind,
        name=workflow.name,
    )


@router.get("/{kb_id}/processing/runs", response_model=list[WorkflowRunOut])
async def list_processing_runs(
    kb_id: UUID,
    context: JwtContext,
    session: SessionDep,
    document_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[WorkflowRunOut]:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    statement = (
        select(WorkflowRun)
        .join(Workflow, Workflow.id == WorkflowRun.workflow_id)
        .where(
            WorkflowRun.kb_id == kb.id,
            WorkflowRun.workspace_id == context.workspace.id,
            Workflow.kind == "knowledge_process",
        )
        .order_by(WorkflowRun.id.desc())
        .limit(limit)
    )
    if document_id is not None:
        statement = statement.where(
            WorkflowRun.input_payload["document_id"].as_string() == str(document_id)
        )
    runs = list((await session.execute(statement)).scalars())
    return [WorkflowRunOut.model_validate(run) for run in runs]


@router.get(
    "/{kb_id}/processing/runs/{run_id}/preview",
    response_model=KnowledgeProcessPreviewOut,
)
async def preview_processing_run(
    kb_id: UUID, run_id: UUID, context: JwtContext, session: SessionDep
) -> KnowledgeProcessPreviewOut:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    run = (
        await session.execute(
            select(WorkflowRun).where(
                WorkflowRun.id == run_id,
                WorkflowRun.kb_id == kb.id,
                WorkflowRun.workspace_id == context.workspace.id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    nodes = list(
        (
            await session.execute(
                select(WorkflowNodeRun)
                .where(WorkflowNodeRun.run_id == run.id)
                .order_by(WorkflowNodeRun.created_at, WorkflowNodeRun.id)
            )
        ).scalars()
    )
    artifacts = list(
        (
            await session.execute(
                select(WorkflowArtifact)
                .where(WorkflowArtifact.run_id == run.id)
                .order_by(WorkflowArtifact.created_at)
            )
        ).scalars()
    )
    drafts = list(
        (
            await session.execute(
                select(KnowledgeChunkDraft)
                .where(KnowledgeChunkDraft.run_id == run.id)
                .order_by(KnowledgeChunkDraft.chunk_index)
            )
        ).scalars()
    )
    return KnowledgeProcessPreviewOut(
        run=WorkflowRunOut(
            **WorkflowRunOut.model_validate(run).model_dump(exclude={"nodes"}),
            nodes=[WorkflowNodeRunOut.model_validate(node) for node in nodes],
        ),
        artifacts=[
            KnowledgeProcessArtifactOut(
                node_id=artifact.node_id,
                kind=artifact.kind,
                payload=artifact.payload or {},
            )
            for artifact in artifacts
        ],
        drafts=draft_preview(drafts, limit=50),
        draft_count=len(drafts),
        applied=run.applied_at is not None,
    )


@router.post(
    "/{kb_id}/processing/runs/{run_id}/apply",
    response_model=KnowledgeProcessApplyOut,
)
async def apply_processing_run(
    kb_id: UUID, run_id: UUID, context: JwtContext, session: SessionDep
) -> KnowledgeProcessApplyOut:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    run = (
        await session.execute(
            select(WorkflowRun).where(
                WorkflowRun.id == run_id,
                WorkflowRun.kb_id == kb.id,
                WorkflowRun.workspace_id == context.workspace.id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    document_id = run_document_id(run)
    if document_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "document_missing", "message": "Run has no document"},
        )
    document = await session.get(Document, document_id)
    if document is None or document.kb_id != kb.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    try:
        result = await apply_knowledge_run(session, run, document)
    except KnowledgeApplyError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": exc.code, "message": exc.message},
        ) from None
    return KnowledgeProcessApplyOut(
        document_id=document.id,
        chunks=result["chunks"],
        applied_at=run.applied_at or datetime.now(UTC),
    )


@router.get(
    "/{kb_id}/retrieval/binding", response_model=KnowledgeProcessBindingOut
)
async def get_retrieval_binding(
    kb_id: UUID, context: JwtContext, session: SessionDep
) -> KnowledgeProcessBindingOut:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    if kb.retrieval_workflow_version_id is None:
        return KnowledgeProcessBindingOut(kind="knowledge_retrieval")
    version = await session.get(WorkflowVersion, kb.retrieval_workflow_version_id)
    if version is None:
        return KnowledgeProcessBindingOut(kind="knowledge_retrieval")
    workflow = await session.get(Workflow, version.workflow_id)
    return KnowledgeProcessBindingOut(
        workflow_version_id=version.id,
        workflow_id=version.workflow_id,
        version=version.version,
        kind="knowledge_retrieval",
        name=workflow.name if workflow is not None else "",
    )


@router.put(
    "/{kb_id}/retrieval/binding", response_model=KnowledgeProcessBindingOut
)
async def bind_retrieval_workflow(
    kb_id: UUID,
    payload: KnowledgeProcessBindingIn,
    context: JwtContext,
    session: SessionDep,
) -> KnowledgeProcessBindingOut:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    if payload.workflow_version_id is None:
        kb.retrieval_workflow_version_id = None
        await session.commit()
        return KnowledgeProcessBindingOut(kind="knowledge_retrieval")
    version = await session.get(WorkflowVersion, payload.workflow_version_id)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Workflow version not found")
    workflow = await session.get(Workflow, version.workflow_id)
    if (
        workflow is None
        or workflow.workspace_id != context.workspace.id
        or workflow.deleted_at is not None
        or workflow.kind != "knowledge_retrieval"
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "invalid_workflow", "message": "Not a knowledge retrieval workflow"},
        )
    kb.retrieval_workflow_version_id = version.id
    await session.commit()
    return KnowledgeProcessBindingOut(
        workflow_version_id=version.id,
        workflow_id=workflow.id,
        version=version.version,
        kind="knowledge_retrieval",
        name=workflow.name,
    )


@router.post(
    "/{kb_id}/retrieval/test", response_model=KnowledgeRetrievalTestOut
)
async def test_retrieval_workflow(
    kb_id: UUID,
    payload: KnowledgeRetrievalTestIn,
    context: JwtContext,
    session: SessionDep,
) -> KnowledgeRetrievalTestOut:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    version_id = payload.workflow_version_id or kb.retrieval_workflow_version_id
    if version_id is not None:
        version = await session.get(WorkflowVersion, version_id)
        workflow = await session.get(Workflow, version.workflow_id) if version else None
        if (
            version is None
            or workflow is None
            or workflow.workspace_id != context.workspace.id
            or workflow.kind != "knowledge_retrieval"
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "invalid_workflow", "message": "Retrieval workflow not found"},
            )
        try:
            definition = validate_knowledge_retrieval(version.definition)
            result = await run_retrieval_workflow(
                session,
                definition=definition,
                workspace_id=context.workspace.id,
                kb_ids=[kb.id],
                query=payload.query,
                user_id=context.user.id,
                collect_traces=True,
            )
        except RetrievalWorkflowError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                {"code": exc.code, "message": exc.message},
            ) from None
        return KnowledgeRetrievalTestOut(
            query=payload.query,
            rewritten_query=result.rewritten_query,
            mode=result.mode,
            context=result.context,
            results=[_retrieval_hit(chunk) for chunk in result.selected],
            citations=[
                {
                    "index": citation.index,
                    "document_id": str(citation.document_id),
                    "chunk_id": str(citation.chunk_id),
                    "page_no": citation.page_no,
                    "snippet": citation.snippet,
                }
                for citation in result.citations
            ],
            nodes=[
                {
                    "node_id": trace.node_id,
                    "node_type": trace.node_type,
                    "status": trace.status,
                    "duration_ms": trace.duration_ms,
                    "count": trace.count,
                    "error_code": trace.error_code,
                }
                for trace in result.traces
            ],
            timings={"total_ms": sum(trace.duration_ms for trace in result.traces)},
        )

    outcome = await retrieve_with_diagnostics(
        session,
        workspace_id=context.workspace.id,
        kb_id=kb.id,
        query=payload.query,
        top_k=payload.top_k,
    )
    selected = fit_context(outcome.chunks, resolve_kb_settings(kb).retrieval.top_k * 1200)
    citations = build_citations(selected)
    return KnowledgeRetrievalTestOut(
        query=payload.query,
        mode=outcome.mode,
        context="\n\n".join(
            f"[{index}] {chunk.text}"
            for index, chunk in enumerate(selected, start=1)
        ),
        results=[_retrieval_hit(chunk) for chunk in outcome.chunks],
        citations=[
            {
                "index": citation.index,
                "document_id": str(citation.document_id),
                "chunk_id": str(citation.chunk_id),
                "page_no": citation.page_no,
                "snippet": citation.snippet,
            }
            for citation in citations
        ],
        timings=outcome.timings,
    )


def _retrieval_hit(chunk) -> RetrievalHitOut:
    return RetrievalHitOut(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        filename=chunk.filename,
        page_no=chunk.page_no,
        chunk_index=chunk.chunk_index,
        text=chunk.text,
        distance=chunk.distance,
        vector_rank=chunk.vector_rank,
        lexical_rank=chunk.lexical_rank,
        fused_score=chunk.fused_score,
        rerank_score=chunk.rerank_score,
    )


OPTIMIZER_STATUS_CODES = {
    "run_not_found": status.HTTP_404_NOT_FOUND,
    "not_found": status.HTTP_404_NOT_FOUND,
    "provider_not_found": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "invalid_retrieval_workflow": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "invalid_definition": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "invalid_workflow": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "no_definition": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "run_not_completed": status.HTTP_409_CONFLICT,
    "invalid_status": status.HTTP_409_CONFLICT,
    "binding_changed": status.HTTP_409_CONFLICT,
}


def _raise_optimizer_error(exc: KnowledgeOptimizerError) -> None:
    raise HTTPException(
        OPTIMIZER_STATUS_CODES.get(exc.code, status.HTTP_502_BAD_GATEWAY),
        {"code": exc.code, "message": exc.message},
    ) from None


def _optimization_detail(
    row: KnowledgeOptimization,
) -> KnowledgeOptimizationDetailOut:
    return KnowledgeOptimizationDetailOut.model_validate(row)


@router.post(
    "/{kb_id}/optimizations",
    response_model=KnowledgeOptimizationDetailOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_kb_optimization(
    kb_id: UUID,
    payload: KnowledgeOptimizationCreate,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
) -> KnowledgeOptimizationDetailOut:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    run = await session.get(EvalRun, payload.eval_run_id)
    if (
        run is None
        or run.workspace_id != context.workspace.id
        or run.kb_id != kb.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evaluation run not found")
    try:
        row = await generate_optimization(
            session,
            registry,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            kb=kb,
            run=run,
            provider_id=payload.provider_id,
            model=payload.model,
        )
    except KnowledgeOptimizerError as exc:
        _raise_optimizer_error(exc)
    return _optimization_detail(row)


@router.get(
    "/{kb_id}/optimizations", response_model=list[KnowledgeOptimizationOut]
)
async def list_kb_optimizations(
    kb_id: UUID,
    context: JwtContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[KnowledgeOptimizationOut]:
    await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    rows = await list_optimizations(
        session, workspace_id=context.workspace.id, kb_id=kb_id, limit=limit
    )
    return [KnowledgeOptimizationOut.model_validate(row) for row in rows]


@router.get(
    "/{kb_id}/optimizations/{optimization_id}",
    response_model=KnowledgeOptimizationDetailOut,
)
async def get_kb_optimization(
    kb_id: UUID,
    optimization_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> KnowledgeOptimizationDetailOut:
    await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    try:
        row = await get_optimization(
            session,
            workspace_id=context.workspace.id,
            kb_id=kb_id,
            optimization_id=optimization_id,
        )
    except KnowledgeOptimizerError as exc:
        _raise_optimizer_error(exc)
    return _optimization_detail(row)


@router.post(
    "/{kb_id}/optimizations/{optimization_id}/apply",
    response_model=KnowledgeOptimizationDetailOut,
)
async def apply_kb_optimization(
    kb_id: UUID,
    optimization_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> KnowledgeOptimizationDetailOut:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    try:
        row = await get_optimization(
            session,
            workspace_id=context.workspace.id,
            kb_id=kb_id,
            optimization_id=optimization_id,
        )
        await apply_optimization(
            session, optimization=row, kb=kb, user_id=context.user.id
        )
    except KnowledgeOptimizerError as exc:
        _raise_optimizer_error(exc)
    return _optimization_detail(row)


@router.post(
    "/{kb_id}/optimizations/{optimization_id}/rollback",
    response_model=KnowledgeOptimizationDetailOut,
)
async def rollback_kb_optimization(
    kb_id: UUID,
    optimization_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> KnowledgeOptimizationDetailOut:
    kb = await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    try:
        row = await get_optimization(
            session,
            workspace_id=context.workspace.id,
            kb_id=kb_id,
            optimization_id=optimization_id,
        )
        await rollback_optimization(session, optimization=row, kb=kb)
    except KnowledgeOptimizerError as exc:
        _raise_optimizer_error(exc)
    return _optimization_detail(row)


@router.post(
    "/{kb_id}/optimizations/{optimization_id}/dismiss",
    response_model=KnowledgeOptimizationDetailOut,
)
async def dismiss_kb_optimization(
    kb_id: UUID,
    optimization_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> KnowledgeOptimizationDetailOut:
    await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    try:
        row = await get_optimization(
            session,
            workspace_id=context.workspace.id,
            kb_id=kb_id,
            optimization_id=optimization_id,
        )
        await dismiss_optimization(session, optimization=row)
    except KnowledgeOptimizerError as exc:
        _raise_optimizer_error(exc)
    return _optimization_detail(row)
