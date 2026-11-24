"""Async memory extraction from finished chat turns and candidate review."""

import json
import logging
import re
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.metrics import metrics
from app.models import (
    AgentMemory,
    Conversation,
    MemoryCandidate,
    MemoryExtractionRun,
    Message,
)
from app.providers.base import ChatMessage
from app.providers.registry import ProviderRegistry
from app.services.memories import (
    CATEGORIES,
    DEFAULT_ALLOWED_CATEGORIES,
    SCOPE_TYPES,
    MemoryError,
    _contains_secret,
    _cosine,
    _embed_text,
    create_memory,
    get_memory_settings,
    memory_hash,
    update_memory,
)
from app.services.model_stream import ModelCompletion
from app.services.provider_configs import build_user_registry
from app.services.usage_ledger import SOURCE_MEMORY_EXTRACTION

logger = logging.getLogger(__name__)

EXPLICIT_PATTERN = re.compile(
    r"(记住|记一下|请记住|帮我记住|别忘|不要忘|"
    r"remember (?:that|this)|keep in mind|save (?:this|that) (?:as|to) memory)",
    re.IGNORECASE,
)
JSON_PATTERN = re.compile(r"[\[{].*[\]}]", re.DOTALL)
DUPLICATE_THRESHOLD = 0.92
UPDATE_THRESHOLD = 0.75
EXTRACTION_SYSTEM_PROMPT = (
    "You extract long-term memories from one chat turn. "
    "Only keep stable preferences, durable personal background, project facts, "
    "technical decisions, reusable experience, or explicit user requests to remember. "
    "Never store passwords, API keys, tokens, or other secrets. "
    "Do not store temporary tasks, greetings, or one-off details. "
    "Return ONLY a JSON array. Each item has keys: "
    "category (preference|profile|project|technical|experience|decision|relation|fact), "
    "title (short), content (self-contained sentence), scope_type (global|project|agent), "
    "confidence (0-1), tags (string array), reason (short). "
    "Return [] when nothing is worth remembering."
)


class ExtractedMemory(BaseModel):
    category: str = "fact"
    title: str = ""
    content: str
    scope_type: str = "global"
    confidence: float = Field(default=0.6, ge=0, le=1)
    tags: list[str] = Field(default_factory=list)
    reason: str = ""


def explicit_memory_request(text: str) -> bool:
    return bool(EXPLICIT_PATTERN.search(text or ""))


def parse_candidates(text: str) -> list[ExtractedMemory]:
    match = JSON_PATTERN.search(text)
    if match is None:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = data.get("memories") or data.get("candidates") or []
    if not isinstance(data, list):
        return []
    result: list[ExtractedMemory] = []
    for item in data:
        try:
            candidate = ExtractedMemory.model_validate(item)
        except ValidationError:
            continue
        if candidate.content.strip():
            result.append(candidate)
    return result


async def _create_run(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    message_id: UUID,
) -> MemoryExtractionRun | None:
    run = MemoryExtractionRun(
        workspace_id=workspace_id,
        user_id=user_id,
        source_type="message",
        source_id=str(message_id),
        status="running",
    )
    session.add(run)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return None
    await session.refresh(run)
    return run


async def _finish_run(
    session: AsyncSession,
    run: MemoryExtractionRun,
    *,
    status: str,
    count: int = 0,
    error_code: str | None = None,
) -> None:
    run.status = status
    run.candidate_count = count
    run.error_code = error_code
    run.finished_at = datetime.now(UTC)
    await session.commit()


