"""Small memory retrieval evaluation set: cases, runs and metrics."""

import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import metrics
from app.models import AgentMemory, MemoryEvalCase, MemoryEvalRun
from app.services.memories import select_memories

MAX_CASES = 200
DEFAULT_TOP_K = 5
MAX_CHARS = 6000


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


async def run_evaluation(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    *,
    top_k: int = DEFAULT_TOP_K,
) -> MemoryEvalRun:
    cases = await list_cases(session, workspace_id, user_id)
    if not cases:
        raise MemoryEvalError("no_cases", "Add at least one evaluation case first")
    started = time.perf_counter()
    results: list[dict[str, object]] = []
    total_precision = 0.0
    total_recall = 0.0
    total_mrr = 0.0
    hits_cases = 0
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
        results.append(
            {
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
        )
    count = len(cases)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    run = MemoryEvalRun(
        workspace_id=workspace_id,
        user_id=user_id,
        status="completed",
        cases_count=count,
        metrics={
            "precision": round(total_precision / count, 4),
            "recall": round(total_recall / count, 4),
            "mrr": round(total_mrr / count, 4),
            "hit_rate": round(hits_cases / count, 4),
            "top_k": top_k,
        },
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