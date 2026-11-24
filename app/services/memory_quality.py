"""Memory quality analysis and optimization suggestions with apply/rollback."""

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import metrics
from app.models import AgentMemory, MemoryOptimization, MemoryRelation, MemorySettings
from app.services.memories import (
    create_memory_relation,
    delete_memory_relation,
    update_memory,
)
from app.services.memory_graph import rebuild_memory_graph
from app.services.memory_linking import memory_similarity, scope_compatible

DUPLICATE_THRESHOLD = 0.6
UNUSED_DAYS = 90
INCOMPLETE_CHARS = 12
MAX_ANALYSIS_MEMORIES = 300
MAX_SUGGESTIONS = 20
PREFERENCE_HINTS = (
    "prefer",
    "prefers",
    "concise",
    "偏好",
    "喜欢",
    "简洁",
    "回答风格",
    "style",
)
NEGATIVE_MARKERS = (
    "not ",
    "never",
    "dislike",
    "avoid",
    "不要",
    "不喜欢",
    "禁止",
    "avoid ",
)
POSITIVE_MARKERS = (
    "prefer",
    "like",
    "always",
    "should",
    "使用",
    "喜欢",
    "需要",
    "推荐",
)
USES_PATTERN = re.compile(r"\b(?:uses|use)\s+([A-Za-z0-9_.+-]+)")
ACTIONABLE_KINDS = {
    "merge_duplicates",
    "resolve_conflict",
    "expire_memory",
    "archive_memory",
    "recategorize",
}


class QualityError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _signature(
    kind: str, memory_ids: list[str], payload: dict[str, object]
) -> tuple[str, tuple[str, ...], str, str]:
    return (
        kind,
        tuple(sorted(memory_ids)),
        str(payload.get("target_id") or payload.get("keep_id") or ""),
        str(payload.get("category") or payload.get("status") or ""),
    )


async def _active_memories(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> list[AgentMemory]:
    return list(
        (
            await session.execute(
                select(AgentMemory)
                .where(
                    AgentMemory.workspace_id == workspace_id,
                    AgentMemory.user_id == user_id,
                    AgentMemory.status == "active",
                )
                .order_by(AgentMemory.importance.desc(), AgentMemory.updated_at.desc())
                .limit(MAX_ANALYSIS_MEMORIES)
            )
        ).scalars()
    )


def _duplicate_groups(memories: list[AgentMemory]) -> list[list[AgentMemory]]:
    parent = {memory.id: memory.id for memory in memories}

    def find(node: UUID) -> UUID:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: UUID, right: UUID) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for index, left in enumerate(memories):
        for right in memories[index + 1 :]:
            if not scope_compatible(left, right):
                continue
            if memory_similarity(left, right) >= DUPLICATE_THRESHOLD:
                union(left.id, right.id)
    grouped: dict[UUID, list[AgentMemory]] = {}
    for memory in memories:
        grouped.setdefault(find(memory.id), []).append(memory)
    return [group for group in grouped.values() if len(group) > 1]


def _polarity(text: str) -> int:
    lowered = text.casefold()
    negative = any(marker in lowered for marker in NEGATIVE_MARKERS)
    positive = any(marker in lowered for marker in POSITIVE_MARKERS)
    if negative and not positive:
        return -1
    if positive and not negative:
        return 1
    return 0


def _heuristic_conflicts(
    memories: list[AgentMemory],
) -> list[tuple[AgentMemory, AgentMemory]]:
    pairs: list[tuple[AgentMemory, AgentMemory]] = []
    for index, left in enumerate(memories):
        for right in memories[index + 1 :]:
            if left.content.strip() == right.content.strip():
                continue
            if not scope_compatible(left, right):
                continue
            score = memory_similarity(left, right)
            if score < DUPLICATE_THRESHOLD:
                continue
            left_polarity = _polarity(left.content)
            right_polarity = _polarity(right.content)
            polarity_conflict = (
                left_polarity != 0
                and right_polarity != 0
                and left_polarity != right_polarity
            )
            same_title = (
                left.title.strip().casefold() == right.title.strip().casefold()
                and left.title.strip() != ""
            )
            left_use = USES_PATTERN.search(left.content)
            right_use = USES_PATTERN.search(right.content)
            value_conflict = (
                left_use is not None
                and right_use is not None
                and left_use.group(1).casefold() != right_use.group(1).casefold()
            )
            if polarity_conflict or same_title or value_conflict:
                pairs.append((left, right))
    return pairs