async def _load_context(
    session: AsyncSession, message: Message
) -> tuple[Conversation | None, Message | None]:
    conversation = await session.get(Conversation, message.conversation_id)
    user_message = (
        await session.execute(
            select(Message)
            .where(
                Message.conversation_id == message.conversation_id,
                Message.role == "user",
                Message.created_at <= message.created_at,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return conversation, user_message


async def _existing_memories(
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
                .order_by(AgentMemory.updated_at.desc())
                .limit(100)
            )
        ).scalars()
    )


async def _classify(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    candidate: ExtractedMemory,
    existing: list[AgentMemory],
) -> tuple[str, AgentMemory | None, str]:
    content_hash = memory_hash(candidate.title, candidate.content)
    embedding = await _embed_text(
        f"{candidate.title}\n{candidate.content}", get_settings()
    )
    best: AgentMemory | None = None
    best_score = 0.0
    for memory in existing:
        if memory.content_hash == content_hash:
            return "duplicate", memory, "identical memory"
        if embedding is not None and memory.embedding:
            score = _cosine(embedding, [float(value) for value in memory.embedding])
            if score > best_score:
                best_score = score
                best = memory
    if best is not None and best_score >= DUPLICATE_THRESHOLD:
        return "duplicate", best, f"similar memory ({best_score:.2f})"
    if (
        best is not None
        and best_score >= UPDATE_THRESHOLD
        and best.category == candidate.category
    ):
        return "update", best, f"possible update ({best_score:.2f})"
    return "create", None, candidate.reason


async def _apply_candidate(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    candidate: MemoryCandidate,
) -> AgentMemory:
    metadata: dict[str, object] = {}
    if candidate.extracted_by:
        provider_id, _, model = candidate.extracted_by.partition("/")
        if provider_id:
            metadata["provider_id"] = provider_id
        if model:
            metadata["model"] = model
    if (
        candidate.suggested_action == "duplicate"
        and candidate.target_memory_id is not None
    ):
        target = await session.get(AgentMemory, candidate.target_memory_id)
        if target is not None and target.user_id == user_id:
            candidate.status = "accepted"
            candidate.reviewed_at = datetime.now(UTC)
            return target
    if candidate.suggested_action == "update" and candidate.target_memory_id is not None:
        target = await session.get(AgentMemory, candidate.target_memory_id)
        if target is not None and target.user_id == user_id:
            memory = await update_memory(
                session,
                target,
                title=candidate.title,
                content=candidate.content,
                category=candidate.category,
                tags=candidate.tags,
                confidence=candidate.confidence,
                metadata=metadata or None,
                change_reason="memory extraction update",
                changed_by=user_id,
            )
            candidate.status = "merged"
            candidate.reviewed_at = datetime.now(UTC)
            return memory
    memory = await create_memory(
        session,
        workspace_id=workspace_id,
        user_id=user_id,
        content=candidate.content,
        title=candidate.title,
        scope_type=candidate.scope_type,
        category=candidate.category,
        project_id=candidate.project_id,
        agent_id=candidate.agent_id,
        tags=candidate.tags,
        confidence=candidate.confidence,
        source_type=candidate.source_type,
        source_id=candidate.source_id,
        source_ref=candidate.source_ref,
        metadata=metadata or None,
    )
    candidate.status = "accepted"
    candidate.target_memory_id = memory.id
    candidate.reviewed_at = datetime.now(UTC)
    return memory


async def run_memory_extraction_for_message(
    message_id: UUID,
    *,
    registry: ProviderRegistry | None = None,
    settings: Settings | None = None,
) -> dict[str, object]:
    current = settings or get_settings()
    async with SessionLocal() as session:
        message = await session.get(Message, message_id)
        if message is None or message.role != "assistant":
            return {"status": "skipped", "reason": "not_assistant"}
        if message.status not in {"completed", "cancelled"}:
            return {"status": "skipped", "reason": "not_final"}
        conversation, user_message = await _load_context(session, message)
        if conversation is None:
            return {"status": "skipped", "reason": "conversation_missing"}
        memory_settings = await get_memory_settings(
            session, conversation.workspace_id, message.user_id
        )
        await session.commit()
        if not memory_settings.enabled:
            return {"status": "skipped", "reason": "memory_disabled"}
        if conversation.agent and not memory_settings.allow_agent_extract:
            return {"status": "skipped", "reason": "agent_extraction_disabled"}
        if conversation.project_id is not None and not memory_settings.allow_project_extract:
            return {"status": "skipped", "reason": "project_extraction_disabled"}
        user_text = (user_message.content if user_message else "") or ""
        explicit = explicit_memory_request(user_text)
        if not memory_settings.auto_extract and not explicit:
            return {"status": "skipped", "reason": "extraction_disabled"}

        run = await _create_run(
            session,
            workspace_id=conversation.workspace_id,
            user_id=message.user_id,
            message_id=message.id,
        )
        if run is None:
            return {"status": "skipped", "reason": "already_processed"}

        try:
            provider_id = (
                current.memory_extraction_provider_id.strip()
                or message.provider_id
                or conversation.provider_id
            )
            model = (
                current.memory_extraction_model.strip()
                or message.model
                or conversation.model
            )
            active_registry = registry
            if active_registry is None:
                active_registry = await build_user_registry(
                    session, conversation.workspace_id, message.user_id
                )
            try:
                provider = active_registry.get(provider_id)
            except Exception:
                await _finish_run(
                    session, run, status="failed", error_code="provider_unavailable"
                )
                return {"status": "failed", "reason": "provider_unavailable"}

            allowed = memory_settings.allowed_categories or DEFAULT_ALLOWED_CATEGORIES
            blocked = [item.casefold() for item in memory_settings.blocked_topics or []]
            recent = await _existing_memories(
                session, conversation.workspace_id, message.user_id
            )
            recent_titles = [memory.title for memory in recent[:10]]
            turn = (
                f"User:\n{user_text}\n\nAssistant:\n{message.content or ''}"
            )[: current.memory_extraction_max_chars]
            prompt = (
                f"Allowed categories: {', '.join(allowed)}\n"
                f"Blocked topics: {', '.join(blocked) or '(none)'}\n"
                f"Existing memory titles: {json.dumps(recent_titles, ensure_ascii=False)}\n"
                f"Explicit remember request: {explicit}\n\n"
                f"Chat turn:\n{turn}"
            )
            completion = ModelCompletion(
                provider=provider,
                model=model,
                messages=[
                    ChatMessage(role="system", content=EXTRACTION_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=prompt),
                ],
                opts={"temperature": 0, "max_tokens": 1800},
                workspace_id=conversation.workspace_id,
                user_id=message.user_id,
                source=SOURCE_MEMORY_EXTRACTION,
            )
            result = await completion.run()
            if result.status != "completed":
                await _finish_run(
                    session,
                    run,
                    status="failed",
                    error_code=result.error_code or "extraction_failed",
                )
                return {"status": "failed", "reason": result.error_code}

            parsed = parse_candidates(result.content)
            saved = 0
            pending = 0
            for extracted in parsed[: current.memory_extraction_max_candidates]:
                if extracted.confidence < current.memory_extraction_min_confidence:
                    continue
                if extracted.category not in CATEGORIES:
                    continue
                if _contains_secret(extracted.content):
                    continue
                haystack = f"{extracted.title} {extracted.content}".casefold()
                if any(topic in haystack for topic in blocked):
                    continue
                scope_type = extracted.scope_type
                if scope_type not in SCOPE_TYPES:
                    scope_type = "global"
                requested_scope = scope_type
                project_id = (
                    conversation.project_id if scope_type == "project" else None
                )
                agent_id = (
                    conversation.custom_agent_id if scope_type == "agent" else None
                )
                scope_unavailable = False
                if scope_type == "project" and project_id is None:
                    scope_type = "global"
                    scope_unavailable = True
                if scope_type == "agent" and agent_id is None:
                    scope_type = "global"
                    scope_unavailable = True
                action, target, reason = await _classify(
                    session,
                    workspace_id=conversation.workspace_id,
                    user_id=message.user_id,
                    candidate=extracted,
                    existing=recent,
                )
                if scope_unavailable:
                    reason = (
                        f"scope_unavailable ({requested_scope}); "
                        f"review before saving. {reason}"
                    )[:2000]
                candidate = MemoryCandidate(
                    workspace_id=conversation.workspace_id,
                    user_id=message.user_id,
                    project_id=project_id,
                    agent_id=agent_id,
                    target_memory_id=target.id if target is not None else None,
                    source_type="chat",
                    source_id=str(message.id),
                    source_ref={
                        "conversation_id": str(conversation.id),
                        "message_id": str(message.id),
                    },
                    extracted_by=f"{provider_id}/{model}",
                    suggested_action=action,
                    category=extracted.category,
                    scope_type=scope_type,
                    title=extracted.title[:120],
                    content=extracted.content,
                    tags=extracted.tags,
                    confidence=extracted.confidence,
                    sensitivity="sensitive" if scope_unavailable else "normal",
                    reason=reason[:2000],
                    status="duplicate" if action == "duplicate" else "pending",
                )
                session.add(candidate)
                await session.flush()
                auto_save = (
                    not scope_unavailable
                    and extracted.category in allowed
                    and memory_settings.auto_save
                    and not memory_settings.require_confirmation
                )
                if action == "duplicate":
                    pending += 1
                elif (explicit and not scope_unavailable) or auto_save:
                    await _apply_candidate(
                        session,
                        workspace_id=conversation.workspace_id,
                        user_id=message.user_id,
                        candidate=candidate,
                    )
                    saved += 1
                else:
                    pending += 1
            await _finish_run(
                session, run, status="completed", count=saved + pending
            )
            metrics.inc_counter(
                "ai_power_memory_extractions_total",
                status="completed",
                explicit=str(explicit).lower(),
            )
            return {
                "status": "completed",
                "saved": saved,
                "pending": pending,
                "explicit": explicit,
            }
        except Exception as exc:
            logger.exception("memory extraction failed for message %s", message_id)
            await session.rollback()
            run = await session.get(MemoryExtractionRun, run.id)
            if run is not None:
                await _finish_run(
                    session, run, status="failed", error_code=type(exc).__name__
                )
            metrics.inc_counter(
                "ai_power_memory_extractions_total", status="failed"
            )
            return {"status": "failed", "reason": type(exc).__name__}


async def list_candidates(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    *,
    status: str = "pending",
    limit: int = 50,
) -> list[MemoryCandidate]:
    return list(
        (
            await session.execute(
                select(MemoryCandidate)
                .where(
                    MemoryCandidate.workspace_id == workspace_id,
                    MemoryCandidate.user_id == user_id,
                    MemoryCandidate.status == status,
                )
                .order_by(MemoryCandidate.created_at.desc())
                .limit(max(1, min(limit, 200)))
            )
        ).scalars()
    )


async def get_candidate(
    session: AsyncSession, workspace_id: UUID, user_id: UUID, candidate_id: UUID
) -> MemoryCandidate:
    row = await session.get(MemoryCandidate, candidate_id)
    if (
        row is None
        or row.workspace_id != workspace_id
        or row.user_id != user_id
    ):
        raise MemoryError("not_found", "Memory candidate not found")
    return row


async def accept_candidate(
    session: AsyncSession,
    candidate: MemoryCandidate,
    *,
    user_id: UUID,
) -> AgentMemory:
    if candidate.status not in {"pending", "duplicate"}:
        raise MemoryError("invalid_status", "Candidate cannot be accepted")
    if candidate.scope_type == "project" and candidate.project_id is None:
        raise MemoryError(
            "scope_context_missing",
            "Project memory requires a project; edit the candidate or use global scope",
        )
    if candidate.scope_type == "agent" and candidate.agent_id is None:
        raise MemoryError(
            "scope_context_missing",
            "Agent memory requires an agent; edit the candidate or use global scope",
        )
    memory = await _apply_candidate(
        session,
        workspace_id=candidate.workspace_id,
        user_id=user_id,
        candidate=candidate,
    )
    await session.flush()
    metrics.inc_counter("ai_power_memory_candidates_total", action="accepted")
    return memory


async def reject_candidate(
    session: AsyncSession, candidate: MemoryCandidate
) -> None:
    if candidate.status not in {"pending", "duplicate"}:
        raise MemoryError("invalid_status", "Candidate cannot be rejected")
    candidate.status = "rejected"
    candidate.reviewed_at = datetime.now(UTC)
    await session.flush()
    metrics.inc_counter("ai_power_memory_candidates_total", action="rejected")


async def create_project_memory_candidate(
    session: AsyncSession, project, user_id: UUID
) -> MemoryCandidate | None:
    """Create a candidate from project instructions/description activity."""
    settings = await get_memory_settings(
        session, project.workspace_id, user_id
    )
    if (
        not settings.enabled
        or not settings.auto_extract
        or not settings.allow_project_extract
    ):
        return None
    content = (project.instructions or project.description or "").strip()
    if len(content) < 12:
        return None
    title = (project.name or "Project")[:120]
    content_hash = memory_hash(title, content)
    existing = (
        await session.execute(
            select(AgentMemory.id).where(
                AgentMemory.workspace_id == project.workspace_id,
                AgentMemory.user_id == user_id,
                AgentMemory.content_hash == content_hash,
                AgentMemory.status == "active",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None
    duplicate = (
        await session.execute(
            select(MemoryCandidate.id).where(
                MemoryCandidate.workspace_id == project.workspace_id,
                MemoryCandidate.user_id == user_id,
                MemoryCandidate.source_type == "project",
                MemoryCandidate.source_id == str(project.id),
                MemoryCandidate.content == content,
                MemoryCandidate.status.in_(("pending", "duplicate")),
            )
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        return None
    candidate = MemoryCandidate(
        workspace_id=project.workspace_id,
        user_id=user_id,
        project_id=project.id,
        source_type="project",
        source_id=str(project.id),
        source_ref={"project_id": str(project.id)},
        extracted_by=None,
        suggested_action="create",
        category="project",
        scope_type="project",
        title=title,
        content=content[:5000],
        tags=[],
        confidence=0.8,
        sensitivity="normal",
        reason="project activity",
        status="pending",
    )
    session.add(candidate)
    await session.flush()
    if settings.auto_save and not settings.require_confirmation:
        await _apply_candidate(
            session,
            workspace_id=project.workspace_id,
            user_id=user_id,
            candidate=candidate,
        )
    return candidate


async def schedule_memory_extraction(message_id: UUID) -> None:
    try:
        from app.services.queue import get_queue

        queue = await get_queue()
        enqueue = getattr(queue, "enqueue_memory_extraction", None)
        if enqueue is not None:
            await enqueue(message_id)
    except Exception:
        logger.warning("failed to enqueue memory extraction", exc_info=True)