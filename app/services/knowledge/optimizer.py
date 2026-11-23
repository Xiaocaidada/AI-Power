"""AI-assisted retrieval workflow optimization driven by evaluation results."""

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import metrics
from app.models import (
    AuditLog,
    EvalRun,
    EvalRunItem,
    KnowledgeBase,
    KnowledgeOptimization,
    Workflow,
    WorkflowVersion,
)
from app.providers.base import ChatMessage
from app.providers.registry import ProviderRegistry
from app.services.agent_builder import diff_definitions
from app.services.knowledge.retrieval_catalog import retrieval_builder_manifest
from app.services.knowledge.retrieval_schema import (
    RetrievalValidationError,
    validate_knowledge_retrieval,
)
from app.services.model_stream import ModelCompletion
from app.services.usage_ledger import SOURCE_KNOWLEDGE_EVAL

JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)
MAX_SUGGESTIONS = 12
OPTIMIZER_SYSTEM_PROMPT = (
    "You are the AI Power retrieval optimization architect. "
    "You receive evaluation metrics, failing questions and the current retrieval "
    "workflow definition. Propose concrete, low-risk improvements.\n"
    "Return ONLY one JSON object with keys: summary (string), rationale (string), "
    "suggestions (array of {title, detail}), and definition (optional workflow object).\n"
    "The definition must be a linear retrieval pipeline with exactly one start and one "
    "output node. Use only node types from the manifest. Keep node ids stable when "
    "possible so the diff stays readable. Do not invent providers, models or resources.\n"
)


