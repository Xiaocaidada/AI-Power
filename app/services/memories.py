"""Long-term memory hub: scoped notes, versions, relations and usage."""

import asyncio
import hashlib
import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import String, and_, cast, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import (
    AgentMemory,
    CustomAgent,
    MemoryCandidate,
    MemoryRelation,
    MemorySettings,
    MemoryUsageEvent,
    MemoryVersion,
    Project,
)
from app.services.embedding_factory import build_embedder
from app.services.memory_linking import auto_link_memory
from app.services.quotas import enforce_memory_quota

MEMORY_SCOPES = {"user", "workspace"}
MEMORY_KINDS = {"fact", "preference", "summary"}
SCOPE_TYPES = {"global", "project", "agent"}
CATEGORIES = {
    "fact",
    "preference",
    "profile",
    "project",
    "technical",
    "experience",
    "decision",
    "relation",
    "summary",
}
STATUSES = {"candidate", "active", "conflict", "expired", "archived", "rejected"}
SOURCE_TYPES = {
    "manual",
    "chat",
    "agent",
    "workflow",
    "project",
    "document",
    "import",
    "api",
    "system",
}
SENSITIVITIES = {"normal", "sensitive"}
RELATION_TYPES = {"related", "supports", "contradicts", "supersedes", "derived_from"}

MAX_SEARCH_WORDS = 5
MIN_SEARCH_WORD = 2
MAX_VECTOR_CANDIDATES = 200
MIN_VECTOR_SCORE = 0.25
SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b(password|passwd|api[_ -]?key|secret|access[_ -]?token|"
        r"refresh[_ -]?token|密码)\s*[:=：]\s*\S{4,}"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{20,}"),
    re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |PGP )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
    ),
    re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb|redis)://[^:\s]+:[^@\s]+@"),
)
DEFAULT_ALLOWED_CATEGORIES = [
    "preference",
    "profile",
    "project",
    "technical",
    "experience",
    "decision",
    "relation",
    "fact",
]
logger = logging.getLogger(__name__)


class MemoryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class SelectedMemory:
    memory: AgentMemory
    score: float
    injected_chars: int


@dataclass(frozen=True, slots=True)
class MemorySelection:
    block: str
    items: list[SelectedMemory]

    def refs(self) -> list[dict[str, object]]:
        return [
            {
                "id": str(item.memory.id),
                "title": item.memory.title,
                "category": item.memory.category,
                "scope_type": item.memory.scope_type,
                "relevance": round(item.score, 4),
                "injected_chars": item.injected_chars,
            }
            for item in self.items
        ]


def _words(query: str) -> list[str]:
    words = [
        word
        for word in re.findall(r"[0-9A-Za-z_一-鿿]+", query)
        if len(word) >= MIN_SEARCH_WORD
    ]
    return words[:MAX_SEARCH_WORDS]


def memory_hash(title: str, content: str) -> str:
    return hashlib.sha256(f"{title}\n{content}".encode()).hexdigest()


def _contains_secret(content: str) -> bool:
    return any(pattern.search(content) for pattern in SECRET_PATTERNS)


def _clean_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    cleaned: list[str] = []
    for item in tags:
        tag = item.strip()[:30]
        if tag and tag not in cleaned:
            cleaned.append(tag)
    return cleaned[:20]


def _clean_blocked_topics(items: list[str] | None) -> list[str]:
    if not items:
        return []
    cleaned: list[str] = []
    for item in items:
        value = item.strip()[:50]
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned[:20]


def _normalize_scope(scope: str | None, scope_type: str | None) -> tuple[str, str]:
    if scope_type is not None:
        if scope_type not in SCOPE_TYPES:
            raise MemoryError("invalid_scope", "Invalid memory scope type")
        legacy = "user" if scope_type == "global" else "workspace"
        return legacy, scope_type
    if scope in {"workspace"}:
        return "workspace", "global"
    return "user", "global"


def _normalize_category(category: str | None, kind: str | None) -> str:
    if category is not None:
        if category not in CATEGORIES:
            raise MemoryError("invalid_category", "Invalid memory category")
        return category
    if kind == "preference":
        return "preference"
    if kind == "summary":
        return "experience"
    return "fact"


def _snapshot(memory: AgentMemory) -> dict[str, object]:
    return {
        "title": memory.title,
        "content": memory.content,
        "category": memory.category,
        "scope_type": memory.scope_type,
        "project_id": str(memory.project_id) if memory.project_id else None,
        "agent_id": str(memory.agent_id) if memory.agent_id else None,
        "tags": list(memory.tags or []),
        "status": memory.status,
        "importance": memory.importance,
        "enabled": memory.enabled,
        "pinned": memory.pinned,
        "favorite": memory.favorite,
        "sensitivity": memory.sensitivity,
        "confidence": memory.confidence,
        "valid_until": memory.valid_until.isoformat() if memory.valid_until else None,
        "retention_days": memory.retention_days,
        "version": memory.version,
    }


