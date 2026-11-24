"""Small memory retrieval evaluation set: cases, runs and metrics."""

import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.metrics import metrics
from app.models import AgentMemory, MemoryEvalCase, MemoryEvalRun
from app.providers.base import ChatMessage
from app.providers.registry import ProviderRegistry
from app.services.evaluation_runner import parse_judge_response
from app.services.memories import select_memories
from app.services.memory_extraction import resolve_memory_model
from app.services.model_stream import ModelCompletion
from app.services.provider_configs import build_user_registry
from app.services.usage_ledger import SOURCE_MEMORY_EVAL

MAX_CASES = 200
MAX_ANSWER_CASES = 50
DEFAULT_TOP_K = 5
MAX_CHARS = 6000
ANSWER_SYSTEM_PROMPT = (
    "You are a helpful assistant. Answer the user question concisely. "
    "Use the provided long-term memory notes only when they are relevant; "
    "do not invent facts and do not mention the notes unless useful."
)
JUDGE_SYSTEM_PROMPT = (
    "You score an answer to a user question. "
    "Score 1-5 for correctness and relevance. "
    "When memory notes are provided, faithful means the answer is consistent with them; "
    "when no notes are provided, faithful means the answer makes no unsupported claims. "
    "Return exactly one JSON object with keys: score (1-5), faithful (boolean), reason (short)."
)


