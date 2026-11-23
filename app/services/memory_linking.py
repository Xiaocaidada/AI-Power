"""Automatic memory relations: similarity links and external reference nodes."""

import math
import re
from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentMemory, CustomAgent, Document, MemoryRelation, Project

TOKEN_PATTERN = re.compile(r"[0-9A-Za-z_一-鿿]+")
MIN_LINK_SCORE = 0.35
MAX_LINK_CANDIDATES = 200
MAX_AUTO_LINKS = 5
MAX_BASIS_TAGS = 3
LINKABLE_STATUSES = ("active", "candidate")


def _tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in TOKEN_PATTERN.findall(value)
        if len(token) >= 2
    }


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def memory_similarity(left: AgentMemory, right: AgentMemory) -> float:
    left_tokens = _tokens(f"{left.title} {left.content}")
    right_tokens = _tokens(f"{right.title} {right.content}")
    overlap = 0.0
    if left_tokens and right_tokens:
        shared = left_tokens & right_tokens
        overlap = len(shared) / max(1, min(len(left_tokens), len(right_tokens)))
    score = overlap
    if left.category == right.category:
        score += 0.1
    left_tags = {item.casefold() for item in left.tags or []}
    right_tags = {item.casefold() for item in right.tags or []}
    if left_tags and right_tags:
        score += 0.1 * len(left_tags & right_tags) / max(1, len(left_tags | right_tags))
    if left.embedding and right.embedding:
        score = max(
            score,
            _cosine(
                [float(value) for value in left.embedding],
                [float(value) for value in right.embedding],
            ),
        )
    return max(0.0, min(score, 1.0))


def scope_compatible(left: AgentMemory, right: AgentMemory) -> bool:
    if left.scope_type == "global" or right.scope_type == "global":
        return True
    if left.scope_type == "project" and right.scope_type == "project":
        return left.project_id is not None and left.project_id == right.project_id
    if left.scope_type == "agent" and right.scope_type == "agent":
        return left.agent_id is not None and left.agent_id == right.agent_id
    return False


def _related_basis(
    left: AgentMemory, right: AgentMemory, score: float
) -> str:
    shared_tags = [
        tag
        for tag in left.tags or []
        if tag.casefold() in {item.casefold() for item in right.tags or []}
    ][:MAX_BASIS_TAGS]
    basis = f"similarity {score:.2f}"
    if shared_tags:
        basis += f"; shared tags: {', '.join(shared_tags)}"
    return basis