class KnowledgeOptimizerError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _parse_json(text: str) -> dict[str, Any] | None:
    match = JSON_PATTERN.search(text)
    if match is None:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _normalize_suggestions(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        return []
    normalized: list[dict[str, object]] = []
    for item in raw[:MAX_SUGGESTIONS]:
        if isinstance(item, str) and item.strip():
            normalized.append({"title": item.strip()[:200], "detail": ""})
        elif isinstance(item, dict):
            title = str(item.get("title") or item.get("summary") or "").strip()
            detail = str(item.get("detail") or item.get("description") or "").strip()
            if title or detail:
                normalized.append(
                    {"title": (title or detail)[:200], "detail": detail[:2000]}
                )
    return normalized


def _analysis_context(
    run: EvalRun,
    items: Sequence[EvalRunItem],
    definition: dict[str, object] | None,
) -> str:
    metrics = run.metrics or {}
    failing = sorted(items, key=lambda item: (item.ndcg_at_5, item.hit_rank or 999))[:8]
    payload = {
        "retrieval_mode": metrics.get("retrieval_mode"),
        "metrics": {
            key: metrics.get(key)
            for key in (
                "recall_at_1",
                "recall_at_3",
                "recall_at_5",
                "precision_at_5",
                "recall_at_5_docs",
                "ndcg_at_5",
                "precision_at_10",
                "recall_at_10_docs",
                "ndcg_at_10",
                "mrr",
                "latency_p50_ms",
                "latency_p95_ms",
                "success_rate",
            )
        },
        "node_timing": metrics.get("node_timing"),
        "total_questions": len(items),
        "worst_questions": [
            {
                "question": item.question_text[:500],
                "hit_rank": item.hit_rank,
                "ndcg_at_5": item.ndcg_at_5,
                "recall_at_5": item.recall_at_5,
                "latency_ms": item.latency_ms,
                "error_code": item.error_code,
            }
            for item in failing
        ],
    }
    return (
        "Evaluation analysis:\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\n\nCurrent definition:\n"
        + (
            json.dumps(definition, ensure_ascii=False)
            if definition is not None
            else "(builtin hybrid retrieval; no workflow version was evaluated)"
        )
        + "\n\nNode manifest:\n"
        + retrieval_builder_manifest()
    )


async def _load_base_version(
    session: AsyncSession, run: EvalRun
) -> tuple[Workflow | None, WorkflowVersion | None]:
    if run.retrieval_workflow_version_id is None:
        return None, None
    version = await session.get(WorkflowVersion, run.retrieval_workflow_version_id)
    workflow = await session.get(Workflow, version.workflow_id) if version else None
    if (
        version is None
        or workflow is None
        or workflow.workspace_id != run.workspace_id
        or workflow.kind != "knowledge_retrieval"
        or workflow.deleted_at is not None
    ):
        raise KnowledgeOptimizerError(
            "invalid_retrieval_workflow", "Evaluated retrieval workflow is unavailable"
        )
    return workflow, version


async def generate_optimization(
    session: AsyncSession,
    registry: ProviderRegistry,
    *,
    workspace_id: UUID,
    user_id: UUID,
    kb: KnowledgeBase,
    run: EvalRun,
    provider_id: str,
    model: str,
) -> KnowledgeOptimization:
    if run.workspace_id != workspace_id or run.kb_id != kb.id:
        raise KnowledgeOptimizerError("run_not_found", "Evaluation run not found")
    if run.status != "completed":
        raise KnowledgeOptimizerError(
            "run_not_completed", "Evaluation run must be completed first"
        )
    try:
        provider = registry.get(provider_id)
    except Exception:
        raise KnowledgeOptimizerError(
            "provider_not_found", "Optimizer provider is not available"
        ) from None
    items = list(
        (
            await session.execute(
                select(EvalRunItem)
                .where(EvalRunItem.run_id == run.id)
                .order_by(EvalRunItem.created_at, EvalRunItem.id)
            )
        ).scalars()
    )
    workflow, base_version = await _load_base_version(session, run)
    base_definition = dict(base_version.definition) if base_version is not None else None
    messages = [
        ChatMessage(role="system", content=OPTIMIZER_SYSTEM_PROMPT),
        ChatMessage(
            role="user",
            content=_analysis_context(run, items, base_definition),
        ),
    ]
    last_error = ""
    for _attempt in range(3):
        last_error = ""
        completion = ModelCompletion(
            provider=provider,
            model=model,
            messages=messages,
            opts={"temperature": 0.1, "max_tokens": 5000},
            workspace_id=workspace_id,
            user_id=user_id,
            source=SOURCE_KNOWLEDGE_EVAL,
        )
        completion_metrics = await completion.run()
        if completion_metrics.status != "completed":
            raise KnowledgeOptimizerError(
                completion_metrics.error_code or "optimization_failed",
                "Optimization generation failed",
            )
        payload = _parse_json(completion_metrics.content)
        if payload is None:
            last_error = "Model did not return valid JSON."
        else:
            definition: dict[str, object] | None = None
            raw_definition = payload.get("definition")
            if raw_definition is not None and not isinstance(raw_definition, dict):
                last_error = "definition must be an object."
            elif isinstance(raw_definition, dict):
                try:
                    definition = validate_knowledge_retrieval(raw_definition).model_dump(
                        by_alias=True
                    )
                except RetrievalValidationError as exc:
                    last_error = f"Invalid retrieval definition: {exc}"
            elif base_definition is not None:
                last_error = "Model response is missing definition."
            if last_error:
                pass
            else:
                summary = str(payload.get("summary") or "").strip()[:2000]
                rationale = str(payload.get("rationale") or "").strip()[:8000]
                suggestions = _normalize_suggestions(payload.get("suggestions"))
                if definition is None and not suggestions:
                    last_error = "Response contains neither suggestions nor definition."
                else:
                    optimization = KnowledgeOptimization(
                        workspace_id=workspace_id,
                        kb_id=kb.id,
                        eval_run_id=run.id,
                        workflow_id=workflow.id if workflow is not None else None,
                        base_version_id=base_version.id if base_version is not None else None,
                        created_by=user_id,
                        status="proposed",
                        summary=summary or "Retrieval optimization proposal",
                        rationale=rationale,
                        suggestions=suggestions,
                        proposed_definition=definition,
                        diff=(
                            diff_definitions(base_definition, definition)
                            if base_definition is not None and definition is not None
                            else None
                        ),
                        metrics_snapshot=dict(run.metrics or {}),
                        provider_id=provider_id,
                        model=model,
                    )
                    session.add(optimization)
                    await session.commit()
                    await session.refresh(optimization)
                    metrics.inc_counter(
                        "ai_power_knowledge_optimizations_total", action="generated"
                    )
                    return optimization
        messages.append(
            ChatMessage(
                role="user",
                content=(
                    "The previous output was invalid for these reasons:\n"
                    f"{last_error}\nReturn a corrected JSON object only."
                ),
            )
        )
    raise KnowledgeOptimizerError(
        "invalid_generation", last_error or "Invalid optimization generation"
    )


async def list_optimizations(
    session: AsyncSession, *, workspace_id: UUID, kb_id: UUID, limit: int = 50
) -> list[KnowledgeOptimization]:
    return list(
        (
            await session.execute(
                select(KnowledgeOptimization)
                .where(
                    KnowledgeOptimization.workspace_id == workspace_id,
                    KnowledgeOptimization.kb_id == kb_id,
                )
                .order_by(KnowledgeOptimization.created_at.desc())
                .limit(limit)
            )
        ).scalars()
    )


async def get_optimization(
    session: AsyncSession, *, workspace_id: UUID, kb_id: UUID, optimization_id: UUID
) -> KnowledgeOptimization:
    row = (
        await session.execute(
            select(KnowledgeOptimization).where(
                KnowledgeOptimization.id == optimization_id,
                KnowledgeOptimization.workspace_id == workspace_id,
                KnowledgeOptimization.kb_id == kb_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise KnowledgeOptimizerError("not_found", "Optimization not found")
    return row


async def apply_optimization(
    session: AsyncSession,
    *,
    optimization: KnowledgeOptimization,
    kb: KnowledgeBase,
    user_id: UUID,
) -> WorkflowVersion:
    if optimization.status != "proposed":
        raise KnowledgeOptimizerError(
            "invalid_status", "Only proposed optimizations can be applied"
        )
    if optimization.proposed_definition is None:
        raise KnowledgeOptimizerError(
            "no_definition", "This optimization contains suggestions only"
        )
    workflow = (
        await session.get(Workflow, optimization.workflow_id)
        if optimization.workflow_id is not None
        else None
    )
    if (
        workflow is None
        or workflow.workspace_id != optimization.workspace_id
        or workflow.kind != "knowledge_retrieval"
        or workflow.deleted_at is not None
    ):
        raise KnowledgeOptimizerError(
            "invalid_workflow", "Target retrieval workflow is unavailable"
        )
    try:
        definition = validate_knowledge_retrieval(optimization.proposed_definition)
    except RetrievalValidationError as exc:
        raise KnowledgeOptimizerError(
            "invalid_definition", f"Proposed definition is invalid: {exc}"
        ) from None
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
    await session.flush()
    optimization.previous_binding_version_id = kb.retrieval_workflow_version_id
    kb.retrieval_workflow_version_id = version.id
    optimization.applied_version_id = version.id
    optimization.status = "applied"
    optimization.applied_at = datetime.now(UTC)
    session.add(
        AuditLog(
            actor_user_id=user_id,
            action="workflow.publish",
            target_type="workflow",
            target_id=str(workflow.id),
            detail={
                "version": version.version,
                "name": workflow.name,
                "source": "knowledge_optimization",
                "optimization_id": str(optimization.id),
            },
        )
    )
    await session.commit()
    await session.refresh(version)
    await session.refresh(optimization)
    metrics.inc_counter("ai_power_knowledge_optimizations_total", action="applied")
    return version


async def rollback_optimization(
    session: AsyncSession,
    *,
    optimization: KnowledgeOptimization,
    kb: KnowledgeBase,
) -> None:
    if optimization.status != "applied":
        raise KnowledgeOptimizerError(
            "invalid_status", "Only applied optimizations can be rolled back"
        )
    if kb.retrieval_workflow_version_id != optimization.applied_version_id:
        raise KnowledgeOptimizerError(
            "binding_changed",
            "Knowledge base retrieval binding changed after this optimization",
        )
    kb.retrieval_workflow_version_id = optimization.previous_binding_version_id
    optimization.status = "reverted"
    optimization.reverted_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(optimization)
    metrics.inc_counter("ai_power_knowledge_optimizations_total", action="reverted")


async def dismiss_optimization(
    session: AsyncSession, *, optimization: KnowledgeOptimization
) -> None:
    if optimization.status != "proposed":
        raise KnowledgeOptimizerError(
            "invalid_status", "Only proposed optimizations can be dismissed"
        )
    optimization.status = "dismissed"
    await session.commit()
    await session.refresh(optimization)
    metrics.inc_counter("ai_power_knowledge_optimizations_total", action="dismissed")