def _personal_filters(workspace_id: UUID, user_id: UUID) -> list:
    return [AgentMemory.workspace_id == workspace_id, AgentMemory.user_id == user_id]


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def _ensure_topic_allowed(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    title: str,
    content: str,
) -> None:
    row = (
        await session.execute(
            select(MemorySettings).where(
                MemorySettings.workspace_id == workspace_id,
                MemorySettings.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None or not row.blocked_topics:
        return
    text = f"{title}\n{content}".casefold()
    if any(str(topic).casefold() in text for topic in row.blocked_topics if topic):
        raise MemoryError(
            "blocked_topic", "Memory matches a blocked topic in memory settings"
        )




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


async def _validate_project(
    session: AsyncSession, workspace_id: UUID, project_id: UUID | None
) -> None:
    if project_id is None:
        return
    project = await session.get(Project, project_id)
    if (
        project is None
        or project.workspace_id != workspace_id
        or project.archived_at is not None
    ):
        raise MemoryError("project_not_found", "Project not found")


async def _validate_agent(
    session: AsyncSession, workspace_id: UUID, agent_id: UUID | None
) -> None:
    if agent_id is None:
        return
    agent = await session.get(CustomAgent, agent_id)
    if agent is None or agent.workspace_id != workspace_id or agent.archived_at is not None:
        raise MemoryError("agent_not_found", "Agent not found")


async def validate_memory_targets(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    project_id: UUID | None = None,
    agent_id: UUID | None = None,
) -> None:
    await _validate_project(session, workspace_id, project_id)
    await _validate_agent(session, workspace_id, agent_id)


async def find_memory_by_title(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    title: str,
    scope_type: str,
    project_id: UUID | None = None,
    agent_id: UUID | None = None,
) -> AgentMemory | None:
    clean_title = title.strip()[:120]
    if not clean_title:
        return None
    return (
        await session.execute(
            select(AgentMemory)
            .where(
                *_personal_filters(workspace_id, user_id),
                AgentMemory.title == clean_title,
                AgentMemory.scope_type == scope_type,
                AgentMemory.project_id == project_id,
                AgentMemory.agent_id == agent_id,
                AgentMemory.status.notin_(["archived", "rejected"]),
            )
            .order_by(AgentMemory.updated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def get_memory_settings(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> MemorySettings:
    row = (
        await session.execute(
            select(MemorySettings).where(
                MemorySettings.workspace_id == workspace_id,
                MemorySettings.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    row = MemorySettings(
        workspace_id=workspace_id,
        user_id=user_id,
        allowed_categories=list(DEFAULT_ALLOWED_CATEGORIES),
    )
    session.add(row)
    await session.flush()
    return row


async def update_memory_settings(
    session: AsyncSession, row: MemorySettings, **fields: object
) -> MemorySettings:
    for key, value in fields.items():
        if value is None:
            continue
        setattr(row, key, value)
    row.updated_at = datetime.now(UTC)
    await session.flush()
    return row


async def list_memories(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    *,
    query: str = "",
    agent_id: UUID | None = None,
    scope: str | None = None,
    scope_type: str | None = None,
    category: str | None = None,
    status: str | None = None,
    project_id: UUID | None = None,
    tag: str | None = None,
    favorite: bool | None = None,
    pinned: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AgentMemory]:
    conditions = _personal_filters(workspace_id, user_id)
    effective_scope = scope_type
    if effective_scope is None and scope is not None:
        effective_scope = "global"
    if effective_scope is not None:
        if effective_scope not in SCOPE_TYPES:
            raise MemoryError("invalid_scope", "Invalid memory scope type")
        conditions.append(AgentMemory.scope_type == effective_scope)
    if category is not None:
        conditions.append(AgentMemory.category == category)
    if status is not None:
        conditions.append(AgentMemory.status == status)
    if project_id is not None:
        conditions.append(AgentMemory.project_id == project_id)
    if agent_id is not None:
        conditions.append(
            or_(AgentMemory.agent_id == agent_id, AgentMemory.agent_id.is_(None))
        )
    if tag is not None and tag.strip():
        conditions.append(
            cast(AgentMemory.tags, String).ilike(f'%"{tag.strip()}"%')
        )
    if favorite is not None:
        conditions.append(AgentMemory.favorite.is_(favorite))
    if pinned is not None:
        conditions.append(AgentMemory.pinned.is_(pinned))
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
        .order_by(
            AgentMemory.pinned.desc(),
            AgentMemory.importance.desc(),
            AgentMemory.updated_at.desc(),
        )
        .offset(max(offset, 0))
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
    project_id: UUID | None = None,
    scope_type: str | None = None,
    category: str | None = None,
    status: str = "active",
    importance: int = 3,
    source: str = "manual",
    source_type: str | None = None,
    source_id: str | None = None,
    source_ref: dict[str, object] | None = None,
    confidence: float = 1.0,
    sensitivity: str = "normal",
    tags: list[str] | None = None,
    enabled: bool = True,
    pinned: bool = False,
    favorite: bool = False,
    valid_until: datetime | None = None,
    retention_days: int | None = None,
    metadata: dict[str, object] | None = None,
) -> AgentMemory:
    content = content.strip()
    if not content:
        raise MemoryError("invalid_memory", "Memory content is required")
    if _contains_secret(content):
        raise MemoryError("secret_blocked", "Secrets cannot be stored as memory")
    legacy_scope, normalized_scope = _normalize_scope(scope, scope_type)
    normalized_category = _normalize_category(category, kind)
    if status not in STATUSES:
        raise MemoryError("invalid_status", "Invalid memory status")
    if sensitivity not in SENSITIVITIES:
        raise MemoryError("invalid_sensitivity", "Invalid sensitivity")
    if source_type is None:
        source_type = source if source in SOURCE_TYPES else "manual"
    await _validate_agent(session, workspace_id, agent_id)
    await _validate_project(session, workspace_id, project_id)
    if normalized_scope == "project" and project_id is None:
        raise MemoryError("invalid_scope", "Project memory requires project_id")
    if normalized_scope == "agent" and agent_id is None:
        raise MemoryError("invalid_scope", "Agent memory requires agent_id")
    await enforce_memory_quota(session, workspace_id)
    title = title.strip()[:120] or content[:60]
    await _ensure_topic_allowed(session, workspace_id, user_id, title, content)
    memory = AgentMemory(
        workspace_id=workspace_id,
        user_id=user_id,
        agent_id=agent_id,
        project_id=project_id,
        scope=legacy_scope,
        scope_type=normalized_scope,
        kind=kind,
        category=normalized_category,
        status=status,
        title=title,
        content=content,
        importance=max(1, min(importance, 5)),
        source=source,
        source_type=source_type,
        source_id=source_id,
        source_ref=dict(source_ref or {}),
        confidence=max(0.0, min(confidence, 1.0)),
        sensitivity=sensitivity,
        tags=_clean_tags(tags),
        enabled=enabled,
        pinned=pinned,
        favorite=favorite,
        valid_until=valid_until,
        retention_days=retention_days if retention_days and retention_days > 0 else None,
        version=1,
        memory_metadata=dict(metadata or {}),
    )
    memory.content_hash = memory_hash(memory.title, memory.content)
    session.add(memory)
    await session.flush()
    memory.embedding = await _embed_text(
        memory.title + "\n" + memory.content, get_settings()
    )
    session.add(
        MemoryVersion(
            memory_id=memory.id,
            version=1,
            snapshot=_snapshot(memory),
            changed_by=user_id,
            change_reason="created",
        )
    )
    await session.flush()
    await auto_link_memory(session, memory)
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
    scope_type: str | None = None,
    category: str | None = None,
    status: str | None = None,
    project_id: UUID | None = None,
    agent_id: UUID | None = None,
    tags: list[str] | None = None,
    enabled: bool | None = None,
    pinned: bool | None = None,
    favorite: bool | None = None,
    sensitivity: str | None = None,
    confidence: float | None = None,
    valid_until: datetime | None = None,
    retention_days: int | None = None,
    metadata: dict[str, object] | None = None,
    change_reason: str = "",
    changed_by: UUID | None = None,
    auto_link: bool = True,
) -> AgentMemory:
    content_changed = False
    if content is not None:
        stripped = content.strip()
        if not stripped:
            raise MemoryError("invalid_memory", "Memory content is required")
        if _contains_secret(stripped):
            raise MemoryError("secret_blocked", "Secrets cannot be stored as memory")
        memory.content = stripped
        content_changed = True
    if title is not None:
        memory.title = title.strip()[:120] or memory.content[:60]
        content_changed = True
    if scope_type is not None:
        if scope_type not in SCOPE_TYPES:
            raise MemoryError("invalid_scope", "Invalid memory scope type")
        memory.scope_type = scope_type
        memory.scope = "user" if scope_type == "global" else "workspace"
    elif scope is not None:
        legacy_scope, normalized_scope = _normalize_scope(scope, None)
        memory.scope = legacy_scope
        memory.scope_type = normalized_scope
    if category is not None:
        if category not in CATEGORIES:
            raise MemoryError("invalid_category", "Invalid memory category")
        memory.category = category
    elif kind is not None:
        if kind not in MEMORY_KINDS:
            raise MemoryError("invalid_kind", "Invalid memory kind")
        memory.kind = kind
        memory.category = _normalize_category(None, kind)
    if status is not None:
        if status not in STATUSES:
            raise MemoryError("invalid_status", "Invalid memory status")
        memory.status = status
    if project_id is not None:
        await _validate_project(session, memory.workspace_id, project_id)
        memory.project_id = project_id
    if agent_id is not None:
        await _validate_agent(session, memory.workspace_id, agent_id)
        memory.agent_id = agent_id
    if importance is not None:
        memory.importance = max(1, min(importance, 5))
    if tags is not None:
        memory.tags = _clean_tags(tags)
    if enabled is not None:
        memory.enabled = enabled
    if pinned is not None:
        memory.pinned = pinned
    if favorite is not None:
        memory.favorite = favorite
    if sensitivity is not None:
        if sensitivity not in SENSITIVITIES:
            raise MemoryError("invalid_sensitivity", "Invalid sensitivity")
        memory.sensitivity = sensitivity
    if confidence is not None:
        memory.confidence = max(0.0, min(confidence, 1.0))
    if valid_until is not None:
        memory.valid_until = valid_until
    if retention_days is not None:
        memory.retention_days = retention_days if retention_days > 0 else None
    if content_changed:
        await _ensure_topic_allowed(
            session, memory.workspace_id, memory.user_id, memory.title, memory.content
        )
    if metadata is not None:
        memory.memory_metadata = dict(metadata)
    if memory.scope_type == "project" and memory.project_id is None:
        raise MemoryError("invalid_scope", "Project memory requires project_id")
    if memory.scope_type == "agent" and memory.agent_id is None:
        raise MemoryError("invalid_scope", "Agent memory requires agent_id")
    memory.content_hash = memory_hash(memory.title, memory.content)
    memory.version += 1
    memory.updated_at = datetime.now(UTC)
    if content_changed:
        memory.embedding = await _embed_text(
            memory.title + "\n" + memory.content, get_settings()
        )
    session.add(
        MemoryVersion(
            memory_id=memory.id,
            version=memory.version,
            snapshot=_snapshot(memory),
            changed_by=changed_by,
            change_reason=change_reason[:300],
        )
    )
    await session.flush()
    if auto_link:
        await auto_link_memory(session, memory)
    return memory


async def delete_memory(session: AsyncSession, memory: AgentMemory) -> None:
    await session.execute(
        delete(MemoryRelation).where(
            or_(
                (MemoryRelation.from_type == "memory")
                & (MemoryRelation.from_id == memory.id),
                (MemoryRelation.to_type == "memory")
                & (MemoryRelation.to_id == memory.id),
            )
        )
    )
    await session.delete(memory)
    await session.flush()


async def list_memory_versions(
    session: AsyncSession, memory: AgentMemory
) -> list[MemoryVersion]:
    return list(
        (
            await session.execute(
                select(MemoryVersion)
                .where(MemoryVersion.memory_id == memory.id)
                .order_by(MemoryVersion.version.desc())
            )
        ).scalars()
    )


async def restore_memory_version(
    session: AsyncSession,
    memory: AgentMemory,
    version: int,
    *,
    changed_by: UUID,
) -> AgentMemory:
    row = (
        await session.execute(
            select(MemoryVersion).where(
                MemoryVersion.memory_id == memory.id,
                MemoryVersion.version == version,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise MemoryError("not_found", "Memory version not found")
    snapshot = row.snapshot
    memory.title = str(snapshot.get("title") or memory.title)[:120]
    memory.content = str(snapshot.get("content") or memory.content)
    memory.category = str(snapshot.get("category") or memory.category)
    memory.scope_type = str(snapshot.get("scope_type") or memory.scope_type)
    memory.scope = "user" if memory.scope_type == "global" else "workspace"
    project_id = snapshot.get("project_id")
    memory.project_id = UUID(str(project_id)) if project_id else None
    agent_id = snapshot.get("agent_id")
    memory.agent_id = UUID(str(agent_id)) if agent_id else None
    memory.tags = list(snapshot.get("tags") or [])
    memory.status = str(snapshot.get("status") or "active")
    memory.importance = int(snapshot.get("importance") or memory.importance)
    memory.enabled = bool(snapshot.get("enabled", True))
    memory.pinned = bool(snapshot.get("pinned", False))
    memory.favorite = bool(snapshot.get("favorite", False))
    memory.sensitivity = str(snapshot.get("sensitivity") or memory.sensitivity)
    memory.confidence = float(snapshot.get("confidence") or memory.confidence)
    retention_days = snapshot.get("retention_days")
    memory.retention_days = (
        int(retention_days) if retention_days is not None else memory.retention_days
    )
    memory.content_hash = memory_hash(memory.title, memory.content)
    memory.version += 1
    memory.updated_at = datetime.now(UTC)
    memory.embedding = await _embed_text(
        memory.title + "\n" + memory.content, get_settings()
    )
    session.add(
        MemoryVersion(
            memory_id=memory.id,
            version=memory.version,
            snapshot=_snapshot(memory),
            changed_by=changed_by,
            change_reason=f"restored from v{version}",
        )
    )
    await session.flush()
    await auto_link_memory(session, memory)
    return memory


async def batch_update_memories(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    memory_ids: list[UUID],
    *,
    status: str | None = None,
    category: str | None = None,
    scope_type: str | None = None,
    project_id: UUID | None = None,
    agent_id: UUID | None = None,
    enabled: bool | None = None,
    tags: list[str] | None = None,
) -> int:
    rows = list(
        (
            await session.execute(
                select(AgentMemory).where(
                    AgentMemory.workspace_id == workspace_id,
                    AgentMemory.user_id == user_id,
                    AgentMemory.id.in_(memory_ids[:100]),
                )
            )
        ).scalars()
    )
    for memory in rows:
        await update_memory(
            session,
            memory,
            status=status,
            category=category,
            scope_type=scope_type,
            project_id=project_id,
            agent_id=agent_id,
            enabled=enabled,
            tags=tags,
            changed_by=user_id,
            change_reason="batch update",
        )
    return len(rows)


async def retention_preview(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    settings = await get_memory_settings(session, workspace_id, user_id)
    current = now or datetime.now(UTC)
    global_days = settings.retention_days
    rows = list(
        (
            await session.execute(
                select(AgentMemory)
                .where(
                    *_personal_filters(workspace_id, user_id),
                    AgentMemory.status == "active",
                    AgentMemory.enabled.is_(True),
                    AgentMemory.pinned.is_(False),
                    AgentMemory.favorite.is_(False),
                )
                .limit(5000)
            )
        ).scalars()
    )
    items = []
    for memory in rows:
        days = memory.retention_days or global_days
        if not days or days <= 0:
            continue
        if _as_aware(memory.updated_at) < current - timedelta(days=days):
            items.append(
                {
                    "id": memory.id,
                    "title": memory.title,
                    "updated_at": memory.updated_at,
                    "retention_days": days,
                }
            )
    return {
        "retention_days": global_days,
        "expiring_count": len(items),
        "items": items[:50],
    }


async def expire_retention_memories(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 500,
) -> dict[str, int]:
    """Mark stale memories as expired; never hard-delete user data."""
    current = now or datetime.now(UTC)
    settings_rows = list(
        (
            await session.execute(
                select(MemorySettings).where(MemorySettings.retention_days.is_not(None))
            )
        ).scalars()
    )
    settings_map = {
        (row.workspace_id, row.user_id): int(row.retention_days)
        for row in settings_rows
        if row.retention_days
    }
    rows = list(
        (
            await session.execute(
                select(AgentMemory)
                .where(
                    AgentMemory.status == "active",
                    AgentMemory.enabled.is_(True),
                    AgentMemory.pinned.is_(False),
                    AgentMemory.favorite.is_(False),
                )
                .limit(5000)
            )
        ).scalars()
    )
    expired = 0
    for memory in rows:
        days = memory.retention_days or settings_map.get(
            (memory.workspace_id, memory.user_id)
        )
        if not days or days <= 0:
            continue
        if _as_aware(memory.updated_at) >= current - timedelta(days=days):
            continue
        await update_memory(
            session,
            memory,
            status="expired",
            change_reason="retention policy",
            changed_by=None,
            auto_link=False,
        )
        expired += 1
        if expired >= limit:
            break
    return {"scanned": len(rows), "expired": expired}


async def memory_stats(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> dict[str, object]:
    base = _personal_filters(workspace_id, user_id)

    async def count(*conditions) -> int:
        return int(
            (
                await session.execute(
                    select(func.count()).select_from(AgentMemory).where(*base, *conditions)
                )
            ).scalar_one()
        )

    total = await count()
    active = await count(AgentMemory.status == "active")
    pending = await count(AgentMemory.status == "candidate")
    candidates_pending = int(
        (
            await session.execute(
                select(func.count())
                .select_from(MemoryCandidate)
                .where(
                    MemoryCandidate.workspace_id == workspace_id,
                    MemoryCandidate.user_id == user_id,
                    MemoryCandidate.status == "pending",
                )
            )
        ).scalar_one()
    )
    conflicts = await count(AgentMemory.status == "conflict")
    expired = await count(AgentMemory.status == "expired")
    archived = await count(AgentMemory.status == "archived")
    category_rows = (
        await session.execute(
            select(AgentMemory.category, func.count())
            .where(*base)
            .group_by(AgentMemory.category)
        )
    ).all()
    scope_rows = (
        await session.execute(
            select(AgentMemory.scope_type, func.count())
            .where(*base)
            .group_by(AgentMemory.scope_type)
        )
    ).all()
    status_rows = (
        await session.execute(
            select(AgentMemory.status, func.count())
            .where(*base)
            .group_by(AgentMemory.status)
        )
    ).all()
    source_rows = (
        await session.execute(
            select(AgentMemory.source_type, func.count())
            .where(*base)
            .group_by(AgentMemory.source_type)
        )
    ).all()
    all_rows = list(
        (
            await session.execute(
                select(AgentMemory).where(*base).order_by(AgentMemory.updated_at.desc()).limit(5000)
            )
        ).scalars()
    )
    completeness_buckets = {"complete": 0, "partial": 0, "sparse": 0}
    completeness_total = 0
    for memory in all_rows:
        score = 0
        if memory.title:
            score += 15
        content_length = len(memory.content or "")
        if content_length >= 40:
            score += 20
        if content_length >= 120:
            score += 15
        if memory.category != "fact":
            score += 10
        if memory.tags:
            score += 10
        if memory.source_type != "manual":
            score += 10
        if memory.embedding is not None:
            score += 10
        if memory.importance >= 4:
            score += 5
        if memory.project_id is not None or memory.agent_id is not None:
            score += 5
        completeness_total += score
        if score >= 80:
            completeness_buckets["complete"] += 1
        elif score >= 50:
            completeness_buckets["partial"] += 1
        else:
            completeness_buckets["sparse"] += 1
    settings_row = (
        await session.execute(
            select(MemorySettings).where(
                MemorySettings.workspace_id == workspace_id,
                MemorySettings.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    expiring_soon = int(
        (
            await session.execute(
                select(func.count())
                .select_from(AgentMemory)
                .where(
                    *base,
                    AgentMemory.status == "active",
                    AgentMemory.valid_until.is_not(None),
                    AgentMemory.valid_until <= now + timedelta(days=7),
                )
            )
        ).scalar_one()
    )
    stale_cutoff = now - timedelta(days=30)
    stale = int(
        (
            await session.execute(
                select(func.count())
                .select_from(AgentMemory)
                .where(
                    *base,
                    AgentMemory.status == "active",
                    AgentMemory.updated_at < stale_cutoff,
                    or_(
                        AgentMemory.last_used_at.is_(None),
                        AgentMemory.last_used_at < stale_cutoff,
                    ),
                )
            )
        ).scalar_one()
    )
    usage_filters = [
        MemoryUsageEvent.workspace_id == workspace_id,
        MemoryUsageEvent.user_id == user_id,
    ]
    usage_total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(MemoryUsageEvent)
                .where(*usage_filters)
            )
        ).scalar_one()
    )
    usage_chars = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(MemoryUsageEvent.injected_chars), 0)).where(
                    *usage_filters
                )
            )
        ).scalar_one()
    )
    usage_model_rows = (
        await session.execute(
            select(
                MemoryUsageEvent.provider_id,
                MemoryUsageEvent.model,
                func.count(),
                func.coalesce(func.sum(MemoryUsageEvent.injected_chars), 0),
            )
            .where(*usage_filters)
            .group_by(MemoryUsageEvent.provider_id, MemoryUsageEvent.model)
            .order_by(func.count().desc())
            .limit(10)
        )
    ).all()
    usage_context_rows = (
        await session.execute(
            select(MemoryUsageEvent.context_type, func.count())
            .where(*usage_filters)
            .group_by(MemoryUsageEvent.context_type)
        )
    ).all()
    usage_agent_rows = (
        await session.execute(
            select(AgentMemory.agent_id, func.count())
            .select_from(MemoryUsageEvent)
            .join(AgentMemory, AgentMemory.id == MemoryUsageEvent.memory_id)
            .where(*usage_filters)
            .group_by(AgentMemory.agent_id)
            .order_by(func.count().desc())
            .limit(10)
        )
    ).all()
    usage_project_rows = (
        await session.execute(
            select(AgentMemory.project_id, func.count())
            .select_from(MemoryUsageEvent)
            .join(AgentMemory, AgentMemory.id == MemoryUsageEvent.memory_id)
            .where(*usage_filters)
            .group_by(AgentMemory.project_id)
            .order_by(func.count().desc())
            .limit(10)
        )
    ).all()
    usage_conversation_rows = (
        await session.execute(
            select(MemoryUsageEvent.context_id, func.count())
            .where(*usage_filters, MemoryUsageEvent.context_type == "chat")
            .group_by(MemoryUsageEvent.context_id)
            .order_by(func.count().desc())
            .limit(5)
        )
    ).all()
    recent = list(
        (
            await session.execute(
                select(AgentMemory)
                .where(*base)
                .order_by(AgentMemory.updated_at.desc())
                .limit(5)
            )
        ).scalars()
    )
    top_used = list(
        (
            await session.execute(
                select(AgentMemory)
                .where(*base)
                .order_by(AgentMemory.use_count.desc(), AgentMemory.last_used_at.desc())
                .limit(5)
            )
        ).scalars()
    )
    return {
        "total": total,
        "active": active,
        "pending": pending,
        "candidates_pending": candidates_pending,
        "conflict": conflicts,
        "expired": expired,
        "archived": archived,
        "by_category": {str(key): int(value) for key, value in category_rows},
        "by_scope": {str(key): int(value) for key, value in scope_rows},
        "by_status": {str(key): int(value) for key, value in status_rows},
        "by_source": {str(key): int(value) for key, value in source_rows},
        "completeness": {
            "average_score": round(
                completeness_total / len(all_rows), 1
            )
            if all_rows
            else 0.0,
            **completeness_buckets,
        },
        "retention_days": settings_row.retention_days if settings_row else None,
        "expiring_soon": expiring_soon,
        "stale": stale,
        "active_chars": sum(
            len(memory.content or "")
            for memory in all_rows
            if memory.status == "active"
        ),
        "usage_total": usage_total,
        "usage_chars": usage_chars,
        "usage_by_model": [
            {
                "provider_id": provider_id or "",
                "model": model or "",
                "count": int(count),
                "injected_chars": int(chars or 0),
            }
            for provider_id, model, count, chars in usage_model_rows
        ],
        "usage_by_context": {
            str(key): int(value) for key, value in usage_context_rows
        },
        "usage_by_agent": [
            {"agent_id": str(agent_id) if agent_id else None, "count": int(count)}
            for agent_id, count in usage_agent_rows
        ],
        "usage_by_project": [
            {"project_id": str(project_id) if project_id else None, "count": int(count)}
            for project_id, count in usage_project_rows
        ],
        "usage_by_conversation": [
            {"context_id": str(context_id) if context_id else None, "count": int(count)}
            for context_id, count in usage_conversation_rows
        ],
        "recent": recent,
        "top_used": top_used,
    }


async def list_memory_relations(
    session: AsyncSession, workspace_id: UUID, user_id: UUID, memory_id: UUID
) -> list[MemoryRelation]:
    return list(
        (
            await session.execute(
                select(MemoryRelation)
                .where(
                    MemoryRelation.workspace_id == workspace_id,
                    MemoryRelation.user_id == user_id,
                    or_(
                        (MemoryRelation.from_type == "memory")
                        & (MemoryRelation.from_id == memory_id),
                        (MemoryRelation.to_type == "memory")
                        & (MemoryRelation.to_id == memory_id),
                    ),
                )
                .order_by(MemoryRelation.created_at.desc())
            )
        ).scalars()
    )


async def create_memory_relation(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    from_type: str,
    from_id: UUID,
    to_type: str,
    to_id: UUID,
    relation_type: str,
    basis: str = "",
) -> MemoryRelation:
    if relation_type not in RELATION_TYPES:
        raise MemoryError("invalid_relation", "Invalid relation type")
    if from_type not in {"memory", "project", "document", "agent"}:
        raise MemoryError("invalid_relation", "Invalid source type")
    if to_type not in {"memory", "project", "document", "agent"}:
        raise MemoryError("invalid_relation", "Invalid target type")
    existing = (
        await session.execute(
            select(MemoryRelation).where(
                MemoryRelation.from_type == from_type,
                MemoryRelation.from_id == from_id,
                MemoryRelation.to_type == to_type,
                MemoryRelation.to_id == to_id,
                MemoryRelation.relation_type == relation_type,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    relation = MemoryRelation(
        workspace_id=workspace_id,
        user_id=user_id,
        from_type=from_type,
        from_id=from_id,
        to_type=to_type,
        to_id=to_id,
        relation_type=relation_type,
        basis=basis[:500],
    )
    session.add(relation)
    await session.flush()
    return relation


async def delete_memory_relation(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    relation_id: UUID,
) -> None:
    row = (
        await session.execute(
            select(MemoryRelation).where(
                MemoryRelation.id == relation_id,
                MemoryRelation.workspace_id == workspace_id,
                MemoryRelation.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise MemoryError("not_found", "Relation not found")
    await session.delete(row)
    await session.flush()


async def record_memory_usage(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    memories: list[tuple[AgentMemory, float | None, int]],
    context_type: str,
    context_id: str | None,
    provider_id: str | None,
    model: str | None,
) -> None:
    now = datetime.now(UTC)
    for memory, relevance, injected_chars in memories:
        session.add(
            MemoryUsageEvent(
                workspace_id=workspace_id,
                user_id=user_id,
                memory_id=memory.id,
                context_type=context_type,
                context_id=context_id,
                provider_id=provider_id,
                model=model,
                relevance=relevance,
                injected_chars=max(injected_chars, 0),
            )
        )
        memory.use_count += 1
        memory.last_used_at = now
    await session.flush()


async def list_memory_usage(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    *,
    limit: int = 50,
) -> list[tuple[MemoryUsageEvent, str]]:
    rows = (
        await session.execute(
            select(MemoryUsageEvent, AgentMemory.title)
            .outerjoin(AgentMemory, AgentMemory.id == MemoryUsageEvent.memory_id)
            .where(
                MemoryUsageEvent.workspace_id == workspace_id,
                MemoryUsageEvent.user_id == user_id,
            )
            .order_by(MemoryUsageEvent.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
    ).all()
    return [(row[0], row[1] or "") for row in rows]


def _cross_model_allowed(
    memory: AgentMemory, provider_id: str | None, model: str | None
) -> bool:
    metadata = memory.memory_metadata or {}
    memory_provider = metadata.get("provider_id")
    memory_model = metadata.get("model")
    if not memory_provider and not memory_model:
        return True
    if provider_id is not None and memory_provider not in {None, provider_id}:
        return False
    if model is not None and memory_model not in {None, model}:
        return False
    return True


def _base_score(memory: AgentMemory) -> float:
    score = 0.02 * memory.importance
    score += min(memory.use_count, 20) * 0.001
    if memory.pinned:
        score += 0.02
    if memory.favorite:
        score += 0.01
    updated_at = memory.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    age_days = max((datetime.now(UTC) - updated_at).total_seconds(), 0) / 86400
    score += max(0.0, 1 - age_days / 180) * 0.02
    return score


async def select_memories(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    agent_id: UUID | None,
    query: str,
    limit: int,
    max_chars: int,
    touch: bool = False,
    project_id: UUID | None = None,
    excluded_ids: list[UUID] | None = None,
    provider_id: str | None = None,
    model: str | None = None,
    allow_cross_model: bool = True,
    allowed_scopes: frozenset[str] | set[str] | None = None,
    allowed_provider_ids: list[str] | None = None,
    allowed_models: list[str] | None = None,
    allowed_agent_ids: list[str] | None = None,
) -> MemorySelection:
    now = datetime.now(UTC)
    if allowed_scopes is not None and not allowed_scopes:
        return MemorySelection(block="", items=[])
    if (
        allowed_provider_ids
        and provider_id is not None
        and provider_id not in allowed_provider_ids
    ):
        return MemorySelection(block="", items=[])
    if allowed_models and model is not None and model not in allowed_models:
        return MemorySelection(block="", items=[])
    if (
        allowed_agent_ids
        and agent_id is not None
        and str(agent_id) not in allowed_agent_ids
    ):
        return MemorySelection(block="", items=[])
    conditions = [
        *_personal_filters(workspace_id, user_id),
        AgentMemory.status == "active",
        AgentMemory.enabled.is_(True),
        or_(AgentMemory.valid_until.is_(None), AgentMemory.valid_until > now),
        or_(
            AgentMemory.scope_type == "global",
            *(
                [
                    and_(
                        AgentMemory.scope_type == "agent",
                        AgentMemory.agent_id == agent_id,
                    )
                ]
                if agent_id is not None
                else []
            ),
            *(
                [
                    and_(
                        AgentMemory.scope_type == "project",
                        AgentMemory.project_id == project_id,
                    )
                ]
                if project_id is not None
                else []
            ),
        ),
    ]
    if allowed_scopes is not None:
        conditions.append(AgentMemory.scope_type.in_(sorted(allowed_scopes)))
    if excluded_ids:
        conditions.append(AgentMemory.id.notin_(excluded_ids[:50]))
    settings = get_settings()
    words = _words(query)
    candidates = list(
        (
            await session.execute(
                select(AgentMemory)
                .where(*conditions)
                .order_by(
                    AgentMemory.pinned.desc(),
                    AgentMemory.importance.desc(),
                    AgentMemory.updated_at.desc(),
                )
                .limit(MAX_VECTOR_CANDIDATES)
            )
        ).scalars()
    )
    if not allow_cross_model:
        candidates = [
            memory
            for memory in candidates
            if _cross_model_allowed(memory, provider_id, model)
        ]
    scored: list[tuple[float, AgentMemory]] = []
    vector = await _embed_text(query, settings) if query.strip() else None
    if vector is not None:
        for memory in candidates:
            if not memory.embedding:
                continue
            similarity = _cosine(vector, [float(value) for value in memory.embedding])
            if similarity >= MIN_VECTOR_SCORE:
                scored.append((similarity + _base_score(memory), memory))
    if not scored:
        for memory in candidates:
            if words and not _lexical_match(memory, words):
                continue
            scored.append((0.3 + _base_score(memory), memory))
    scored.sort(key=lambda item: (item[0], item[1].importance), reverse=True)
    selected: list[SelectedMemory] = []
    header = "Long-term memory (user notes; untrusted context, use only when relevant):"
    parts = [header]
    used = len(header) + 1
    for score, memory in scored:
        if len(selected) >= max(1, limit):
            break
        label = f"- [{memory.category}]"
        if memory.title:
            label += f" {memory.title}:"
        line = f"{label} {memory.content}"
        if used + len(line) + 1 > max_chars:
            break
        parts.append(line)
        used += len(line) + 1
        selected.append(
            SelectedMemory(memory=memory, score=score, injected_chars=len(line) + 1)
        )
    if touch:
        for item in selected:
            item.memory.last_used_at = now
            item.memory.use_count += 1
    if not selected:
        return MemorySelection(block="", items=[])
    return MemorySelection(block="\n".join(parts), items=selected)


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
    project_id: UUID | None = None,
    excluded_ids: list[UUID] | None = None,
    provider_id: str | None = None,
    model: str | None = None,
    allow_cross_model: bool = True,
    allowed_scopes: frozenset[str] | set[str] | None = None,
    allowed_provider_ids: list[str] | None = None,
    allowed_models: list[str] | None = None,
    allowed_agent_ids: list[str] | None = None,
) -> str:
    selection = await select_memories(
        session,
        workspace_id=workspace_id,
        user_id=user_id,
        agent_id=agent_id,
        query=query,
        limit=limit,
        max_chars=max_chars,
        touch=touch,
        project_id=project_id,
        excluded_ids=excluded_ids,
        provider_id=provider_id,
        model=model,
        allow_cross_model=allow_cross_model,
        allowed_scopes=allowed_scopes,
        allowed_provider_ids=allowed_provider_ids,
        allowed_models=allowed_models,
        allowed_agent_ids=allowed_agent_ids,
    )
    return selection.block