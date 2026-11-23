import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, get_registry
from app.models import (
    Document,
    EvalDataset,
    EvalQuestion,
    EvalRun,
    EvalRunItem,
    Workflow,
    WorkflowVersion,
)
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas import (
    EvalCompareOut,
    EvalDatasetCreate,
    EvalDatasetDetailOut,
    EvalDatasetImportIn,
    EvalDatasetOut,
    EvalNodeTimingOut,
    EvalQuestionInsightOut,
    EvalQuestionOut,
    EvalRunAnalysisOut,
    EvalRunCreate,
    EvalRunDetailOut,
    EvalRunItemOut,
    EvalRunOut,
)
from app.services.access import get_owned_knowledge_base
from app.services.knowledge.metrics import aggregate_retrieval_traces
from app.services.knowledge.retrieval_schema import (
    RetrievalValidationError,
    validate_knowledge_retrieval,
)
from app.services.knowledge_settings import resolve_kb_settings
from app.services.queue import JobQueue, get_queue
from app.services.retrieval import resolve_options

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
QueueDep = Annotated[JobQueue, Depends(get_queue)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_registry)]


async def _get_dataset(session: AsyncSession, dataset_id: UUID, workspace_id: UUID) -> EvalDataset:
    dataset = (
        await session.execute(
            select(EvalDataset).where(
                EvalDataset.id == dataset_id,
                EvalDataset.workspace_id == workspace_id,
                EvalDataset.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evaluation dataset not found")
    return dataset


async def _get_run(session: AsyncSession, run_id: UUID, workspace_id: UUID) -> EvalRun:
    run = (
        await session.execute(
            select(EvalRun).where(EvalRun.id == run_id, EvalRun.workspace_id == workspace_id)
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evaluation run not found")
    return run


async def _resolve_retrieval_version(
    session: AsyncSession, version_id: UUID | None, workspace_id: UUID
) -> tuple[WorkflowVersion | None, dict[str, object] | None]:
    if version_id is None:
        return None, None
    version = await session.get(WorkflowVersion, version_id)
    workflow = await session.get(Workflow, version.workflow_id) if version else None
    if (
        version is None
        or workflow is None
        or workflow.workspace_id != workspace_id
        or workflow.deleted_at is not None
        or workflow.kind != "knowledge_retrieval"
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "invalid_retrieval_workflow",
                "message": "Retrieval workflow version not found",
            },
        )
    try:
        validate_knowledge_retrieval(version.definition)
    except RetrievalValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "invalid_retrieval_workflow",
                "message": f"Retrieval workflow is invalid: {exc}",
            },
        ) from None
    snapshot = {
        "retrieval_workflow_version_id": str(version.id),
        "workflow_id": str(workflow.id),
        "version": version.version,
        "name": workflow.name,
    }
    return version, snapshot


async def _dataset_questions(session: AsyncSession, dataset_id: UUID) -> list[EvalQuestion]:
    return list(
        (
            await session.execute(
                select(EvalQuestion)
                .where(EvalQuestion.dataset_id == dataset_id)
                .order_by(EvalQuestion.created_at, EvalQuestion.id)
            )
        ).scalars()
    )


async def _create_questions(
    session: AsyncSession, dataset_id: UUID, questions: list[EvalQuestion]
) -> None:
    for question in questions:
        question.dataset_id = dataset_id
        session.add(question)


def _document_ids(questions: list[EvalQuestion]) -> set[UUID]:
    ids: set[UUID] = set()
    for question in questions:
        ids.update(UUID(str(value)) for value in question.relevant_document_ids)
    return ids


@router.get("/datasets", response_model=list[EvalDatasetOut])
async def list_datasets(
    context: JwtContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[EvalDatasetOut]:
    datasets = list(
        (
            await session.execute(
                select(EvalDataset)
                .where(
                    EvalDataset.workspace_id == context.workspace.id,
                    EvalDataset.deleted_at.is_(None),
                )
                .order_by(EvalDataset.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
    counts: dict[UUID, int] = {}
    if datasets:
        rows = (
            await session.execute(
                select(EvalQuestion.dataset_id, func.count())
                .where(EvalQuestion.dataset_id.in_([dataset.id for dataset in datasets]))
                .group_by(EvalQuestion.dataset_id)
            )
        ).all()
        counts = {dataset_id: count for dataset_id, count in rows}
    return [
        EvalDatasetOut(
            id=dataset.id,
            name=dataset.name,
            description=dataset.description,
            question_count=counts.get(dataset.id, 0),
            created_at=dataset.created_at,
        )
        for dataset in datasets
    ]


@router.post("/datasets", response_model=EvalDatasetDetailOut, status_code=status.HTTP_201_CREATED)
async def create_dataset(
    payload: EvalDatasetCreate, context: JwtContext, session: SessionDep
) -> EvalDatasetDetailOut:
    ids = {
        document_id
        for question in payload.questions
        for document_id in question.relevant_document_ids
    }
    existing = set(
        (
            await session.execute(
                select(Document.id).where(
                    Document.workspace_id == context.workspace.id,
                    Document.deleted_at.is_(None),
                    Document.id.in_(ids),
                )
            )
        ).scalars()
    )
    missing = ids - existing
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "documents_not_found",
                "message": f"{len(missing)} referenced documents do not exist",
            },
        )
    dataset = EvalDataset(
        workspace_id=context.workspace.id,
        name=payload.name,
        description=payload.description,
        created_by=context.user.id,
    )
    session.add(dataset)
    await session.flush()
    questions = [
        EvalQuestion(
            question=question.question,
            relevant_document_ids=[str(value) for value in question.relevant_document_ids],
            evidence=question.evidence,
        )
        for question in payload.questions
    ]
    await _create_questions(session, dataset.id, questions)
    await session.commit()
    await session.refresh(dataset)
    return EvalDatasetDetailOut(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        question_count=len(questions),
        created_at=dataset.created_at,
        questions=[EvalQuestionOut.model_validate(question) for question in questions],
    )


@router.post(
    "/datasets/import",
    response_model=EvalDatasetDetailOut,
    status_code=status.HTTP_201_CREATED,
)
async def import_dataset(
    payload: EvalDatasetImportIn, context: JwtContext, session: SessionDep
) -> EvalDatasetDetailOut:
    await get_owned_knowledge_base(payload.kb_id, context.workspace.id, session)
    documents = list(
        (
            await session.execute(
                select(Document).where(
                    Document.kb_id == payload.kb_id,
                    Document.workspace_id == context.workspace.id,
                    Document.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    by_filename: dict[str, Document] = {}
    for document in documents:
        if document.filename in by_filename:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {
                    "code": "duplicate_filename",
                    "message": f"Knowledge base has duplicate filename: {document.filename}",
                },
            )
        by_filename[document.filename] = document

    questions: list[EvalQuestion] = []
    for item in payload.bundle.questions:
        missing = [name for name in item.relevant_filenames if name not in by_filename]
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {
                    "code": "unknown_filenames",
                    "message": f"Documents not found in knowledge base: {', '.join(missing[:5])}",
                },
            )
        questions.append(
            EvalQuestion(
                question=item.question,
                relevant_document_ids=[
                    str(by_filename[name].id) for name in item.relevant_filenames
                ],
                evidence=item.evidence,
            )
        )
    dataset = EvalDataset(
        workspace_id=context.workspace.id,
        name=payload.name,
        description=payload.description or payload.bundle.description,
        created_by=context.user.id,
    )
    session.add(dataset)
    await session.flush()
    await _create_questions(session, dataset.id, questions)
    await session.commit()
    await session.refresh(dataset)
    return EvalDatasetDetailOut(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        question_count=len(questions),
        created_at=dataset.created_at,
        questions=[EvalQuestionOut.model_validate(question) for question in questions],
    )


@router.get("/datasets/{dataset_id}", response_model=EvalDatasetDetailOut)
async def get_dataset(
    dataset_id: UUID, context: JwtContext, session: SessionDep
) -> EvalDatasetDetailOut:
    dataset = await _get_dataset(session, dataset_id, context.workspace.id)
    questions = await _dataset_questions(session, dataset.id)
    return EvalDatasetDetailOut(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        question_count=len(questions),
        created_at=dataset.created_at,
        questions=[EvalQuestionOut.model_validate(question) for question in questions],
    )


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(dataset_id: UUID, context: JwtContext, session: SessionDep) -> Response:
    dataset = await _get_dataset(session, dataset_id, context.workspace.id)
    dataset.deleted_at = datetime.now(UTC)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/runs", response_model=EvalRunOut, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    payload: EvalRunCreate,
    context: JwtContext,
    session: SessionDep,
    queue: QueueDep,
    registry: RegistryDep,
) -> EvalRunOut:
    dataset = await _get_dataset(session, payload.dataset_id, context.workspace.id)
    kb = await get_owned_knowledge_base(payload.kb_id, context.workspace.id, session)
    retrieval_version, retrieval_snapshot = await _resolve_retrieval_version(
        session, payload.retrieval_workflow_version_id, context.workspace.id
    )
    questions = await _dataset_questions(session, dataset.id)
    if not questions:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "empty_dataset", "message": "Dataset has no questions"},
        )

    doc_ids = _document_ids(questions)
    ready_ids = set(
        (
            await session.execute(
                select(Document.id).where(
                    Document.id.in_(doc_ids),
                    Document.kb_id == kb.id,
                    Document.workspace_id == context.workspace.id,
                    Document.status == "ready",
                    Document.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    if ready_ids != doc_ids:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "dataset_documents_unavailable",
                "message": "Dataset references documents that are missing or not ready in this KB",
            },
        )

    kb_settings = resolve_kb_settings(kb)
    options = resolve_options(
        kb_settings,
        top_k=payload.top_k,
        candidate_k=payload.candidate_k,
        hybrid_enabled=payload.hybrid_enabled,
        rerank_enabled=payload.rerank_enabled,
    )
    answer_enabled = payload.answer_enabled
    judge_enabled = payload.judge_enabled
    provider_id = payload.provider_id.strip() if payload.provider_id else None
    model = payload.model.strip() if payload.model else None
    judge_provider_id = (
        payload.judge_provider_id.strip() if payload.judge_provider_id else provider_id
    )
    judge_model = payload.judge_model.strip() if payload.judge_model else model
    if answer_enabled:
        _require_provider(registry, provider_id)
        if judge_enabled:
            _require_provider(registry, judge_provider_id)

    config = {
        "top_k": options.top_k,
        "candidate_k": options.candidate_k,
        "hybrid_enabled": options.hybrid_enabled,
        "rerank_enabled": options.rerank_enabled,
        "chunking": kb_settings.chunking.model_dump(),
        "answer_enabled": answer_enabled,
        "judge_enabled": judge_enabled,
        "provider_id": provider_id,
        "model": model,
        "judge_provider_id": judge_provider_id,
        "judge_model": judge_model,
        "judge_version": 1,
        "retrieval_workflow_version_id": (
            str(retrieval_version.id) if retrieval_version is not None else None
        ),
        "retrieval_workflow": retrieval_snapshot,
    }
    run = EvalRun(
        dataset_id=dataset.id,
        kb_id=kb.id,
        retrieval_workflow_version_id=(
            retrieval_version.id if retrieval_version is not None else None
        ),
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        status="queued",
        config=config,
        progress_total=len(questions),
        progress_done=0,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    try:
        await queue.enqueue_evaluation(run.id)
    except Exception:
        logger.exception("failed to enqueue evaluation run %s", run.id)
        run.status = "failed"
        run.error_code = "queue_unavailable"
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": "queue_unavailable", "message": "Evaluation queue unavailable"},
        ) from None
    await session.refresh(run)
    return EvalRunOut.model_validate(run)


@router.get("/runs", response_model=list[EvalRunOut])
async def list_runs(
    context: JwtContext,
    session: SessionDep,
    dataset_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[EvalRun]:
    statement = select(EvalRun).where(EvalRun.workspace_id == context.workspace.id)
    if dataset_id is not None:
        statement = statement.where(EvalRun.dataset_id == dataset_id)
    result = await session.execute(statement.order_by(EvalRun.created_at.desc()).limit(limit))
    return list(result.scalars())


@router.get("/runs/{run_id}", response_model=EvalRunDetailOut)
async def get_run(run_id: UUID, context: JwtContext, session: SessionDep) -> EvalRunDetailOut:
    run = await _get_run(session, run_id, context.workspace.id)
    items = list(
        (
            await session.execute(
                select(EvalRunItem)
                .where(EvalRunItem.run_id == run.id)
                .order_by(EvalRunItem.created_at, EvalRunItem.id)
            )
        ).scalars()
    )
    base = EvalRunOut.model_validate(run)
    return EvalRunDetailOut(
        **base.model_dump(),
        items=[EvalRunItemOut.model_validate(item) for item in items],
    )


def _insight(item: EvalRunItem) -> EvalQuestionInsightOut:
    return EvalQuestionInsightOut(
        question_id=item.question_id,
        question_text=item.question_text,
        hit_rank=item.hit_rank,
        precision_at_5=item.precision_at_5,
        recall_at_5=item.recall_at_5,
        ndcg_at_5=item.ndcg_at_5,
        latency_ms=item.latency_ms,
        retrieval_mode=item.retrieval_mode,
        error_code=item.error_code,
    )


@router.get("/runs/{run_id}/analysis", response_model=EvalRunAnalysisOut)
async def get_run_analysis(
    run_id: UUID, context: JwtContext, session: SessionDep
) -> EvalRunAnalysisOut:
    run = await _get_run(session, run_id, context.workspace.id)
    items = list(
        (
            await session.execute(
                select(EvalRunItem)
                .where(EvalRunItem.run_id == run.id)
                .order_by(EvalRunItem.created_at, EvalRunItem.id)
            )
        ).scalars()
    )
    node_rows = aggregate_retrieval_traces(
        [item.retrieval_trace for item in items if item.retrieval_trace]
    )
    worst = sorted(items, key=lambda item: (item.ndcg_at_5, item.hit_rank or 999))[:10]
    missed = [
        item
        for item in items
        if item.hit_rank is None or item.ndcg_at_5 <= 0.0 or item.error_code is not None
    ][:20]
    slowest = sorted(
        (item for item in items if item.latency_ms is not None),
        key=lambda item: item.latency_ms or 0.0,
        reverse=True,
    )[:10]
    return EvalRunAnalysisOut(
        run=EvalRunOut.model_validate(run),
        node_timing=[EvalNodeTimingOut(**row) for row in node_rows],
        worst_questions=[_insight(item) for item in worst],
        missed_questions=[_insight(item) for item in missed],
        slowest_questions=[_insight(item) for item in slowest],
    )


@router.get("/compare", response_model=EvalCompareOut)
async def compare_runs(
    context: JwtContext,
    session: SessionDep,
    ids: Annotated[list[UUID], Query(min_length=2, max_length=5)],
) -> EvalCompareOut:
    runs = list(
        (
            await session.execute(
                select(EvalRun).where(
                    EvalRun.workspace_id == context.workspace.id, EvalRun.id.in_(ids)
                )
            )
        ).scalars()
    )
    if len(runs) != len(set(ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evaluation run not found")
    by_id = {run.id: run for run in runs}
    return EvalCompareOut(runs=[EvalRunOut.model_validate(by_id[run_id]) for run_id in ids])


def _require_provider(registry: ProviderRegistry, provider_id: str | None) -> None:
    if provider_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "provider_not_configured", "message": "Provider is required"},
        )
    try:
        registry.get(provider_id)
    except ProviderError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "provider_not_found", "message": f"Unknown provider: {provider_id}"},
        ) from None
