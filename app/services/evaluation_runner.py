import json
import logging
import math
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionLocal
from app.metrics import metrics
from app.models import EvalQuestion, EvalRun, EvalRunItem, Workflow, WorkflowVersion
from app.providers.base import ChatMessage, LLMProvider, ProviderError, Usage
from app.providers.embedding import EmbeddingProvider
from app.providers.registry import ProviderRegistry, build_registry
from app.providers.rerank import Reranker, build_reranker
from app.services.costs import compute_cost, price_snapshot
from app.services.embedding_factory import build_embedder
from app.services.knowledge.metrics import (
    aggregate_retrieval_traces,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)
from app.services.knowledge.retrieval_pipeline import (
    RetrievalWorkflowError,
    run_retrieval_workflow,
)
from app.services.knowledge.retrieval_schema import (
    KnowledgeRetrievalDefinition,
    RetrievalValidationError,
    validate_knowledge_retrieval,
)
from app.services.rag import build_rag_messages, fit_context
from app.services.retrieval import RetrievalOptions, RetrievedChunk, retrieve_chunks

logger = logging.getLogger(__name__)

JUDGE_SYSTEM_PROMPT = (
    "You are a strict evaluator of retrieval-augmented answers. "
    "Use only the reference passages to decide whether the answer is supported. "
    "Return exactly one JSON object with keys: "
    "score (integer 1-5), faithful (boolean), reason (short string). "
    "5 = correct, complete, and fully supported; 1 = wrong or unsupported. "
    "Do not use markdown or add any text outside the JSON object."
)
JUDGE_JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
ANSWER_MAX_CHARS = 8000
JUDGE_REASON_MAX_CHARS = 1000


@dataclass(frozen=True, slots=True)
class Completion:
    text: str
    prompt_tokens: int | None
    completion_tokens: int | None


async def complete(
    provider: LLMProvider,
    messages: list[ChatMessage],
    model: str,
    *,
    temperature: float = 0.0,
) -> Completion:
    parts: list[str] = []
    usage: Usage | None = None
    async for chunk in provider.stream_chat(messages, model, temperature=temperature):
        if chunk.delta:
            parts.append(chunk.delta)
        if chunk.usage is not None:
            usage = chunk.usage
    return Completion(
        text="".join(parts).strip(),
        prompt_tokens=usage.prompt_tokens if usage else None,
        completion_tokens=usage.completion_tokens if usage else None,
    )


def parse_judge_response(text: str) -> tuple[int, bool, str]:
    match = JUDGE_JSON_PATTERN.search(text)
    if match is None:
        raise ValueError("judge response has no JSON object")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("judge response is not an object")
    score = data.get("score")
    faithful = data.get("faithful")
    reason = data.get("reason", "")
    if isinstance(score, str):
        try:
            score = float(score)
        except ValueError:
            raise ValueError("judge score must be numeric") from None
    if isinstance(score, float):
        score = int(round(score))
    if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
        raise ValueError("judge score must be an integer in [1, 5]")
    if isinstance(faithful, str) and faithful.strip().lower() in {"true", "false"}:
        faithful = faithful.strip().lower() == "true"
    if not isinstance(faithful, bool):
        raise ValueError("judge faithful must be a boolean")
    return score, faithful, str(reason)[:JUDGE_REASON_MAX_CHARS]


