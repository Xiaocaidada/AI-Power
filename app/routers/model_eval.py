from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, get_scoped_registry
from app.models import (
    ModelEvalDataset,
    ModelEvalItem,
    ModelEvalQuestion,
    ModelEvalRun,
    ModelEvalScore,
)
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas import (
    ModelEvalDatasetCreate,
    ModelEvalDatasetDetail,
    ModelEvalDatasetOut,
    ModelEvalItemOut,
    ModelEvalManualScoreIn,
    ModelEvalQuestionIn,
    ModelEvalQuestionOut,
    ModelEvalRunCreate,
    ModelEvalRunDetail,
    ModelEvalRunOut,
    ModelEvalScoreOut,
)
from app.services.provider_configs import ProviderConfigError, ensure_model_capability
from app.services.queue import JobQueue, get_queue

router = APIRouter(prefix="/model-eval", tags=["model-eval"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
QueueDep = Annotated[JobQueue, Depends(get_queue)]


async def _get_dataset(
    session: AsyncSession, dataset_id: UUID, workspace_id: UUID
) -> ModelEvalDataset:
    dataset = await session.get(ModelEvalDataset, dataset_id)
    if (
        dataset is None
        or dataset.workspace_id != workspace_id
        or dataset.deleted_at is not None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dataset not found")
    return dataset


async def _get_question(
    session: AsyncSession, question_id: UUID, workspace_id: UUID
) -> ModelEvalQuestion:
    question = await session.get(ModelEvalQuestion, question_id)
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    dataset = await session.get(ModelEvalDataset, question.dataset_id)
    if (
        dataset is None
        or dataset.workspace_id != workspace_id
        or dataset.deleted_at is not None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")
    return question


async def _dataset_out(
    session: AsyncSession, dataset: ModelEvalDataset
) -> ModelEvalDatasetOut:
    count = len(
        (
            await session.execute(
                select(ModelEvalQuestion.id).where(
                    ModelEvalQuestion.dataset_id == dataset.id
                )
            )
        ).scalars().all()
    )
    return ModelEvalDatasetOut(
        id=dataset.id,
        name=dataset.name,
        description=dataset.description,
        question_count=count,
        created_at=dataset.created_at,
    )


async def _questions(
    session: AsyncSession, dataset_id: UUID
) -> list[ModelEvalQuestion]:
    return list(
        (
            await session.execute(
                select(ModelEvalQuestion)
                .where(ModelEvalQuestion.dataset_id == dataset_id)
                .order_by(ModelEvalQuestion.sort_order, ModelEvalQuestion.id)
            )
        ).scalars()
    )


@router.get("/datasets", response_model=list[ModelEvalDatasetOut])
async def list_datasets(
    context: JwtContext, session: SessionDep
) -> list[ModelEvalDatasetOut]:
    datasets = list(
        (
            await session.execute(
                select(ModelEvalDataset)
                .where(
                    ModelEvalDataset.workspace_id == context.workspace.id,
                    ModelEvalDataset.deleted_at.is_(None),
                )
                .order_by(ModelEvalDataset.created_at.desc())
            )
        ).scalars()
    )
    return [await _dataset_out(session, item) for item in datasets]


@router.post(
    "/datasets", response_model=ModelEvalDatasetDetail, status_code=status.HTTP_201_CREATED
)
async def create_dataset(
    payload: ModelEvalDatasetCreate, context: JwtContext, session: SessionDep
) -> ModelEvalDatasetDetail:
    dataset = ModelEvalDataset(
        workspace_id=context.workspace.id,
        created_by=context.user.id,
        name=payload.name,
        description=payload.description,
    )
    session.add(dataset)
    await session.flush()
    for index, question in enumerate(payload.questions):
        session.add(
            ModelEvalQuestion(
                dataset_id=dataset.id,
                question=question.question,
                reference_answer=question.reference_answer,
                scoring_criteria=question.scoring_criteria,
                expected_keywords=question.expected_keywords,
                regex=question.regex,
                sort_order=index,
            )
        )
    await session.commit()
    await session.refresh(dataset)
    questions = await _questions(session, dataset.id)
    return ModelEvalDatasetDetail(
        **(
            await _dataset_out(session, dataset)
        ).model_dump(),
        questions=[ModelEvalQuestionOut.model_validate(item) for item in questions],
    )


@router.get("/datasets/{dataset_id}", response_model=ModelEvalDatasetDetail)
async def get_dataset(
    dataset_id: UUID, context: JwtContext, session: SessionDep
) -> ModelEvalDatasetDetail:
    dataset = await _get_dataset(session, dataset_id, context.workspace.id)
    questions = await _questions(session, dataset.id)
    return ModelEvalDatasetDetail(
        **(await _dataset_out(session, dataset)).model_dump(),
        questions=[ModelEvalQuestionOut.model_validate(item) for item in questions],
    )


@router.post(
    "/datasets/{dataset_id}/questions", response_model=ModelEvalQuestionOut
)
async def add_question(
    dataset_id: UUID,
    payload: ModelEvalQuestionIn,
    context: JwtContext,
    session: SessionDep,
) -> ModelEvalQuestion:
    dataset = await _get_dataset(session, dataset_id, context.workspace.id)
    question = ModelEvalQuestion(
        dataset_id=dataset.id,
        question=payload.question,
        reference_answer=payload.reference_answer,
        scoring_criteria=payload.scoring_criteria,
        expected_keywords=payload.expected_keywords,
        regex=payload.regex,
        sort_order=len(await _questions(session, dataset.id)),
    )
    session.add(question)
    await session.commit()
    await session.refresh(question)
    return question


@router.patch(
    "/questions/{question_id}", response_model=ModelEvalQuestionOut
)
async def update_question(
    question_id: UUID,
    payload: ModelEvalQuestionIn,
    context: JwtContext,
    session: SessionDep,
) -> ModelEvalQuestion:
    question = await _get_question(session, question_id, context.workspace.id)
    question.question = payload.question
    question.reference_answer = payload.reference_answer
    question.scoring_criteria = payload.scoring_criteria
    question.expected_keywords = payload.expected_keywords
    question.regex = payload.regex
    await session.commit()
    await session.refresh(question)
    return question


@router.delete("/questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question(
    question_id: UUID, context: JwtContext, session: SessionDep
) -> None:
    question = await _get_question(session, question_id, context.workspace.id)
    in_use = (
        await session.execute(
            select(ModelEvalItem.id).where(ModelEvalItem.question_id == question.id).limit(1)
        )
    ).first()
    if in_use is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "question_in_use",
                "message": "Question is referenced by evaluation items",
            },
        )
    await session.delete(question)
    await session.commit()


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(
    dataset_id: UUID, context: JwtContext, session: SessionDep
) -> None:
    dataset = await _get_dataset(session, dataset_id, context.workspace.id)
    dataset.deleted_at = datetime.now(UTC)
    await session.commit()


@router.get("/datasets/{dataset_id}/export")
async def export_dataset(
    dataset_id: UUID, context: JwtContext, session: SessionDep
) -> dict:
    dataset = await _get_dataset(session, dataset_id, context.workspace.id)
    questions = await _questions(session, dataset.id)
    return {
        "name": dataset.name,
        "description": dataset.description,
        "questions": [
            ModelEvalQuestionOut.model_validate(item).model_dump(mode="json")
            for item in questions
        ],
    }


def _run_out(run: ModelEvalRun) -> ModelEvalRunOut:
    return ModelEvalRunOut(
        id=run.id,
        dataset_id=run.dataset_id,
        name=run.name,
        status=run.status,
        config=run.config,
        metrics=run.metrics,
        error_code=run.error_code,
        progress_total=run.progress_total,
        progress_done=run.progress_done,
        progress_failed=run.progress_failed,
        progress_running=run.progress_running,
        current_model=run.current_model,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
    )


@router.post("/runs", response_model=ModelEvalRunOut, status_code=status.HTTP_202_ACCEPTED)
async def create_run(
    payload: ModelEvalRunCreate,
    context: JwtContext,
    session: SessionDep,
    registry: Annotated[ProviderRegistry, Depends(get_scoped_registry)],
    queue: QueueDep,
) -> ModelEvalRunOut:
    dataset = await _get_dataset(session, payload.dataset_id, context.workspace.id)
    questions = await _questions(session, dataset.id)
    if not questions:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "empty_dataset", "message": "Dataset has no questions"},
        )
    for item in payload.models:
        if item.provider_id == "auto":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "explicit_model_required", "message": "Choose explicit models"},
            )
        try:
            registry.get(item.provider_id)
            await ensure_model_capability(
                session,
                workspace_id=context.workspace.id,
                user_id=context.user.id,
                provider_id=item.provider_id,
                model_id=item.model,
                capability="chat",
            )
        except ProviderError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
        except ProviderConfigError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": exc.code, "message": exc.message},
            ) from None

    config = {
        "models": [item.model_dump() for item in payload.models],
        "parameters": payload.parameters.model_dump(exclude_none=True),
        "concurrency": payload.concurrency,
        "methods": payload.methods,
        "judge_provider_id": payload.judge_provider_id,
        "judge_model": payload.judge_model,
    }
    run = ModelEvalRun(
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        dataset_id=dataset.id,
        name=payload.name or dataset.name,
        config=config,
        progress_total=len(questions) * len(payload.models),
    )
    session.add(run)
    await session.flush()
    session.add_all(
        [
            ModelEvalItem(
                run_id=run.id,
                question_id=question.id,
                provider_id=model.provider_id,
                model=model.model,
                question_snapshot=question.question,
                reference_snapshot=question.reference_answer,
                scoring_snapshot={
                    "scoring_criteria": question.scoring_criteria,
                    "expected_keywords": list(question.expected_keywords or []),
                    "regex": question.regex,
                },
            )
            for question in questions
            for model in payload.models
        ]
    )
    await session.commit()
    await session.refresh(run)
    # Close the read transaction opened by refresh before the worker writes.
    await session.commit()
    try:
        await queue.enqueue_model_eval(run.id)
    except Exception:
        run.status = "failed"
        run.error_code = "queue_unavailable"
        await session.commit()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": "queue_unavailable", "message": "Evaluation queue unavailable"},
        ) from None
    return _run_out(run)


