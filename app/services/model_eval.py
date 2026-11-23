import asyncio
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update

from app.db import SessionLocal
from app.models import (
    ModelEvalItem,
    ModelEvalQuestion,
    ModelEvalRun,
    ModelEvalScore,
)
from app.providers.base import ChatMessage, ProviderError
from app.providers.registry import ProviderRegistry
from app.services.model_stream import ModelCompletion
from app.services.provider_configs import build_user_registry
from app.services.usage_ledger import SOURCE_MODEL_EVAL

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EvalQuestionView:
    question: str
    reference_answer: str
    scoring_criteria: str
    expected_keywords: list[str]
    regex: str


def _clamp_settings(parameters: dict) -> dict[str, object]:
    result: dict[str, object] = {}
    mapping = {"temperature": (0.0, 2.0), "max_tokens": (1, 32768), "top_p": (0.0, 1.0)}
    for key, (low, high) in mapping.items():
        value = parameters.get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        result[key] = max(low, min(high, int(number) if key == "max_tokens" else number))
    return result


def _rule_score(question: EvalQuestionView, answer: str) -> tuple[bool, str]:
    text = answer.casefold()
    keywords = [item for item in (question.expected_keywords or []) if item]
    missing = [item for item in keywords if item.casefold() not in text]
    regex_ok = True
    if question.regex:
        try:
            regex_ok = re.search(question.regex, answer) is not None
        except re.error:
            regex_ok = False
    passed = not missing and regex_ok
    reasons: list[str] = []
    if missing:
        reasons.append("missing: " + ", ".join(missing))
    if not regex_ok:
        reasons.append("regex mismatch")
    return passed, "; ".join(reasons) if reasons else "rule passed"


async def _ai_score(
    registry: ProviderRegistry,
    config: dict,
    question: EvalQuestionView,
    item: ModelEvalItem,
    workspace_id: UUID,
    user_id: UUID,
) -> tuple[float | None, bool | None, str]:
    provider_id = config.get("judge_provider_id")
    model = config.get("judge_model")
    if not provider_id or not model:
        return None, None, "judge model not configured"
    try:
        provider = registry.get(str(provider_id))
    except ProviderError:
        return None, None, "judge provider unavailable"
    prompt = (
        "You are an evaluation judge. Return ONLY JSON: "
        '{"score": 1-5, "faithful": true/false, "reason": "..."}.\n'
        f"Question:\n{question.question}\n\n"
        f"Reference answer:\n{question.reference_answer or '(none)'}\n\n"
        f"Scoring criteria:\n{question.scoring_criteria or '(none)'}\n\n"
        f"Answer to evaluate:\n{item.answer}"
    )
    completion = ModelCompletion(
        provider=provider,
        model=str(model),
        messages=[ChatMessage(role="user", content=prompt)],
        opts={"temperature": 0.0, "max_tokens": 300},
        workspace_id=workspace_id,
        user_id=user_id,
        source=SOURCE_MODEL_EVAL,
    )
    metrics = await completion.run()
    if metrics.status != "completed":
        return None, None, f"judge failed: {metrics.error_code or 'unknown'}"
    raw = metrics.content
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match is None:
        return None, None, "judge returned invalid JSON"
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, None, "judge returned invalid JSON"
    score = payload.get("score")
    faithful = payload.get("faithful")
    reason = str(payload.get("reason", ""))[:1000]
    try:
        numeric = float(score)
    except (TypeError, ValueError):
        return None, None, reason or "judge score missing"
    return max(0.0, min(5.0, numeric)), bool(faithful), reason