async def _conflict_pairs(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    memory_ids: set[UUID],
) -> list[tuple[AgentMemory, AgentMemory]]:
    rows = list(
        (
            await session.execute(
                select(MemoryRelation).where(
                    MemoryRelation.workspace_id == workspace_id,
                    MemoryRelation.user_id == user_id,
                    MemoryRelation.relation_type == "contradicts",
                    MemoryRelation.from_type == "memory",
                    MemoryRelation.to_type == "memory",
                )
            )
        ).scalars()
    )
    pairs: list[tuple[AgentMemory, AgentMemory]] = []
    for relation in rows:
        if relation.from_id not in memory_ids or relation.to_id not in memory_ids:
            continue
        left = await session.get(AgentMemory, relation.from_id)
        right = await session.get(AgentMemory, relation.to_id)
        if left is not None and right is not None:
            pairs.append((left, right))
    return pairs


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _relation_anomalies(
    memories: list[AgentMemory], relations: list[MemoryRelation]
) -> list[MemoryRelation]:
    anomalies: list[MemoryRelation] = []
    seen: set[tuple[str, str, str]] = set()
    by_id = {memory.id: memory for memory in memories}
    for relation in relations:
        if relation.from_id == relation.to_id:
            anomalies.append(relation)
            continue
        key = (str(relation.from_id), str(relation.to_id), relation.relation_type)
        if key in seen:
            anomalies.append(relation)
            continue
        seen.add(key)
        if relation.relation_type == "contradicts":
            left = by_id.get(relation.from_id)
            right = by_id.get(relation.to_id)
            if left is not None and right is not None:
                if memory_similarity(left, right) >= DUPLICATE_THRESHOLD:
                    anomalies.append(relation)
    return anomalies


def _analysis_payload(
    memories: list[AgentMemory],
    groups: list[list[AgentMemory]],
    conflicts: list[tuple[AgentMemory, AgentMemory]],
    now: datetime,
    relation_anomalies: list[MemoryRelation],
    orphan_ids: list[UUID],
) -> dict[str, object]:
    expired = [
        memory
        for memory in memories
        if memory.valid_until is not None
        and _as_utc(memory.valid_until) <= now
    ]
    unused_cutoff = now - timedelta(days=UNUSED_DAYS)
    unused = [
        memory
        for memory in memories
        if memory.use_count == 0
        and memory.updated_at is not None
        and _as_utc(memory.updated_at) <= unused_cutoff
    ]
    missing_source = [
        memory
        for memory in memories
        if memory.source_type != "manual"
        and memory.source_id is None
        and not (memory.source_ref or {})
    ]
    incomplete = [
        memory for memory in memories if len(memory.content.strip()) < INCOMPLETE_CHARS
    ]
    project_gaps = [
        memory
        for memory in memories
        if memory.category == "project" and memory.project_id is None
    ]
    total = max(len(memories), 1)
    rule_hints: list[str] = []
    if len(groups) / total > 0.15:
        rule_hints.append("high_duplicate_rate")
    if len(conflicts) / total > 0.10:
        rule_hints.append("high_conflict_rate")
    if len(incomplete) / total > 0.30:
        rule_hints.append("many_incomplete")
    if len(unused) / total > 0.40:
        rule_hints.append("many_unused")
    return {
        "total": len(memories),
        "duplicates": len(groups),
        "duplicate_groups": [
            [str(memory.id) for memory in group] for group in groups[:10]
        ],
        "conflicts": len(conflicts),
        "expired": len(expired),
        "unused": len(unused),
        "missing_source": len(missing_source),
        "incomplete": len(incomplete),
        "orphans": len(orphan_ids),
        "relation_anomalies": len(relation_anomalies),
        "project_gaps": len(project_gaps),
        "rule_hints": rule_hints,
        "_expired_ids": [memory.id for memory in expired],
        "_unused_ids": [memory.id for memory in unused],
        "_groups": groups,
        "_conflicts": conflicts,
        "_orphan_ids": orphan_ids,
        "_anomaly_ids": [relation.id for relation in relation_anomalies],
        "_project_gap_ids": [memory.id for memory in project_gaps],
        "_rule_hints": rule_hints,
    }