@router.get("/runs", response_model=list[ModelEvalRunOut])
async def list_runs(
    context: JwtContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list[ModelEvalRunOut]:
    runs = list(
        (
            await session.execute(
                select(ModelEvalRun)
                .where(ModelEvalRun.workspace_id == context.workspace.id)
                .order_by(ModelEvalRun.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )
    return [_run_out(run) for run in runs]


async def _get_run(
    session: AsyncSession, run_id: UUID, workspace_id: UUID
) -> ModelEvalRun:
    run = await session.get(ModelEvalRun, run_id)
    if run is None or run.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Evaluation run not found")
    return run


@router.get("/runs/{run_id}", response_model=ModelEvalRunDetail)
async def get_run(
    run_id: UUID, context: JwtContext, session: SessionDep
) -> ModelEvalRunDetail:
    run = await _get_run(session, run_id, context.workspace.id)
    items = list(
        (
            await session.execute(
                select(ModelEvalItem)
                .where(ModelEvalItem.run_id == run.id)
                .order_by(ModelEvalItem.created_at, ModelEvalItem.id)
            )
        ).scalars()
    )
    scores = list(
        (
            await session.execute(
                select(ModelEvalScore).where(
                    ModelEvalScore.item_id.in_([item.id for item in items])
                )
            )
        ).scalars()
    ) if items else []
    scores_by_item: dict[UUID, list[ModelEvalScore]] = {}
    for score in scores:
        scores_by_item.setdefault(score.item_id, []).append(score)
    return ModelEvalRunDetail(
        **_run_out(run).model_dump(),
        items=[
            ModelEvalItemOut(
                id=item.id,
                question_id=item.question_id,
                provider_id=item.provider_id,
                model=item.model,
                question=item.question_snapshot,
                answer=item.answer,
                status=item.status,
                error_code=item.error_code,
                prompt_tokens=item.prompt_tokens,
                completion_tokens=item.completion_tokens,
                cost=item.cost,
                ttft_ms=item.ttft_ms,
                latency_ms=item.latency_ms,
                scores=[
                    ModelEvalScoreOut(
                        method=score.method,
                        score=score.score,
                        passed=score.passed,
                        reason=score.reason,
                        judge_provider_id=score.judge_provider_id,
                        judge_model=score.judge_model,
                    )
                    for score in scores_by_item.get(item.id, [])
                ],
            )
            for item in items
        ],
    )


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(
    run_id: UUID, context: JwtContext, session: SessionDep
) -> None:
    run = await _get_run(session, run_id, context.workspace.id)
    if run.status in ("queued", "running"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"code": "run_active", "message": "Cancel the run before deleting it"},
        )
    item_ids = list(
        (
            await session.execute(
                select(ModelEvalItem.id).where(ModelEvalItem.run_id == run.id)
            )
        ).scalars()
    )
    if item_ids:
        await session.execute(
            delete(ModelEvalScore).where(ModelEvalScore.item_id.in_(item_ids))
        )
        await session.execute(
            delete(ModelEvalItem).where(ModelEvalItem.id.in_(item_ids))
        )
    await session.execute(delete(ModelEvalRun).where(ModelEvalRun.id == run.id))
    await session.commit()


@router.post("/runs/{run_id}/cancel", response_model=ModelEvalRunOut)
async def cancel_run(
    run_id: UUID, context: JwtContext, session: SessionDep
) -> ModelEvalRunOut:
    run = await _get_run(session, run_id, context.workspace.id)
    run.cancel_requested_at = datetime.now(UTC)
    if run.status == "queued":
        run.status = "cancelled"
        run.finished_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(run)
    return _run_out(run)


@router.post("/items/{item_id}/retry", response_model=ModelEvalRunOut)
async def retry_item(
    item_id: UUID,
    context: JwtContext,
    session: SessionDep,
    queue: QueueDep,
) -> ModelEvalRunOut:
    item = await session.get(ModelEvalItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    run = await _get_run(session, item.run_id, context.workspace.id)
    item.status = "queued"
    item.answer = ""
    item.error_code = None
    await session.execute(delete(ModelEvalScore).where(ModelEvalScore.item_id == item.id))
    run.status = "running"
    run.cancel_requested_at = None
    run.finished_at = None
    await session.commit()
    await queue.enqueue_model_eval(run.id)
    return _run_out(run)


@router.post("/items/{item_id}/scores", response_model=ModelEvalScoreOut)
async def manual_score(
    item_id: UUID,
    payload: ModelEvalManualScoreIn,
    context: JwtContext,
    session: SessionDep,
) -> ModelEvalScoreOut:
    item = await session.get(ModelEvalItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Item not found")
    await _get_run(session, item.run_id, context.workspace.id)
    score = (
        await session.execute(
            select(ModelEvalScore).where(
                ModelEvalScore.item_id == item.id,
                ModelEvalScore.method == "manual",
                ModelEvalScore.scorer_user_id == context.user.id,
            )
        )
    ).scalar_one_or_none()
    if score is None:
        score = ModelEvalScore(
            item_id=item.id,
            method="manual",
            scorer_user_id=context.user.id,
        )
        session.add(score)
    score.score = payload.score
    score.passed = payload.passed
    score.reason = payload.reason
    await session.commit()
    await session.refresh(score)
    return ModelEvalScoreOut(
        method=score.method,
        score=score.score,
        passed=score.passed,
        reason=score.reason,
    )