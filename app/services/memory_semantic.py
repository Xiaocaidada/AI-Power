"""Opt-in LLM semantic contradiction detection for long-term memories."""

import json
import logging
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.metrics import metrics
from app.models import AgentMemory, MemoryOptimization
from app.providers.base import ChatMessage
from app.providers.registry import ProviderRegistry
from app.services.memories import get_memory_settings
from app.services.memory_extraction import resolve_memory_model
from app.services.memory_linking import memory_similarity, scope_compatible
from app.services.memory_quality import QualityError
from app.services.model_stream import ModelCompletion
from app.services.provider_configs import build_user_registry
from app.services.usage_ledger import SOURCE_MEMORY_QUALITY

logger = logging.getLogger(__name__)

MAX_PAIRS = 12
MAX_MEMORIES = 60
MIN_CONFIDENCE = 0.6
SEMANTIC_SYSTEM_PROMPT = (
    "You review pairs of long-term memories for factual contradictions. "
    "A contradiction means the two memories cannot both be true at the same time "
    "(different values, opposite preferences, conflicting decisions), not merely "
    "different topics or different levels of detail. "
    "Return ONLY a JSON array. Each item has keys: "
    "pair_id (string), contradicts (boolean), confidence (0-1), reason (short). "
    "Only include pairs where contradicts is true. Return [] when none contradict."
)


class SemanticPairVerdict(BaseModel):
    pair_id: str
    contradicts: bool = False
    confidence: float = Field(default=0, ge=0, le=1)
    reason: str = ""


def _pair_score(left: AgentMemory, right: AgentMemory) -> float:
    score = memory_similarity(left, right)
    shared_tags = set(left.tags or []) & set(right.tags or [])
    if shared_tags:
        score += 0.1 * min(len(shared_tags), 3)
    return score


def _select_pairs(
    memories: list[AgentMemory], limit: int
) -> list[tuple[AgentMemory, AgentMemory]]:
    candidates: list[tuple[float, AgentMemory, AgentMemory]] = []
    for index, left in enumerate(memories):
        for right in memories[index + 1 :]:
            if left.category != right.category:
                continue
            if not scope_compatible(left, right):
                continue
            candidates.append((_pair_score(left, right), left, right))
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [(left, right) for _, left, right in candidates[: max(1, limit)]]


def _parse_verdicts(content: str) -> list[SemanticPairVerdict]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("[")
        end = content.rfind("]")
        if start < 0 or end <= start:
            return []
        try:
            data = json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            return []
    if isinstance(data, dict):
        data = data.get("pairs") or data.get("results") or []
    if not isinstance(data, list):
        return []
    verdicts: list[SemanticPairVerdict] = []
    for item in data:
        try:
            verdicts.append(SemanticPairVerdict.model_validate(item))
        except ValidationError:
            continue
    return verdicts


