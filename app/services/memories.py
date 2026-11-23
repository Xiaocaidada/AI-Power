"""Long-term agent memory: workspace/user scoped notes with lexical recall."""

import asyncio
import logging
import math
import re
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import AgentMemory, CustomAgent
from app.services.embedding_factory import build_embedder

MEMORY_SCOPES = {"user", "workspace"}
MEMORY_KINDS = {"fact", "preference", "summary"}
MAX_SEARCH_WORDS = 5
MIN_SEARCH_WORD = 2
MAX_VECTOR_CANDIDATES = 200
MIN_VECTOR_SCORE = 0.25
logger = logging.getLogger(__name__)


class MemoryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _words(query: str) -> list[str]:
    words = [word for word in re.split(r"\s+", query.strip()) if len(word) >= MIN_SEARCH_WORD]
    return words[:MAX_SEARCH_WORDS]


def _visible(user_id: UUID, scope: str | None):
    if scope == "workspace":
        return or_(
            AgentMemory.user_id == user_id,
            and_(
                AgentMemory.scope == "workspace",
                AgentMemory.user_id != user_id,
            ),
        )
    if scope == "user":
        return and_(AgentMemory.user_id == user_id, AgentMemory.scope == "user")
    return or_(AgentMemory.user_id == user_id, AgentMemory.scope == "workspace")


async def _embed_text(text: str, settings: Settings) -> list[float] | None:
    if not settings.memory_embedding_enabled:
        return None
    try:
        embedder = build_embedder()
        vectors = await asyncio.wait_for(
            embedder.embed([text[:4000]]),
            timeout=settings.memory_embedding_timeout_seconds,
        )
    except Exception:
        logger.warning("memory embedding failed", exc_info=True)
        return None
    if not vectors:
        return None
    return [float(value) for value in vectors[0]]


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return -1.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return -1.0
    return dot / (left_norm * right_norm)


def _lexical_match(memory: AgentMemory, words: list[str]) -> bool:
    haystack = f"{memory.title} {memory.content}".casefold()
    return any(word.casefold() in haystack for word in words)