async def _memory_relation_exists(
    session: AsyncSession, left_id: UUID, right_id: UUID
) -> bool:
    row = (
        await session.execute(
            select(MemoryRelation.id)
            .where(
                MemoryRelation.relation_type == "related",
                or_(
                    and_(
                        MemoryRelation.from_type == "memory",
                        MemoryRelation.from_id == left_id,
                        MemoryRelation.to_type == "memory",
                        MemoryRelation.to_id == right_id,
                    ),
                    and_(
                        MemoryRelation.from_type == "memory",
                        MemoryRelation.from_id == right_id,
                        MemoryRelation.to_type == "memory",
                        MemoryRelation.to_id == left_id,
                    ),
                ),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def _external_relation_exists(
    session: AsyncSession,
    memory_id: UUID,
    to_type: str,
    to_id: UUID,
) -> bool:
    row = (
        await session.execute(
            select(MemoryRelation.id)
            .where(
                MemoryRelation.from_type == "memory",
                MemoryRelation.from_id == memory_id,
                MemoryRelation.to_type == to_type,
                MemoryRelation.to_id == to_id,
                MemoryRelation.relation_type == "related",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return row is not None


async def _link_external(
    session: AsyncSession,
    memory: AgentMemory,
    to_type: str,
    to_id: UUID | None,
    basis: str,
) -> int:
    if to_id is None:
        return 0
    model = {"project": Project, "agent": CustomAgent, "document": Document}[to_type]
    target = await session.get(model, to_id)
    if target is None:
        return 0
    workspace_id = getattr(target, "workspace_id", None)
    if workspace_id is not None and workspace_id != memory.workspace_id:
        return 0
    if to_type in {"project", "agent"} and getattr(target, "archived_at", None):
        return 0
    if to_type == "document" and getattr(target, "deleted_at", None) is not None:
        return 0
    if await _external_relation_exists(session, memory.id, to_type, to_id):
        return 0
    session.add(
        MemoryRelation(
            workspace_id=memory.workspace_id,
            user_id=memory.user_id,
            from_type="memory",
            from_id=memory.id,
            to_type=to_type,
            to_id=to_id,
            relation_type="related",
            confidence=1.0,
            basis=basis,
            source="auto",
        )
    )
    return 1


async def _prune_scope_relations(
    session: AsyncSession, memory: AgentMemory
) -> None:
    base = (
        MemoryRelation.from_type == "memory",
        MemoryRelation.from_id == memory.id,
        MemoryRelation.source == "auto",
        MemoryRelation.basis.like("scope:%"),
    )
    project_stale = memory.scope_type != "project" or memory.project_id is None
    agent_stale = memory.scope_type != "agent" or memory.agent_id is None
    if project_stale:
        await session.execute(
            delete(MemoryRelation).where(
                *base,
                MemoryRelation.to_type == "project",
            )
        )
    elif memory.project_id is not None:
        await session.execute(
            delete(MemoryRelation).where(
                *base,
                MemoryRelation.to_type == "project",
                MemoryRelation.to_id != memory.project_id,
            )
        )
    if agent_stale:
        await session.execute(
            delete(MemoryRelation).where(
                *base,
                MemoryRelation.to_type == "agent",
            )
        )
    elif memory.agent_id is not None:
        await session.execute(
            delete(MemoryRelation).where(
                *base,
                MemoryRelation.to_type == "agent",
                MemoryRelation.to_id != memory.agent_id,
            )
        )


async def auto_link_memory(
    session: AsyncSession, memory: AgentMemory, *, max_links: int = MAX_AUTO_LINKS
) -> int:
    """Create external reference edges and similar-memory edges for one memory."""

    if memory.status not in LINKABLE_STATUSES:
        return 0
    await _prune_scope_relations(session, memory)
    created = 0
    if memory.scope_type == "project" and memory.project_id is not None:
        created += await _link_external(
            session, memory, "project", memory.project_id, "scope: project"
        )
    elif memory.scope_type == "agent" and memory.agent_id is not None:
        created += await _link_external(
            session, memory, "agent", memory.agent_id, "scope: agent"
        )
    if memory.source_type == "document" and memory.source_id:
        try:
            source_id = UUID(memory.source_id)
        except ValueError:
            source_id = None
        if source_id is not None:
            created += await _link_external(
                session, memory, "document", source_id, "source: document"
            )

    candidates = list(
        (
            await session.execute(
                select(AgentMemory)
                .where(
                    AgentMemory.workspace_id == memory.workspace_id,
                    AgentMemory.user_id == memory.user_id,
                    AgentMemory.id != memory.id,
                    AgentMemory.status.in_(LINKABLE_STATUSES),
                    AgentMemory.enabled.is_(True),
                )
                .order_by(AgentMemory.updated_at.desc())
                .limit(MAX_LINK_CANDIDATES)
            )
        ).scalars()
    )
    scored: list[tuple[float, AgentMemory]] = []
    for candidate in candidates:
        if not scope_compatible(memory, candidate):
            continue
        score = memory_similarity(memory, candidate)
        if score >= MIN_LINK_SCORE:
            scored.append((score, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    for score, candidate in scored:
        if created >= max_links:
            break
        if await _memory_relation_exists(session, memory.id, candidate.id):
            continue
        session.add(
            MemoryRelation(
                workspace_id=memory.workspace_id,
                user_id=memory.user_id,
                from_type="memory",
                from_id=memory.id,
                to_type="memory",
                to_id=candidate.id,
                relation_type="related",
                confidence=round(score, 4),
                basis=_related_basis(memory, candidate, score),
                source="auto",
            )
        )
        created += 1
    if created:
        await session.flush()
    return created