async def run_evaluation(
    run_id: UUID,
    *,
    embedder: EmbeddingProvider | None = None,
    reranker: Reranker | None = None,
    registry: ProviderRegistry | None = None,
) -> None:
    settings = get_settings()
    async with SessionLocal() as session:
        run = await session.get(EvalRun, run_id)
        if run is None:
            return
        questions = list(
            (
                await session.execute(
                    select(EvalQuestion)
                    .where(EvalQuestion.dataset_id == run.dataset_id)
                    .order_by(EvalQuestion.created_at, EvalQuestion.id)
                )
            ).scalars()
        )
        if not questions:
            await _mark_failed(session, run_id, "empty_dataset")
            return

        await session.execute(delete(EvalRunItem).where(EvalRunItem.run_id == run_id))
        run.status = "running"
        run.error_code = None
        run.started_at = datetime.now(UTC)
        run.finished_at = None
        run.progress_total = len(questions)
        run.progress_done = 0
        run.prompt_tokens = 0
        run.completion_tokens = 0
        run.cost = 0.0
        await session.commit()

        config = dict(run.config)
        try:
            options = RetrievalOptions(
                top_k=int(config["top_k"]),
                candidate_k=int(config["candidate_k"]),
                hybrid_enabled=bool(config["hybrid_enabled"]),
                rerank_enabled=bool(config["rerank_enabled"]),
            )
            answer_enabled = bool(config.get("answer_enabled", False))
            judge_enabled = bool(config.get("judge_enabled", False))
            provider_id = _optional_str(config.get("provider_id"))
            model = _optional_str(config.get("model"))
            workflow_definition = await _load_retrieval_definition(
                session, run, _optional_str(config.get("retrieval_workflow_version_id"))
            )
            judge_provider_id = _optional_str(config.get("judge_provider_id")) or provider_id
            judge_model = _optional_str(config.get("judge_model")) or model

            provider: LLMProvider | None = None
            judge_provider: LLMProvider | None = None
            if answer_enabled:
                if provider_id is None or model is None:
                    raise ProviderError("provider_not_configured", "Answer provider/model missing")
                provider = (registry or build_registry()).get(provider_id)
                if judge_enabled:
                    if judge_provider_id is None or judge_model is None:
                        raise ProviderError("judge_not_configured", "Judge provider/model missing")
                    judge_provider = (registry or build_registry()).get(judge_provider_id)

            active_embedder = embedder or build_embedder()
            active_reranker = reranker or build_reranker(settings)
            answer_prices = await price_snapshot(session, provider_id, model)
            judge_prices = await price_snapshot(session, judge_provider_id, judge_model)
            items: list[EvalRunItem] = []

            for index, question in enumerate(questions):
                item = await _evaluate_question(
                    session,
                    run=run,
                    question=question,
                    options=options,
                    embedder=active_embedder,
                    reranker=active_reranker,
                    provider=provider,
                    model=model,
                    judge_provider=judge_provider,
                    judge_model=judge_model,
                    answer_enabled=answer_enabled,
                    judge_enabled=judge_enabled,
                    answer_prices=answer_prices,
                    judge_prices=judge_prices,
                    max_context_chars=settings.retrieval_max_context_chars,
                    workflow_definition=workflow_definition,
                    registry=registry,
                )
                session.add(item)
                items.append(item)
                run.progress_done = index + 1
                run.prompt_tokens += item.prompt_tokens
                run.completion_tokens += item.completion_tokens
                run.cost += item.cost
                await session.commit()

            run.metrics = compute_metrics(
                items,
                answer_enabled=answer_enabled,
                judge_enabled=judge_enabled,
            )
            run.status = "completed"
            run.error_code = None
            run.finished_at = datetime.now(UTC)
            await session.commit()
            metrics.inc_counter(
                "ai_power_knowledge_eval_runs_total",
                status="completed",
                mode=str(run.metrics.get("retrieval_mode") or "builtin"),
            )
        except ProviderError as exc:
            await session.rollback()
            logger.warning("evaluation run %s failed: %s", run_id, exc.code)
            await _mark_failed(session, run_id, exc.code)
        except Exception:
            logger.exception("evaluation run %s failed unexpectedly", run_id)
            await session.rollback()
            await _mark_failed(session, run_id, "evaluation_failed")