async def _execute_item(
    item_id: UUID,
    registry: ProviderRegistry,
    config: dict,
) -> None:
    async with SessionLocal() as session:
        item = await session.get(ModelEvalItem, item_id)
        if item is None or item.status != "queued":
            return
        run = await session.get(ModelEvalRun, item.run_id)
        if run is None or run.cancel_requested_at is not None:
            return
        snapshot = item.scoring_snapshot or {}
        live_question = None
        if not snapshot:
            live_question = await session.get(ModelEvalQuestion, item.question_id)
            if live_question is None:
                item.status = "failed"
                item.error_code = "question_missing"
                await session.commit()
                return
        question = EvalQuestionView(
            question=item.question_snapshot,
            reference_answer=item.reference_snapshot,
            scoring_criteria=str(
                snapshot.get("scoring_criteria")
                if snapshot
                else (live_question.scoring_criteria if live_question else "")
            ),
            expected_keywords=[
                str(value)
                for value in (
                    snapshot.get("expected_keywords", [])
                    if snapshot
                    else (live_question.expected_keywords if live_question else [])
                )
            ],
            regex=str(
                snapshot.get("regex")
                if snapshot
                else (live_question.regex if live_question else "")
            ),
        )
        item.status = "running"
        await session.commit()
        await session.execute(
            update(ModelEvalRun)
            .where(ModelEvalRun.id == run.id)
            .values(progress_running=ModelEvalRun.progress_running + 1)
        )
        await session.commit()

        workspace_id = run.workspace_id
        user_id = run.user_id
        try:
            provider = registry.get(item.provider_id)
        except ProviderError:
            provider = None

        if provider is None:
            item.status = "failed"
            item.error_code = "provider_unavailable"
            await session.execute(
                update(ModelEvalRun)
                .where(ModelEvalRun.id == run.id)
                .values(
                    progress_running=ModelEvalRun.progress_running - 1,
                    progress_done=ModelEvalRun.progress_done + 1,
                    progress_failed=ModelEvalRun.progress_failed + 1,
                )
            )
            await session.commit()
            return

        completion = ModelCompletion(
            provider=provider,
            model=item.model,
            messages=[ChatMessage(role="user", content=item.question_snapshot)],
            opts=_clamp_settings(config.get("parameters") or {}),
            workspace_id=workspace_id,
            user_id=user_id,
            source=SOURCE_MODEL_EVAL,
        )
        metrics = await completion.run()

        item.answer = metrics.content
        item.status = "completed" if metrics.status == "completed" else "failed"
        item.error_code = metrics.error_code
        item.prompt_tokens = metrics.prompt_tokens
        item.completion_tokens = metrics.completion_tokens
        item.cost = metrics.cost
        item.ttft_ms = metrics.total_ms
        item.latency_ms = metrics.total_ms

        methods = set(config.get("methods") or [])
        if "rule" in methods and item.status == "completed":
            passed, reason = _rule_score(question, item.answer)
            await session.execute(
                delete(ModelEvalScore).where(
                    ModelEvalScore.item_id == item.id,
                    ModelEvalScore.method == "rule",
                )
            )
            session.add(
                ModelEvalScore(
                    item_id=item.id,
                    method="rule",
                    score=1.0 if passed else 0.0,
                    passed=passed,
                    reason=reason,
                )
            )
            # Release the write transaction before the judge call writes usage.
            await session.commit()
        if "ai" in methods and item.status == "completed":
            score, faithful, reason = await _ai_score(
                registry, config, question, item, workspace_id, user_id
            )
            await session.execute(
                delete(ModelEvalScore).where(
                    ModelEvalScore.item_id == item.id,
                    ModelEvalScore.method == "ai",
                )
            )
            session.add(
                ModelEvalScore(
                    item_id=item.id,
                    method="ai",
                    score=score,
                    passed=faithful,
                    reason=reason,
                    judge_provider_id=config.get("judge_provider_id"),
                    judge_model=config.get("judge_model"),
                )
            )

        failed = item.status != "completed"
        await session.execute(
            update(ModelEvalRun)
            .where(ModelEvalRun.id == run.id)
            .values(
                progress_running=ModelEvalRun.progress_running - 1,
                progress_done=ModelEvalRun.progress_done + 1,
                progress_failed=ModelEvalRun.progress_failed + (1 if failed else 0),
                current_model=item.model,
            )
        )
        await session.commit()