class MemoryEvalError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def list_cases(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> list[MemoryEvalCase]:
    return list(
        (
            await session.execute(
                select(MemoryEvalCase)
                .where(
                    MemoryEvalCase.workspace_id == workspace_id,
                    MemoryEvalCase.user_id == user_id,
                )
                .order_by(MemoryEvalCase.created_at.desc())
                .limit(MAX_CASES)
            )
        ).scalars()
    )


async def create_case(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    name: str,
    query: str,
    expected_memory_ids: list[UUID],
    project_id: UUID | None = None,
    agent_id: UUID | None = None,
    notes: str = "",
) -> MemoryEvalCase:
    if not query.strip():
        raise MemoryEvalError("invalid_case", "Query is required")
    if expected_memory_ids:
        rows = list(
            (
                await session.execute(
                    select(AgentMemory.id).where(
                        AgentMemory.workspace_id == workspace_id,
                        AgentMemory.user_id == user_id,
                        AgentMemory.id.in_(expected_memory_ids),
                    )
                )
            ).scalars()
        )
        if len(set(rows)) != len(set(expected_memory_ids)):
            raise MemoryEvalError(
                "invalid_expected_memory", "Expected memory not found"
            )
    row = MemoryEvalCase(
        workspace_id=workspace_id,
        user_id=user_id,
        name=name.strip()[:120] or query.strip()[:60],
        query=query.strip(),
        expected_memory_ids=[str(item) for item in expected_memory_ids],
        project_id=project_id,
        agent_id=agent_id,
        notes=notes.strip()[:500],
    )
    session.add(row)
    await session.flush()
    return row


async def delete_case(
    session: AsyncSession, workspace_id: UUID, user_id: UUID, case_id: UUID
) -> None:
    row = (
        await session.execute(
            select(MemoryEvalCase).where(
                MemoryEvalCase.id == case_id,
                MemoryEvalCase.workspace_id == workspace_id,
                MemoryEvalCase.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise MemoryEvalError("not_found", "Evaluation case not found")
    await session.delete(row)
    await session.flush()


async def _complete(
    provider,
    model: str,
    *,
    workspace_id: UUID,
    user_id: UUID,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
) -> tuple[str | None, str | None]:
    completion = ModelCompletion(
        provider=provider,
        model=model,
        messages=[
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=user_prompt),
        ],
        opts={"temperature": 0, "max_tokens": max_tokens},
        workspace_id=workspace_id,
        user_id=user_id,
        source=SOURCE_MEMORY_EVAL,
    )
    result = await completion.run()
    if result.status != "completed":
        return None, result.error_code or "memory_eval_completion_failed"
    return result.content, None


async def _generate_answer(
    provider,
    model: str,
    *,
    workspace_id: UUID,
    user_id: UUID,
    question: str,
    memory_block: str,
) -> tuple[str | None, str | None]:
    notes = memory_block.strip() or "(none)"
    return await _complete(
        provider,
        model,
        workspace_id=workspace_id,
        user_id=user_id,
        system_prompt=ANSWER_SYSTEM_PROMPT,
        user_prompt=f"Memory notes:\n{notes}\n\nQuestion: {question}",
        max_tokens=800,
    )


async def _judge_answer(
    provider,
    model: str,
    *,
    workspace_id: UUID,
    user_id: UUID,
    question: str,
    answer: str,
    memory_block: str,
) -> tuple[int | None, bool | None, str | None]:
    notes = memory_block.strip() or "(none)"
    content, error = await _complete(
        provider,
        model,
        workspace_id=workspace_id,
        user_id=user_id,
        system_prompt=JUDGE_SYSTEM_PROMPT,
        user_prompt=(
            f"Memory notes:\n{notes}\n\nQuestion: {question}\n\n"
            f"Answer:\n{answer}"
        ),
        max_tokens=400,
    )
    if content is None:
        return None, None, error
    try:
        score, faithful, _reason = parse_judge_response(content)
    except Exception:
        return None, None, "judge_bad_response"
    return score, faithful, None


async def run_evaluation(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    *,
    top_k: int = DEFAULT_TOP_K,
    generate_answers: bool = False,
    provider_id: str | None = None,
    model: str | None = None,
    registry: ProviderRegistry | None = None,
    settings: Settings | None = None,
) -> MemoryEvalRun:
    cases = await list_cases(session, workspace_id, user_id)
    if not cases:
        raise MemoryEvalError("no_cases", "Add at least one evaluation case first")
    truncated = False
    if generate_answers and len(cases) > MAX_ANSWER_CASES:
        cases = cases[:MAX_ANSWER_CASES]
        truncated = True

    provider = None
    resolved_provider = None
    resolved_model = None
    active_settings = settings or get_settings()
    if generate_answers:
        resolved_provider = provider_id or active_settings.memory_extraction_provider_id.strip()
        resolved_model = model or active_settings.memory_extraction_model.strip()
        if not resolved_provider or not resolved_model:
            resolved_provider, resolved_model = await resolve_memory_model(
                session, active_settings, None
            )
        if not resolved_provider or not resolved_model:
            raise MemoryEvalError(
                "provider_not_configured",
                "Configure a model before running answer evaluation",
            )
        active_registry = registry
        if active_registry is None:
            active_registry = await build_user_registry(
                session, workspace_id, user_id
            )
        try:
            provider = active_registry.get(resolved_provider)
        except Exception:
            raise MemoryEvalError(
                "provider_unavailable", "Answer evaluation provider is unavailable"
            ) from None

    started = time.perf_counter()
    results: list[dict[str, object]] = []
    total_precision = 0.0
    total_recall = 0.0
    total_mrr = 0.0
    hits_cases = 0
    answer_scores_with: list[int] = []
    answer_scores_without: list[int] = []
    faithful_with: list[bool] = []
    faithful_without: list[bool] = []
    answer_errors = 0
    for case in cases:
        allowed_scopes = {"global"}
        if case.project_id is not None:
            allowed_scopes.add("project")
        if case.agent_id is not None:
            allowed_scopes.add("agent")
        selection = await select_memories(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            agent_id=case.agent_id,
            project_id=case.project_id,
            query=case.query,
            limit=top_k,
            max_chars=MAX_CHARS,
            allowed_scopes=allowed_scopes,
        )
        retrieved = [str(item.memory.id) for item in selection.items]
        expected = [str(item) for item in case.expected_memory_ids or []]
        hits = [item for item in retrieved if item in expected]
        precision = len(hits) / len(retrieved) if retrieved else 0.0
        recall = len(hits) / len(expected) if expected else 0.0
        reciprocal_rank = 0.0
        for index, item in enumerate(retrieved, start=1):
            if item in expected:
                reciprocal_rank = 1.0 / index
                break
        if hits:
            hits_cases += 1
        total_precision += precision
        total_recall += recall
        total_mrr += reciprocal_rank
        row: dict[str, object] = {
            "case_id": str(case.id),
            "name": case.name,
            "query": case.query,
            "expected_ids": expected,
            "retrieved_ids": retrieved,
            "hits": hits,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "mrr": round(reciprocal_rank, 4),
        }
        if generate_answers and provider is not None:
            with_memory, with_error = await _generate_answer(
                provider,
                resolved_model or "",
                workspace_id=workspace_id,
                user_id=user_id,
                question=case.query,
                memory_block=selection.block,
            )
            without_memory, without_error = await _generate_answer(
                provider,
                resolved_model or "",
                workspace_id=workspace_id,
                user_id=user_id,
                question=case.query,
                memory_block="",
            )
            row["answer_with_memory"] = with_memory
            row["answer_without"] = without_memory
            if with_error or without_error:
                answer_errors += 1
                row["answer_error"] = with_error or without_error
            if with_memory:
                score, faithful, judge_error = await _judge_answer(
                    provider,
                    resolved_model or "",
                    workspace_id=workspace_id,
                    user_id=user_id,
                    question=case.query,
                    answer=with_memory,
                    memory_block=selection.block,
                )
                row["score_with_memory"] = score
                row["faithful_with_memory"] = faithful
                if judge_error:
                    answer_errors += 1
                    row["judge_error_with_memory"] = judge_error
                if score is not None:
                    answer_scores_with.append(score)
                if faithful is not None:
                    faithful_with.append(faithful)
            if without_memory:
                score, faithful, judge_error = await _judge_answer(
                    provider,
                    resolved_model or "",
                    workspace_id=workspace_id,
                    user_id=user_id,
                    question=case.query,
                    answer=without_memory,
                    memory_block="",
                )
                row["score_without_memory"] = score
                row["faithful_without_memory"] = faithful
                if judge_error:
                    answer_errors += 1
                    row["judge_error_without_memory"] = judge_error
                if score is not None:
                    answer_scores_without.append(score)
                if faithful is not None:
                    faithful_without.append(faithful)
            if (
                row.get("score_with_memory") is not None
                and row.get("score_without_memory") is not None
            ):
                row["answer_lift"] = round(
                    int(row["score_with_memory"]) - int(row["score_without_memory"]),
                    2,
                )
        results.append(row)

    count = len(cases)

    def average(values: list[int]) -> float | None:
        return round(sum(values) / len(values), 2) if values else None

    def rate(values: list[bool]) -> float | None:
        return round(sum(1 for value in values if value) / len(values), 4) if values else None

    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    metrics_payload: dict[str, object] = {
        "precision": round(total_precision / count, 4),
        "recall": round(total_recall / count, 4),
        "mrr": round(total_mrr / count, 4),
        "hit_rate": round(hits_cases / count, 4),
        "top_k": top_k,
        "generate_answers": generate_answers,
        "cases_truncated": truncated,
    }
    if generate_answers:
        metrics_payload.update(
            {
                "provider_id": resolved_provider,
                "model": resolved_model,
                "answer_score_with_memory": average(answer_scores_with),
                "answer_score_without_memory": average(answer_scores_without),
                "answer_lift": (
                    round(
                        (average(answer_scores_with) or 0.0)
                        - (average(answer_scores_without) or 0.0),
                        2,
                    )
                    if answer_scores_with and answer_scores_without
                    else None
                ),
                "faithful_rate_with_memory": rate(faithful_with),
                "faithful_rate_without_memory": rate(faithful_without),
                "answer_judge_errors": answer_errors,
            }
        )
    run = MemoryEvalRun(
        workspace_id=workspace_id,
        user_id=user_id,
        status="completed",
        cases_count=count,
        metrics=metrics_payload,
        results=results,
        duration_ms=duration_ms,
    )
    session.add(run)
    await session.flush()
    metrics.inc_counter("ai_power_memory_eval_runs_total", status="completed")
    return run


async def list_runs(
    session: AsyncSession, workspace_id: UUID, user_id: UUID, *, limit: int = 20
) -> list[MemoryEvalRun]:
    return list(
        (
            await session.execute(
                select(MemoryEvalRun)
                .where(
                    MemoryEvalRun.workspace_id == workspace_id,
                    MemoryEvalRun.user_id == user_id,
                )
                .order_by(MemoryEvalRun.created_at.desc())
                .limit(max(1, min(limit, 100)))
            )
        ).scalars()
    )