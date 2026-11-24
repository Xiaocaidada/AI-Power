import hashlib
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    CodeSnippet,
    Conversation,
    ConversationShare,
    Document,
    IngestionJob,
    KnowledgeBase,
    Message,
    MessageWebSource,
    Project,
    ProjectTask,
    WorkspaceMember,
)

logger = logging.getLogger(__name__)

TASK_STATUSES = ("todo", "doing", "done")
TASK_PRIORITIES = ("low", "medium", "high")
DEFAULT_SHARE_DAYS = 7
MAX_SHARE_DAYS = 30
CODE_BLOCK_RE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)
CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[([ xX])\]\s*(.+?)\s*$")
BULLET_TASK_RE = re.compile(r"^\s*[-*]\s+(?:TODO|Task|任务)[:：]\s*(.+?)\s*$", re.I)


class ReuseError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def get_owned_message(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    conversation_id: UUID,
    message_id: UUID,
) -> tuple[Conversation, Message]:
    conversation = (
        await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == workspace_id,
                Conversation.user_id == user_id,
                Conversation.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise ReuseError("conversation_not_found", "Conversation not found")
    message = await session.get(Message, message_id)
    if message is None or message.conversation_id != conversation.id:
        raise ReuseError("message_not_found", "Message not found")
    return conversation, message


def extract_code_blocks(content: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for index, match in enumerate(CODE_BLOCK_RE.finditer(content or ""), start=1):
        language = (match.group(1) or "").strip().split()[0] if match.group(1).strip() else "text"
        code = match.group(2).strip("\n")
        if not code.strip():
            continue
        first_line = next((line.strip()[:80] for line in code.splitlines() if line.strip()), "")
        blocks.append(
            {
                "index": index,
                "language": language[:40] or "text",
                "title": first_line or f"Code block {index}",
                "code": code[:20000],
            }
        )
        if len(blocks) >= 20:
            break
    return blocks


def extract_task_candidates(content: str) -> list[dict[str, str]]:
    tasks: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in (content or "").splitlines():
        match = CHECKBOX_RE.match(line)
        if match is None:
            match = BULLET_TASK_RE.match(line)
            if match is None:
                continue
            title = match.group(1).strip()
            status = "todo"
        else:
            title = match.group(2).strip()
            status = "done" if match.group(1).lower() == "x" else "todo"
        key = title.casefold()
        if title and key not in seen:
            seen.add(key)
            tasks.append({"title": title[:300], "status": status})
        if len(tasks) >= 50:
            break
    return tasks


async def _owned_project(session: AsyncSession, workspace_id: UUID, project_id: UUID) -> Project:
    project = (
        await session.execute(
            select(Project).where(
                Project.id == project_id,
                Project.workspace_id == workspace_id,
                Project.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if project is None:
        raise ReuseError("project_not_found", "Project not found")
    return project


async def save_generated_document(
    session: AsyncSession,
    *,
    queue,
    workspace_id: UUID,
    user_id: UUID,
    kb_id: UUID,
    title: str,
    body: str,
    tags: list[str],
    source: str,
    metadata: dict[str, Any],
    source_url: str,
    stem: str = "generated",
) -> dict[str, Any]:
    """Persist generated Markdown through the normal ingestion pipeline."""
    kb = (
        await session.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id,
                KnowledgeBase.workspace_id == workspace_id,
                KnowledgeBase.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if kb is None:
        raise ReuseError("knowledge_base_not_found", "Knowledge base not found")
    heading = (title or "").strip()[:200] or "Generated document"
    content = (body or "").strip()
    if content == "":
        raise ReuseError("document_empty", "Generated document is empty")
    encoded = content.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    existing = (
        await session.execute(
            select(Document).where(
                Document.workspace_id == workspace_id,
                Document.kb_id == kb.id,
                Document.content_hash == digest,
                Document.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {
            "document_id": existing.id,
            "status": existing.status,
            "duplicate": True,
        }

    upload_dir = Path(get_settings().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^\w一-鿿.-]+", "-", heading).strip("-")[:60] or "answer"
    filename = f"{safe_title}.md"
    path = upload_dir / f"{stem}-{secret_suffix()}.md"
    path.write_bytes(encoded)
    document = Document(
        workspace_id=workspace_id,
        kb_id=kb.id,
        user_id=user_id,
        filename=filename,
        mime="text/markdown",
        size_bytes=len(encoded),
        content_hash=digest,
        storage_path=str(path),
        status="uploaded",
        tags=tags,
        folder="",
        doc_metadata={**metadata, "source": source},
        source_url=source_url,
        index_mode="hybrid",
    )
    job = IngestionJob(workspace_id=workspace_id, status="queued")
    session.add(document)
    await session.flush()
    job.document_id = document.id
    session.add(job)
    await session.commit()
    try:
        await queue.enqueue_ingestion(document.id)
    except Exception:
        logger.exception("failed to enqueue generated document %s", document.id)
        document.status = "failed"
        document.error_code = "queue_unavailable"
        job.status = "failed"
        job.error = "queue_unavailable"
        job.finished_at = datetime.now(UTC)
        await session.commit()
        path.unlink(missing_ok=True)
        raise ReuseError("queue_unavailable", "Ingestion queue unavailable") from None
    return {"document_id": document.id, "status": document.status, "duplicate": False}


async def save_answer_to_knowledge(
    session: AsyncSession,
    *,
    queue,
    workspace_id: UUID,
    user_id: UUID,
    conversation: Conversation,
    message: Message,
    kb_id: UUID,
    title: str,
) -> dict[str, Any]:
    if message.role != "assistant" or message.status != "completed":
        raise ReuseError("message_not_reusable", "Only completed assistant answers can be saved")
    web_sources = list(
        (
            await session.execute(
                select(MessageWebSource)
                .where(MessageWebSource.message_id == message.id)
                .order_by(MessageWebSource.citation_index)
            )
        ).scalars()
    )
    heading = (title or "").strip()[:200] or f"{conversation.title or 'Conversation'} answer"
    lines = [
        f"# {heading}",
        "",
        f"Source conversation: {conversation.id}",
        f"Source message: {message.id}",
        "",
        message.content or "",
    ]
    if web_sources:
        lines.extend(["", "## Web sources", ""])
        for source in web_sources:
            lines.append(f"- [{source.citation_index}] {source.title} — {source.url}")
    body = "\n".join(lines).strip() + "\n"
    return await save_generated_document(
        session,
        queue=queue,
        workspace_id=workspace_id,
        user_id=user_id,
        kb_id=kb_id,
        title=heading,
        body=body,
        tags=["generated", "conversation_answer"],
        source="conversation_answer",
        metadata={
            "conversation_id": str(conversation.id),
            "message_id": str(message.id),
        },
        source_url=f"conversation://{conversation.id}/messages/{message.id}",
        stem=str(message.id),
    )


def secret_suffix() -> str:
    return secrets.token_hex(8)


async def create_snippet(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    conversation_id: UUID | None,
    message_id: UUID | None,
    project_id: UUID | None,
    title: str,
    language: str,
    code: str,
) -> CodeSnippet:
    body = (code or "").strip()
    if body == "":
        raise ReuseError("code_required", "Code is required")
    if conversation_id is not None and message_id is not None:
        await get_owned_message(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
    if project_id is not None:
        await _owned_project(session, workspace_id, project_id)
    snippet = CodeSnippet(
        workspace_id=workspace_id,
        user_id=user_id,
        project_id=project_id,
        conversation_id=conversation_id,
        message_id=message_id,
        title=(title or "").strip()[:200],
        language=(language or "text").strip()[:40] or "text",
        code=body[:20000],
    )
    session.add(snippet)
    await session.flush()
    return snippet


async def list_snippets(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> list[CodeSnippet]:
    return list(
        (
            await session.execute(
                select(CodeSnippet)
                .where(
                    CodeSnippet.workspace_id == workspace_id,
                    CodeSnippet.user_id == user_id,
                )
                .order_by(CodeSnippet.created_at.desc())
                .limit(200)
            )
        ).scalars()
    )


async def delete_snippet(
    session: AsyncSession, snippet: CodeSnippet, workspace_id: UUID, user_id: UUID
) -> None:
    if snippet.workspace_id != workspace_id or snippet.user_id != user_id:
        raise ReuseError("snippet_not_found", "Code snippet not found")
    await session.delete(snippet)
    await session.flush()


async def create_tasks(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    project_id: UUID,
    tasks: list[dict[str, Any]],
    conversation_id: UUID | None = None,
    message_id: UUID | None = None,
) -> list[ProjectTask]:
    await _owned_project(session, workspace_id, project_id)
    if conversation_id is not None and message_id is not None:
        await get_owned_message(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )
    normalized: list[ProjectTask] = []
    for item in tasks[:50]:
        title = str(item.get("title") or "").strip()
        if title == "":
            continue
        status = str(item.get("status") or "todo")
        priority = str(item.get("priority") or "medium")
        normalized.append(
            ProjectTask(
                workspace_id=workspace_id,
                project_id=project_id,
                user_id=user_id,
                title=title[:300],
                status=status if status in TASK_STATUSES else "todo",
                priority=priority if priority in TASK_PRIORITIES else "medium",
                source_conversation_id=conversation_id,
                source_message_id=message_id,
            )
        )
    if not normalized:
        raise ReuseError("tasks_required", "At least one task is required")
    session.add_all(normalized)
    await session.flush()
    return normalized


async def list_tasks(
    session: AsyncSession, workspace_id: UUID, project_id: UUID | None
) -> list[ProjectTask]:
    conditions = [ProjectTask.workspace_id == workspace_id]
    if project_id is not None:
        conditions.append(ProjectTask.project_id == project_id)
    return list(
        (
            await session.execute(
                select(ProjectTask)
                .where(*conditions)
                .order_by(ProjectTask.created_at.desc(), ProjectTask.id.desc())
                .limit(500)
            )
        ).scalars()
    )


async def update_task(
    session: AsyncSession,
    task: ProjectTask,
    *,
    workspace_id: UUID,
    user_id: UUID,
    role: str,
    title: str | None,
    status: str | None,
    priority: str | None,
) -> ProjectTask:
    if task.workspace_id != workspace_id:
        raise ReuseError("task_not_found", "Task not found")
    if role != "owner" and task.user_id != user_id:
        raise ReuseError("forbidden", "Only the creator can edit this task")
    if title is not None:
        text = title.strip()
        if text == "":
            raise ReuseError("title_required", "Task title is required")
        task.title = text[:300]
    if status is not None:
        if status not in TASK_STATUSES:
            raise ReuseError("invalid_status", "Unsupported task status")
        task.status = status
    if priority is not None:
        if priority not in TASK_PRIORITIES:
            raise ReuseError("invalid_priority", "Unsupported task priority")
        task.priority = priority
    await session.flush()
    return task


async def delete_task(
    session: AsyncSession, task: ProjectTask, workspace_id: UUID, user_id: UUID, role: str
) -> None:
    if task.workspace_id != workspace_id:
        raise ReuseError("task_not_found", "Task not found")
    if role != "owner" and task.user_id != user_id:
        raise ReuseError("forbidden", "Only the creator can delete this task")
    await session.delete(task)
    await session.flush()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_share(
    session: AsyncSession,
    *,
    conversation: Conversation,
    user_id: UUID,
    expires_in_days: int | None,
) -> tuple[ConversationShare, str]:
    days = DEFAULT_SHARE_DAYS if expires_in_days is None else expires_in_days
    days = max(1, min(int(days), MAX_SHARE_DAYS))
    token = secrets.token_urlsafe(32)
    share = ConversationShare(
        workspace_id=conversation.workspace_id,
        conversation_id=conversation.id,
        created_by=user_id,
        token_hash=_token_hash(token),
        expires_at=datetime.now(UTC) + timedelta(days=days),
    )
    session.add(share)
    await session.flush()
    return share, token


async def list_shares(session: AsyncSession, conversation_id: UUID) -> list[ConversationShare]:
    return list(
        (
            await session.execute(
                select(ConversationShare)
                .where(ConversationShare.conversation_id == conversation_id)
                .order_by(ConversationShare.created_at.desc())
            )
        ).scalars()
    )


async def revoke_share(
    session: AsyncSession,
    share: ConversationShare,
    *,
    conversation_id: UUID,
    user_id: UUID,
    role: str,
) -> ConversationShare:
    if share.conversation_id != conversation_id:
        raise ReuseError("share_not_found", "Share link not found")
    if role != "owner" and share.created_by != user_id:
        raise ReuseError("forbidden", "Only the creator can revoke this share")
    if share.revoked_at is None:
        share.revoked_at = datetime.now(UTC)
        await session.flush()
    return share


async def resolve_share(session: AsyncSession, token: str, user_id: UUID) -> Conversation:
    share = (
        await session.execute(
            select(ConversationShare).where(
                ConversationShare.token_hash == _token_hash(token),
                ConversationShare.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if share is None:
        raise ReuseError("share_not_found", "Share link not found")
    expires_at = share.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at is not None and expires_at <= datetime.now(UTC):
        raise ReuseError("share_expired", "Share link has expired")
    member = (
        await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == share.workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise ReuseError("share_not_found", "Share link not found")
    conversation = await session.get(Conversation, share.conversation_id)
    if conversation is None:
        raise ReuseError("share_not_found", "Share link not found")
    return conversation