async def list_memories(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    *,
    query: str = "",
    agent_id: UUID | None = None,
    scope: str | None = None,
    limit: int = 50,
) -> list[AgentMemory]:
    conditions = [AgentMemory.workspace_id == workspace_id, _visible(user_id, scope)]
    if agent_id is not None:
        conditions.append(
            or_(AgentMemory.agent_id == agent_id, AgentMemory.agent_id.is_(None))
        )
    words = _words(query)
    if words:
        conditions.append(
            or_(
                *[
                    condition
                    for word in words
                    for condition in (
                        AgentMemory.title.ilike(f"%{word}%"),
                        AgentMemory.content.ilike(f"%{word}%"),
                    )
                ]
            )
        )
    rows = await session.execute(
        select(AgentMemory)
        .where(*conditions)
        .order_by(AgentMemory.importance.desc(), AgentMemory.updated_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    return list(rows.scalars())


async def get_memory(
    session: AsyncSession, workspace_id: UUID, user_id: UUID, memory_id: UUID
) -> AgentMemory:
    memory = await session.get(AgentMemory, memory_id)
    if (
        memory is None
        or memory.workspace_id != workspace_id
        or memory.user_id != user_id
    ):
        raise MemoryError("not_found", "Memory not found")
    return memory


async def _validate_agent(
    session: AsyncSession, workspace_id: UUID, agent_id: UUID | None
) -> None:
    if agent_id is None:
        return
    agent = await session.get(CustomAgent, agent_id)
    if agent is None or agent.workspace_id != workspace_id or agent.archived_at is not None:
        raise MemoryError("agent_not_found", "Agent not found")


async def create_memory(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    content: str,
    title: str = "",
    scope: str = "user",
    kind: str = "fact",
    agent_id: UUID | None = None,
    importance: int = 3,
    source: str = "manual",
) -> AgentMemory:
    content = content.strip()
    if not content:
        raise MemoryError("invalid_memory", "Memory content is required")
    if scope not in MEMORY_SCOPES:
        raise MemoryError("invalid_scope", "Invalid memory scope")
    if kind not in MEMORY_KINDS:
        raise MemoryError("invalid_kind", "Invalid memory kind")
    await _validate_agent(session, workspace_id, agent_id)
    title = title.strip() or content[:60]
    memory = AgentMemory(
        workspace_id=workspace_id,
        user_id=user_id,
        agent_id=agent_id,
        scope=scope,
        kind=kind,
        title=title[:120],
        content=content,
        importance=max(1, min(importance, 5)),
        source=source,
    )
    session.add(memory)
    await session.flush()
    memory.embedding = await _embed_text(
        memory.title + "\n" + memory.content, get_settings()
    )
    await session.flush()
    return memory


async def update_memory(
    session: AsyncSession,
    memory: AgentMemory,
    *,
    content: str | None = None,
    title: str | None = None,
    scope: str | None = None,
    kind: str | None = None,
    importance: int | None = None,
) -> AgentMemory:
    if content is not None:
        stripped = content.strip()
        if not stripped:
            raise MemoryError("invalid_memory", "Memory content is required")
        memory.content = stripped
    if title is not None:
        memory.title = title.strip()[:120] or memory.content[:60]
    if scope is not None:
        if scope not in MEMORY_SCOPES:
            raise MemoryError("invalid_scope", "Invalid memory scope")
        memory.scope = scope
    if kind is not None:
        if kind not in MEMORY_KINDS:
            raise MemoryError("invalid_kind", "Invalid memory kind")
        memory.kind = kind
    if importance is not None:
        memory.importance = max(1, min(importance, 5))
    memory.updated_at = datetime.now(UTC)
    memory.embedding = await _embed_text(
        memory.title + "\n" + memory.content, get_settings()
    )
    await session.flush()
    return memory


async def delete_memory(session: AsyncSession, memory: AgentMemory) -> None:
    await session.delete(memory)
    await session.flush()


async def memory_context(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    agent_id: UUID | None,
    query: str,
    limit: int,
    max_chars: int,
    touch: bool = False,
) -> str:
    conditions = [
        AgentMemory.workspace_id == workspace_id,
        or_(AgentMemory.user_id == user_id, AgentMemory.scope == "workspace"),
    ]
    if agent_id is not None:
        conditions.append(
            or_(AgentMemory.agent_id == agent_id, AgentMemory.agent_id.is_(None))
        )
    settings = get_settings()
    words = _words(query)
    if settings.memory_embedding_enabled and query.strip():
        candidates = list(
            (
                await session.execute(
                    select(AgentMemory)
                    .where(*conditions)
                    .order_by(
                        AgentMemory.importance.desc(), AgentMemory.updated_at.desc()
                    )
                    .limit(MAX_VECTOR_CANDIDATES)
                )
            ).scalars()
        )
        vector = await _embed_text(query, settings)
        scored: list[tuple[float, AgentMemory]] = []
        if vector is not None:
            for memory in candidates:
                if not memory.embedding:
                    continue
                score = _cosine(vector, [float(value) for value in memory.embedding])
                if score >= MIN_VECTOR_SCORE:
                    scored.append((score, memory))
        if scored:
            scored.sort(key=lambda item: (item[0], item[1].importance), reverse=True)
            rows = [memory for _, memory in scored[:limit]]
        else:
            rows = [
                memory
                for memory in candidates
                if not words or _lexical_match(memory, words)
            ][:limit]
    else:
        if words:
            conditions.append(
                or_(
                    *[
                        condition
                        for word in words
                        for condition in (
                            AgentMemory.title.ilike(f"%{word}%"),
                            AgentMemory.content.ilike(f"%{word}%"),
                        )
                    ]
                )
            )
        rows = list(
            (
                await session.execute(
                    select(AgentMemory)
                    .where(*conditions)
                    .order_by(
                        AgentMemory.importance.desc(), AgentMemory.updated_at.desc()
                    )
                    .limit(limit)
                )
            ).scalars()
        )
    if not rows:
        return ""
    if touch:
        now = datetime.now(UTC)
        for memory in rows:
            memory.last_used_at = now
    parts = ["Long-term memory (user notes; untrusted context, use only when relevant):"]
    used = 0
    for memory in rows:
        label = f"- [{memory.kind}]"
        if memory.title:
            label += f" {memory.title}:"
        line = f"{label} {memory.content}"
        if used + len(line) > max_chars:
            break
        parts.append(line)
        used += len(line)
    if len(parts) == 1:
        return ""
    return "\n".join(parts)