async def _load_retrieval_definition(
    session: AsyncSession, run: EvalRun, raw_version_id: str | None
) -> KnowledgeRetrievalDefinition | None:
    if raw_version_id is None:
        return None
    try:
        version_id = UUID(raw_version_id)
    except ValueError:
        raise ProviderError(
            "invalid_retrieval_workflow", "Invalid retrieval workflow version"
        ) from None
    version = await session.get(WorkflowVersion, version_id)
    workflow = await session.get(Workflow, version.workflow_id) if version else None
    if (
        version is None
        or workflow is None
        or workflow.workspace_id != run.workspace_id
        or workflow.kind != "knowledge_retrieval"
        or workflow.deleted_at is not None
    ):
        raise ProviderError(
            "invalid_retrieval_workflow", "Retrieval workflow version not found"
        )
    try:
        return validate_knowledge_retrieval(version.definition)
    except RetrievalValidationError as exc:
        raise ProviderError(
            "invalid_retrieval_workflow", f"Retrieval workflow is invalid: {exc}"
        ) from None


async def _evaluate_question(
    session: AsyncSession,
    *,
    run: EvalRun,
    question: EvalQuestion,
    options: RetrievalOptions,
    embedder: EmbeddingProvider,
    reranker: Reranker | None,
    provider: LLMProvider | None,
    model: str | None,
    judge_provider: LLMProvider | None,
    judge_model: str | None,
    answer_enabled: bool,
    judge_enabled: bool,
    answer_prices: tuple[float | None, float | None],
    judge_prices: tuple[float | None, float | None],
    max_context_chars: int,
    workflow_definition: KnowledgeRetrievalDefinition | None = None,
    registry: ProviderRegistry | None = None,
) -> EvalRunItem:
    started = time.perf_counter()
    retrieval_mode = "workflow" if workflow_definition is not None else "builtin"
    traces: list[dict[str, object]] = []
    error_code: str | None = None
    if workflow_definition is not None:
        try:
            workflow_result = await run_retrieval_workflow(
                session,
                definition=workflow_definition,
                workspace_id=run.workspace_id,
                kb_ids=[run.kb_id],
                query=question.question,
                registry=registry,
                user_id=run.user_id,
                collect_traces=True,
            )
            chunks = workflow_result.chunks or workflow_result.selected
            traces = [
                {
                    "node_id": trace.node_id,
                    "node_type": trace.node_type,
                    "status": trace.status,
                    "duration_ms": trace.duration_ms,
                    "count": trace.count,
                    "error_code": trace.error_code,
                }
                for trace in workflow_result.traces[:50]
            ]
        except RetrievalWorkflowError as exc:
            chunks = []
            error_code = exc.code
        except Exception:
            logger.exception(
                "evaluation %s question %s retrieval workflow failed",
                run.id,
                question.id,
            )
            chunks = []
            error_code = "retrieval_workflow_failed"
    else:
        chunks = await retrieve_chunks(
            session,
            workspace_id=run.workspace_id,
            kb_id=run.kb_id,
            query=question.question,
            options=options,
            embedder=embedder,
            reranker=reranker,
        )
    latency_ms = _elapsed_ms(started)
    relevant = {UUID(str(value)) for value in question.relevant_document_ids}
    ranked_documents = [chunk.document_id for chunk in chunks]
    hit_rank = next(
        (index for index, chunk in enumerate(chunks, start=1) if chunk.document_id in relevant),
        None,
    )
    evidence = [str(item).strip().lower() for item in question.evidence if str(item).strip()]
    evidence_hit = (
        any(phrase in chunk.text.lower() for chunk in chunks for phrase in evidence)
        if evidence
        else None
    )

    item = EvalRunItem(
        run_id=run.id,
        question_id=question.id,
        question_text=question.question,
        hit_rank=hit_rank,
        reciprocal_rank=1.0 / hit_rank if hit_rank else 0.0,
        precision_at_5=precision_at_k(relevant, ranked_documents, 5),
        recall_at_5=recall_at_k(relevant, ranked_documents, 5),
        ndcg_at_5=ndcg_at_k(relevant, ranked_documents, 5),
        precision_at_10=precision_at_k(relevant, ranked_documents, 10),
        recall_at_10=recall_at_k(relevant, ranked_documents, 10),
        ndcg_at_10=ndcg_at_k(relevant, ranked_documents, 10),
        retrieval_mode=retrieval_mode,
        retrieval_trace=traces,
        evidence_hit=evidence_hit,
        latency_ms=latency_ms,
        top_document_ids=[str(chunk.document_id) for chunk in chunks],
        top_chunk_ids=[str(chunk.chunk_id) for chunk in chunks],
        prompt_tokens=0,
        completion_tokens=0,
        cost=0.0,
        error_code=error_code,
    )
    if error_code is not None:
        return item
    if not answer_enabled or provider is None or model is None:
        return item

    used_chunks = fit_context(chunks, max_context_chars)
    cited_documents = {chunk.document_id for chunk in used_chunks}
    item.citation_precision = (
        round(len(cited_documents & relevant) / len(cited_documents), 4)
        if cited_documents
        else 0.0
    )
    item.citation_recall = (
        round(len(cited_documents & relevant) / len(relevant), 4)
        if relevant
        else None
    )
    answer_started = time.perf_counter()
    try:
        completion = await complete(
            provider,
            build_rag_messages(used_chunks, [ChatMessage(role="user", content=question.question)]),
            model,
        )
    except ProviderError as exc:
        raise ProviderError("answer_failed", f"Answer generation failed: {exc.code}") from None
    item.answer_latency_ms = _elapsed_ms(answer_started)
    item.answer = completion.text[:ANSWER_MAX_CHARS]
    item.prompt_tokens = completion.prompt_tokens or 0
    item.completion_tokens = completion.completion_tokens or 0
    item.cost = compute_cost(
        completion.prompt_tokens,
        completion.completion_tokens,
        answer_prices[0],
        answer_prices[1],
    )
    if not judge_enabled or judge_provider is None or judge_model is None:
        return item

    try:
        judge_completion = await complete(
            judge_provider,
            _judge_messages(question.question, used_chunks, item.answer or ""),
            judge_model,
        )
        score, faithful, reason = parse_judge_response(judge_completion.text)
        item.judge_score = score
        item.judge_faithful = faithful
        item.judge_reason = reason
        item.prompt_tokens += judge_completion.prompt_tokens or 0
        item.completion_tokens += judge_completion.completion_tokens or 0
        item.cost += compute_cost(
            judge_completion.prompt_tokens,
            judge_completion.completion_tokens,
            judge_prices[0],
            judge_prices[1],
        )
    except ProviderError as exc:
        item.judge_error = exc.code
    except (ValueError, json.JSONDecodeError):
        item.judge_error = "judge_bad_response"
    return item