def _aggregate(items: list[ModelEvalItem], scores: list[ModelEvalScore]) -> dict[str, Any]:
    scores_by_item: dict[UUID, list[ModelEvalScore]] = defaultdict(list)
    for score in scores:
        scores_by_item[score.item_id].append(score)
    grouped: dict[str, list[ModelEvalItem]] = defaultdict(list)
    for item in items:
        grouped[f"{item.provider_id}/{item.model}"].append(item)
    result: dict[str, Any] = {"models": {}}
    for key, rows in grouped.items():
        completed = [item for item in rows if item.status == "completed"]
        rule_scores = [
            score
            for item in rows
            for score in scores_by_item.get(item.id, [])
            if score.method == "rule" and score.passed is not None
        ]
        ai_scores = [
            score.score
            for item in rows
            for score in scores_by_item.get(item.id, [])
            if score.method == "ai" and score.score is not None
        ]
        manual_scores = [
            score.score
            for item in rows
            for score in scores_by_item.get(item.id, [])
            if score.method == "manual" and score.score is not None
        ]
        ttfts = [item.ttft_ms for item in completed if item.ttft_ms is not None]
        latencies = [item.latency_ms for item in completed if item.latency_ms is not None]
        result["models"][key] = {
            "total": len(rows),
            "completed": len(completed),
            "failed": len(rows) - len(completed),
            "success_rate": len(completed) / len(rows) if rows else 0,
            "rule_pass_rate": (
                sum(1 for score in rule_scores if score.passed) / len(rule_scores)
                if rule_scores
                else None
            ),
            "rule_scored": len(rule_scores),
            "ai_avg_score": sum(ai_scores) / len(ai_scores) if ai_scores else None,
            "ai_scored": len(ai_scores),
            "ai_unscored": max(0, len(completed) - len(ai_scores)),
            "manual_avg_score": (
                sum(manual_scores) / len(manual_scores) if manual_scores else None
            ),
            "manual_scored": len(manual_scores),
            "avg_ttft_ms": sum(ttfts) / len(ttfts) if ttfts else None,
            "avg_latency_ms": sum(latencies) / len(latencies) if latencies else None,
            "prompt_tokens": sum(item.prompt_tokens or 0 for item in rows),
            "completion_tokens": sum(item.completion_tokens or 0 for item in rows),
            "cost": sum(item.cost for item in rows),
        }
    return result


async def execute_model_eval_run(
    run_id: UUID, provider_registry: ProviderRegistry | None = None
) -> None:
    async with SessionLocal() as session:
        run = await session.get(ModelEvalRun, run_id)
        if run is None or run.status not in ("queued", "running"):
            return
        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.cancel_requested_at = None
        await session.commit()
        config = dict(run.config)
        registry = provider_registry or await build_user_registry(
            session, run.workspace_id, run.user_id
        )

    async with SessionLocal() as session:
        items = list(
            (
                await session.execute(
                    select(ModelEvalItem)
                    .where(ModelEvalItem.run_id == run_id, ModelEvalItem.status == "queued")
                    .order_by(ModelEvalItem.created_at, ModelEvalItem.id)
                )
            ).scalars()
        )

    concurrency = max(1, min(5, int(config.get("concurrency", 3))))
    semaphore = asyncio.Semaphore(concurrency)

    async def guarded(item_id: UUID) -> None:
        async with semaphore:
            await _execute_item(item_id, registry, config)

    try:
        await asyncio.gather(*(guarded(item.id) for item in items))
    except Exception:
        logger.exception("model eval item execution failed")

    async with SessionLocal() as session:
        run = await session.get(ModelEvalRun, run_id)
        if run is None:
            return
        items = list(
            (
                await session.execute(
                    select(ModelEvalItem).where(ModelEvalItem.run_id == run_id)
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
        run.metrics = _aggregate(items, scores)
        run.progress_running = 0
        run.status = "cancelled" if run.cancel_requested_at is not None else "completed"
        run.finished_at = datetime.now(UTC)
        await session.commit()


async def run_model_eval_job(_ctx: dict, run_id: str) -> None:
    await execute_model_eval_run(UUID(run_id))