async def _pending_pairs(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> set[tuple[str, str]]:
    rows = (
        await session.execute(
            select(MemoryOptimization.memory_ids).where(
                MemoryOptimization.workspace_id == workspace_id,
                MemoryOptimization.user_id == user_id,
                MemoryOptimization.kind == "resolve_conflict",
                MemoryOptimization.status == "pending",
            )
        )
    ).scalars()
    pairs: set[tuple[str, str]] = set()
    for ids in rows:
        cleaned = sorted(str(item) for item in ids or [])
        if len(cleaned) >= 2:
            pairs.add((cleaned[0], cleaned[1]))
    return pairs


async def detect_semantic_contradictions(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    *,
    provider_id: str | None = None,
    model: str | None = None,
    limit: int = MAX_PAIRS,
    registry: ProviderRegistry | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    current = settings or get_settings()
    memory_settings = await get_memory_settings(session, workspace_id, user_id)
    if not memory_settings.enabled:
        raise QualityError("memory_disabled", "Memory hub is disabled")
    memories = list(
        (
            await session.execute(
                select(AgentMemory)
                .where(
                    AgentMemory.workspace_id == workspace_id,
                    AgentMemory.user_id == user_id,
                    AgentMemory.status == "active",
                )
                .order_by(AgentMemory.importance.desc(), AgentMemory.updated_at.desc())
                .limit(MAX_MEMORIES)
            )
        ).scalars()
    )
    pairs = _select_pairs(memories, min(max(limit, 1), MAX_PAIRS))
    if not pairs:
        return {
            "pairs_checked": 0,
            "contradictions": 0,
            "suggestions": [],
            "provider_id": None,
            "model": None,
        }

    resolved_provider, resolved_model = provider_id, model
    if not resolved_provider or not resolved_model:
        resolved_provider, resolved_model = await resolve_memory_model(
            session, current, None
        )
    if not resolved_provider or not resolved_model:
        raise QualityError(
            "provider_not_configured",
            "Configure MEMORY_EXTRACTION_PROVIDER_ID/MODEL or enable a catalog model",
        )
    active_registry = registry
    if active_registry is None:
        active_registry = await build_user_registry(session, workspace_id, user_id)
    try:
        provider = active_registry.get(resolved_provider)
    except Exception:
        raise QualityError(
            "provider_unavailable", "Semantic analysis provider is not available"
        ) from None

    payload = [
        {
            "pair_id": str(index),
            "category": left.category,
            "left_title": left.title,
            "left_content": left.content,
            "right_title": right.title,
            "right_content": right.content,
        }
        for index, (left, right) in enumerate(pairs)
    ]
    completion = ModelCompletion(
        provider=provider,
        model=resolved_model,
        messages=[
            ChatMessage(role="system", content=SEMANTIC_SYSTEM_PROMPT),
            ChatMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
        ],
        opts={"temperature": 0, "max_tokens": 1200},
        workspace_id=workspace_id,
        user_id=user_id,
        source=SOURCE_MEMORY_QUALITY,
    )
    result = await completion.run()
    if result.status != "completed":
        metrics.inc_counter(
            "ai_power_memory_semantic_checks_total", status="failed"
        )
        raise QualityError(
            "semantic_analysis_failed",
            result.error_code or "Semantic analysis model call failed",
        )

    verdicts = _parse_verdicts(result.content)
    existing = await _pending_pairs(session, workspace_id, user_id)
    suggestions: list[MemoryOptimization] = []
    contradictions = 0
    for verdict in verdicts:
        if not verdict.contradicts or verdict.confidence < MIN_CONFIDENCE:
            continue
        try:
            index = int(verdict.pair_id)
        except ValueError:
            continue
        if index < 0 or index >= len(pairs):
            continue
        left, right = pairs[index]
        key = (str(min(left.id, right.id)), str(max(left.id, right.id)))
        contradictions += 1
        if key in existing:
            continue
        existing.add(key)
        loser = min(
            (left, right), key=lambda item: (item.importance, item.use_count)
        )
        keeper = right if loser.id == left.id else left
        suggestion = MemoryOptimization(
            workspace_id=workspace_id,
            user_id=user_id,
            kind="resolve_conflict",
            status="pending",
            title="深度分析发现的冲突记忆",
            reason=verdict.reason[:2000] or "语义分析判断两条记忆互相矛盾。",
            expected_effect="保留更重要的一条，归档冲突项，避免矛盾上下文。",
            memory_ids=[str(keeper.id), str(loser.id)],
            payload={
                "keep_id": str(keeper.id),
                "archive_id": str(loser.id),
                "semantic": True,
                "confidence": verdict.confidence,
            },
        )
        session.add(suggestion)
        suggestions.append(suggestion)
    await session.flush()
    metrics.inc_counter(
        "ai_power_memory_semantic_checks_total", status="completed"
    )
    metrics.inc_counter(
        "ai_power_memory_semantic_contradictions_total", contradictions
    )
    return {
        "pairs_checked": len(pairs),
        "contradictions": contradictions,
        "suggestions": suggestions,
        "provider_id": resolved_provider,
        "model": resolved_model,
    }