def compute_metrics(
    items: list[EvalRunItem],
    *,
    answer_enabled: bool = False,
    judge_enabled: bool = False,
) -> dict[str, object]:
    total = len(items)
    if total == 0:
        return {"total": 0, "completed": 0, "errors": 0}
    ranks = [item.hit_rank for item in items]
    latencies = [item.latency_ms for item in items if item.latency_ms is not None]
    evidence_items = [item for item in items if item.evidence_hit is not None]
    judged = [item for item in items if item.judge_score is not None]
    citation_items = [
        item for item in items if item.citation_precision is not None
    ]
    citation_recall_items = [
        item for item in items if item.citation_recall is not None
    ]
    citation_precision = (
        round(
            sum(item.citation_precision or 0.0 for item in citation_items)
            / len(citation_items),
            4,
        )
        if citation_items
        else None
    )
    citation_recall = (
        round(
            sum(item.citation_recall or 0.0 for item in citation_recall_items)
            / len(citation_recall_items),
            4,
        )
        if citation_recall_items
        else None
    )
    metrics: dict[str, object] = {
        "total": total,
        "completed": sum(1 for item in items if item.error_code is None),
        "errors": sum(1 for item in items if item.error_code is not None),
        "recall_at_1": round(sum(1 for rank in ranks if rank is not None and rank <= 1) / total, 4),
        "recall_at_3": round(sum(1 for rank in ranks if rank is not None and rank <= 3) / total, 4),
        "recall_at_5": round(sum(1 for rank in ranks if rank is not None and rank <= 5) / total, 4),
        "precision_at_5": _mean(items, "precision_at_5"),
        "recall_at_5_docs": _mean(items, "recall_at_5"),
        "ndcg_at_5": _mean(items, "ndcg_at_5"),
        "precision_at_10": _mean(items, "precision_at_10"),
        "recall_at_10_docs": _mean(items, "recall_at_10"),
        "ndcg_at_10": _mean(items, "ndcg_at_10"),
        "success_rate": round(
            sum(1 for item in items if item.error_code is None) / total, 4
        ),
        "mrr": round(sum(item.reciprocal_rank for item in items) / total, 4),
        "evidence_hit_rate": (
            round(sum(1 for item in evidence_items if item.evidence_hit) / len(evidence_items), 4)
            if evidence_items
            else None
        ),
        "citation_precision": citation_precision,
        "citation_recall": citation_recall,
        "citation_f1": (
            round(
                2
                * citation_precision
                * citation_recall
                / (citation_precision + citation_recall),
                4,
            )
            if citation_precision is not None
            and citation_recall is not None
            and (citation_precision + citation_recall) > 0
            else None
        ),
        "latency_p50_ms": _percentile(latencies, 50),
        "latency_p95_ms": _percentile(latencies, 95),
        "answer_enabled": answer_enabled,
        "judge_enabled": judge_enabled,
        "judged_count": len(judged),
        "judge_avg_score": (
            round(sum(item.judge_score or 0 for item in judged) / len(judged), 2)
            if judged
            else None
        ),
        "judge_pass_rate": (
            round(sum(1 for item in judged if (item.judge_score or 0) >= 4) / len(judged), 4)
            if judged
            else None
        ),
        "faithful_rate": (
            round(sum(1 for item in judged if item.judge_faithful) / len(judged), 4)
            if judged
            else None
        ),
        "judge_errors": sum(1 for item in items if item.judge_error is not None),
        "prompt_tokens": sum(item.prompt_tokens or 0 for item in items),
        "completion_tokens": sum(item.completion_tokens or 0 for item in items),
        "cost": round(sum(item.cost or 0.0 for item in items), 6),
        "retrieval_mode": items[0].retrieval_mode if items else None,
        "node_timing": aggregate_retrieval_traces(
            [item.retrieval_trace for item in items if item.retrieval_trace]
        ),
    }
    return metrics