def _public_analysis(analysis: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in analysis.items() if not key.startswith("_")}


async def analyze_memories(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> dict[str, object]:
    now = datetime.now(UTC)
    memories = await _active_memories(session, workspace_id, user_id)
    memory_ids = {memory.id for memory in memories}
    groups = _duplicate_groups(memories)
    conflicts = await _conflict_pairs(session, workspace_id, user_id, memory_ids)
    seen = {
        (min(left.id, right.id, key=str), max(left.id, right.id, key=str))
        for left, right in conflicts
    }
    for left, right in _heuristic_conflicts(memories):
        key = (min(left.id, right.id, key=str), max(left.id, right.id, key=str))
        if key in seen:
            continue
        seen.add(key)
        conflicts.append((left, right))
    relations = list(
        (
            await session.execute(
                select(MemoryRelation).where(
                    MemoryRelation.workspace_id == workspace_id,
                    MemoryRelation.user_id == user_id,
                    MemoryRelation.from_type == "memory",
                    MemoryRelation.to_type == "memory",
                )
            )
        ).scalars()
    )
    linked: set[UUID] = set()
    for relation in relations:
        linked.add(relation.from_id)
        linked.add(relation.to_id)
    orphan_ids = [memory.id for memory in memories if memory.id not in linked]
    anomalies = _relation_anomalies(memories, relations)
    return _analysis_payload(
        memories, groups, conflicts, now, anomalies, orphan_ids
    )


async def list_optimizations(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    *,
    status: str | None = None,
    limit: int = 50,
) -> list[MemoryOptimization]:
    conditions = [
        MemoryOptimization.workspace_id == workspace_id,
        MemoryOptimization.user_id == user_id,
    ]
    if status is not None:
        conditions.append(MemoryOptimization.status == status)
    return list(
        (
            await session.execute(
                select(MemoryOptimization)
                .where(*conditions)
                .order_by(MemoryOptimization.created_at.desc())
                .limit(max(1, min(limit, 200)))
            )
        ).scalars()
    )


async def generate_suggestions(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> dict[str, object]:
    analysis = await analyze_memories(session, workspace_id, user_id)
    existing = await list_optimizations(
        session, workspace_id, user_id, status="pending", limit=200
    )
    signatures = {
        _signature(
            row.kind, [str(item) for item in row.memory_ids or []], row.payload or {}
        )
        for row in existing
    }
    rows: list[MemoryOptimization] = []

    def add(
        kind: str,
        title: str,
        reason: str,
        expected_effect: str,
        memory_ids: list[UUID | str],
        payload: dict[str, object],
    ) -> None:
        ids = [str(item) for item in memory_ids]
        signature = _signature(kind, ids, payload)
        if signature in signatures:
            return
        signatures.add(signature)
        rows.append(
            MemoryOptimization(
                workspace_id=workspace_id,
                user_id=user_id,
                kind=kind,
                title=title[:200],
                reason=reason,
                expected_effect=expected_effect[:500],
                memory_ids=ids,
                payload=payload,
                status="pending",
            )
        )

    for group in analysis["_groups"]:
        target = max(group, key=lambda item: (item.importance, item.use_count))
        sources = [memory for memory in group if memory.id != target.id]
        merged_lines: list[str] = []
        for memory in [target, *sources]:
            line = memory.content.strip()
            if line and line not in merged_lines:
                merged_lines.append(line)
        labels = "、".join(
            memory.title or memory.content[:20] for memory in group[:4]
        )
        add(
            "merge_duplicates",
            f"合并 {len(group)} 条相似记忆",
            f"这些记忆的内容高度相似：{labels}。",
            "减少重复记忆，保留一条更完整的内容。",
            [target.id, *[memory.id for memory in sources]],
            {
                "target_id": str(target.id),
                "source_ids": [str(memory.id) for memory in sources],
                "merged_title": target.title,
                "merged_content": "\n".join(merged_lines),
            },
        )

    for left, right in analysis["_conflicts"]:
        loser = min((left, right), key=lambda item: (item.importance, item.use_count))
        keeper = right if loser.id == left.id else left
        add(
            "resolve_conflict",
            "处理冲突记忆",
            "两条记忆通过矛盾关系关联，至少有一条不再需要参与检索。",
            "保留更重要的一条，归档冲突项，避免矛盾上下文。",
            [keeper.id, loser.id],
            {"keep_id": str(keeper.id), "archive_id": str(loser.id)},
        )

    for memory_id in analysis["_expired_ids"]:
        memory = await session.get(AgentMemory, memory_id)
        if memory is None:
            continue
        add(
            "expire_memory",
            "标记过期记忆",
            "这条记忆已超过有效期，继续注入可能产生过时信息。",
            "停止在检索中使用，并保留历史记录。",
            [memory.id],
            {"status": "expired"},
        )

    for memory_id in analysis["_unused_ids"]:
        memory = await session.get(AgentMemory, memory_id)
        if memory is None:
            continue
        add(
            "archive_memory",
            "归档长期未使用记忆",
            "这条记忆超过 90 天未被调用。",
            "降低记忆噪音，仍可在归档中恢复。",
            [memory.id],
            {"status": "archived"},
        )

    memories = await _active_memories(session, workspace_id, user_id)
    for memory in memories:
        if memory.category != "fact":
            continue
        haystack = f"{memory.title} {memory.content}".casefold()
        if any(hint in haystack for hint in PREFERENCE_HINTS):
            add(
                "recategorize",
                "调整记忆分类",
                "内容更像个人偏好，而不是普通事实。",
                "提升检索与注入时的分类匹配度。",
                [memory.id],
                {"category": "preference"},
            )

    orphan_ids = list(analysis.get("_orphan_ids") or [])
    if orphan_ids:
        add(
            "link_orphans",
            f"为 {len(orphan_ids)} 条孤立记忆建立关联",
            "这些记忆没有进入关系图谱，检索和追溯时容易被忽略。",
            "补全关系后可以提升记忆发现率与上下文完整性。",
            orphan_ids[:20],
            {"actionable": False, "orphan_count": len(orphan_ids)},
        )

    anomaly_ids = list(analysis.get("_anomaly_ids") or [])
    if anomaly_ids:
        add(
            "review_relations",
            f"检查 {len(anomaly_ids)} 条异常关系",
            "存在自关联、重复关系或与重复记忆矛盾的关联。",
            "清理异常关系，避免图谱误导检索与质量分析。",
            [],
            {"actionable": False, "relation_ids": [str(item) for item in anomaly_ids[:20]]},
        )

    project_gap_ids = list(analysis.get("_project_gap_ids") or [])
    if project_gap_ids:
        add(
            "supplement_project",
            f"补充 {len(project_gap_ids)} 条项目记忆的项目绑定",
            "这些记忆属于项目类别，但没有绑定具体项目。",
            "绑定项目后可参与项目范围检索与权限控制。",
            project_gap_ids[:20],
            {"actionable": False},
        )

    rule_hints = list(analysis.get("_rule_hints") or [])
    if rule_hints:
        add(
            "adjust_rules",
            "调整记忆规则",
            "当前数据质量指标提示需要调整提取或保留规则。",
            "减少重复/冲突/不完整记忆的产生。",
            [],
            {"actionable": False, "rule_hints": rule_hints},
        )

    for row in rows[:MAX_SUGGESTIONS]:
        session.add(row)
    await session.flush()
    metrics.inc_counter(
        "ai_power_memory_quality_actions_total",
        value=len(rows[:MAX_SUGGESTIONS]),
        action="generated",
    )
    return {
        "analysis": _public_analysis(analysis),
        "suggestions": rows[:MAX_SUGGESTIONS],
    }


async def _load_optimization(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    optimization_id: UUID,
) -> MemoryOptimization:
    row = (
        await session.execute(
            select(MemoryOptimization).where(
                MemoryOptimization.id == optimization_id,
                MemoryOptimization.workspace_id == workspace_id,
                MemoryOptimization.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise QualityError("not_found", "Optimization not found")
    return row


async def _memory_map(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    memory_ids: list[str],
) -> dict[UUID, AgentMemory]:
    parsed = []
    for value in memory_ids:
        try:
            parsed.append(UUID(str(value)))
        except ValueError:
            continue
    if not parsed:
        return {}
    rows = list(
        (
            await session.execute(
                select(AgentMemory).where(
                    AgentMemory.workspace_id == workspace_id,
                    AgentMemory.user_id == user_id,
                    AgentMemory.id.in_(parsed),
                )
            )
        ).scalars()
    )
    return {memory.id: memory for memory in rows}


def _snapshot(memory: AgentMemory) -> dict[str, object]:
    return {
        "title": memory.title,
        "content": memory.content,
        "category": memory.category,
        "status": memory.status,
        "enabled": memory.enabled,
        "importance": memory.importance,
        "tags": list(memory.tags or []),
    }


async def apply_optimization(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    optimization_id: UUID,
) -> MemoryOptimization:
    row = await _load_optimization(session, workspace_id, user_id, optimization_id)
    if row.status != "pending":
        raise QualityError("invalid_status", "Only pending optimizations can be applied")
    if row.kind not in ACTIONABLE_KINDS:
        raise QualityError("not_actionable", "This suggestion is informational only")
    payload = dict(row.payload or {})
    memories = await _memory_map(
        session, workspace_id, user_id, list(row.memory_ids or [])
    )
    row.before_snapshot = {
        str(memory_id): _snapshot(memory)
        for memory_id, memory in memories.items()
    }
    created_relations: list[str] = []
    if row.kind == "merge_duplicates":
        target_id = payload.get("target_id")
        target = memories.get(UUID(str(target_id))) if target_id else None
        if target is None:
            raise QualityError("not_found", "Merge target no longer exists")
        await update_memory(
            session,
            target,
            title=str(payload.get("merged_title") or target.title),
            content=str(payload.get("merged_content") or target.content),
            change_reason="merge duplicates",
            changed_by=user_id,
        )
        for source_id in payload.get("source_ids") or []:
            source = memories.get(UUID(str(source_id)))
            if source is None:
                continue
            await update_memory(
                session,
                source,
                status="archived",
                change_reason="merged into another memory",
                changed_by=user_id,
            )
            relation = await create_memory_relation(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
                from_type="memory",
                from_id=target.id,
                to_type="memory",
                to_id=source.id,
                relation_type="supersedes",
                basis="merged duplicate memory",
            )
            created_relations.append(str(relation.id))
    elif row.kind == "resolve_conflict":
        archive_id = payload.get("archive_id")
        memory = memories.get(UUID(str(archive_id))) if archive_id else None
        if memory is None:
            raise QualityError("not_found", "Conflict memory no longer exists")
        await update_memory(
            session,
            memory,
            status="archived",
            change_reason="conflict resolution",
            changed_by=user_id,
        )
    elif row.kind in {"expire_memory", "archive_memory"}:
        target_id = row.memory_ids[0] if row.memory_ids else None
        memory = memories.get(UUID(str(target_id))) if target_id else None
        if memory is None:
            raise QualityError("not_found", "Memory no longer exists")
        fallback = "expired" if row.kind == "expire_memory" else "archived"
        await update_memory(
            session,
            memory,
            status=str(payload.get("status") or fallback),
            change_reason=row.kind,
            changed_by=user_id,
        )
    elif row.kind == "recategorize":
        target_id = row.memory_ids[0] if row.memory_ids else None
        memory = memories.get(UUID(str(target_id))) if target_id else None
        if memory is None:
            raise QualityError("not_found", "Memory no longer exists")
        await update_memory(
            session,
            memory,
            category=str(payload.get("category") or "preference"),
            change_reason="quality recategorize",
            changed_by=user_id,
        )
    if created_relations:
        payload["created_relation_ids"] = created_relations
        row.payload = payload
    row.status = "applied"
    row.applied_at = datetime.now(UTC)
    await session.flush()
    metrics.inc_counter("ai_power_memory_quality_actions_total", action="applied")
    return row


async def rollback_optimization(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    optimization_id: UUID,
) -> MemoryOptimization:
    row = await _load_optimization(session, workspace_id, user_id, optimization_id)
    if row.status != "applied":
        raise QualityError(
            "invalid_status", "Only applied optimizations can be rolled back"
        )
    snapshot = row.before_snapshot or {}
    memories = await _memory_map(
        session, workspace_id, user_id, list(snapshot.keys())
    )
    for memory_id, memory in memories.items():
        saved = snapshot.get(str(memory_id)) or {}
        await update_memory(
            session,
            memory,
            title=str(saved.get("title") or memory.title),
            content=str(saved.get("content") or memory.content),
            category=str(saved.get("category") or memory.category),
            status=str(saved.get("status") or "active"),
            enabled=bool(saved.get("enabled", True)),
            importance=int(saved.get("importance") or memory.importance),
            tags=list(saved.get("tags") or []),
            change_reason="rollback quality optimization",
            changed_by=user_id,
        )
    for relation_id in (row.payload or {}).get("created_relation_ids") or []:
        try:
            await delete_memory_relation(
                session, workspace_id, user_id, UUID(str(relation_id))
            )
        except Exception:
            continue
    row.status = "rolled_back"
    row.rolled_back_at = datetime.now(UTC)
    await session.flush()
    metrics.inc_counter(
        "ai_power_memory_quality_actions_total", action="rolled_back"
    )
    return row


async def dismiss_optimization(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    optimization_id: UUID,
) -> MemoryOptimization:
    row = await _load_optimization(session, workspace_id, user_id, optimization_id)
    if row.status != "pending":
        raise QualityError("invalid_status", "Only pending suggestions can be dismissed")
    row.status = "dismissed"
    await session.flush()
    metrics.inc_counter(
        "ai_power_memory_quality_actions_total", action="dismissed"
    )
    return row


async def nightly_consolidation(session: AsyncSession) -> dict[str, int]:
    settings_rows = list(
        (
            await session.execute(
                select(MemorySettings).where(MemorySettings.enabled.is_(True)).limit(500)
            )
        ).scalars()
    )
    users = 0
    suggestions = 0
    for row in settings_rows:
        await rebuild_memory_graph(session, row.workspace_id, row.user_id)
        result = await generate_suggestions(
            session, row.workspace_id, row.user_id
        )
        suggestions += len(result["suggestions"])
        users += 1
    await session.flush()
    metrics.inc_counter(
        "ai_power_memory_quality_actions_total",
        value=suggestions,
        action="nightly",
    )
    return {"users": users, "suggestions": suggestions}


async def quality_overview(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> dict[str, object]:
    analysis = await analyze_memories(session, workspace_id, user_id)
    suggestions = await list_optimizations(
        session, workspace_id, user_id, status=None, limit=50
    )
    return {
        "analysis": _public_analysis(analysis),
        "suggestions": suggestions,
    }