def _mean(items: list[EvalRunItem], attribute: str) -> float:
    if not items:
        return 0.0
    return round(sum(float(getattr(item, attribute) or 0.0) for item in items) / len(items), 4)


def _judge_messages(question: str, chunks: list[RetrievedChunk], answer: str) -> list[ChatMessage]:
    references = (
        "\n\n".join(
            f"[{index}] ({chunk.filename})\n{chunk.text}"
            for index, chunk in enumerate(chunks, start=1)
        )
        or "(no reference passages retrieved)"
    )
    content = (
        f"Question:\n{question}\n\n"
        f"Reference passages:\n{references}\n\n"
        f"Answer:\n{answer}\n\n"
        "Return JSON only."
    )
    return [
        ChatMessage(role="system", content=JUDGE_SYSTEM_PROMPT),
        ChatMessage(role="user", content=content),
    ]


def _percentile(values: list[float], percentile: int) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile / 100 * len(ordered)) - 1)
    return round(ordered[index], 2)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


async def _mark_failed(session: AsyncSession, run_id: UUID, code: str) -> None:
    run = await session.get(EvalRun, run_id)
    if run is not None:
        run.status = "failed"
        run.error_code = code
        run.finished_at = datetime.now(UTC)
    await session.commit()
    metrics.inc_counter(
        "ai_power_knowledge_eval_runs_total", status="failed", code=code
    )
