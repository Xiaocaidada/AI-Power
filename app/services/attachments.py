import base64
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChatAttachment
from app.services.parsing import IMAGE_MIMES, UnsupportedDocumentType, parser_for_mime

MAX_EXTRACTED_CHARS = 20000
MAX_PROMPT_ATTACHMENT_CHARS = 40000
MAX_IMAGE_PARTS = 4
MAX_IMAGE_PROMPT_BYTES = 4 * 1024 * 1024


class AttachmentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def is_image(attachment: ChatAttachment) -> bool:
    return attachment.mime in IMAGE_MIMES


def extract_text(path: Path, mime: str) -> str:
    try:
        parsed = parser_for_mime(mime).parse(path, mime)
    except UnsupportedDocumentType as exc:
        raise AttachmentError(
            "unsupported_attachment_type", "Attachment type is not supported"
        ) from exc
    text = "\n".join(page.text for page in parsed.pages if page.text)
    return text[:MAX_EXTRACTED_CHARS]


async def claim_attachments(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    attachment_ids: Sequence[UUID],
    conversation_id: UUID,
    message_id: UUID | None = None,
) -> list[ChatAttachment]:
    ids = list(dict.fromkeys(attachment_ids))
    if not ids:
        return []
    rows = list(
        (
            await session.execute(
                select(ChatAttachment).where(
                    ChatAttachment.id.in_(ids),
                    ChatAttachment.workspace_id == workspace_id,
                    ChatAttachment.user_id == user_id,
                    ChatAttachment.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    if len(rows) != len(ids):
        raise AttachmentError("attachment_not_found", "Attachment not found")
    by_id = {row.id: row for row in rows}
    ordered = [by_id[item] for item in ids]
    for row in ordered:
        if row.message_id is not None and row.message_id != message_id:
            raise AttachmentError(
                "attachment_already_linked", "Attachment is already linked to a message"
            )
        row.conversation_id = conversation_id
        if message_id is not None:
            row.message_id = message_id
    return ordered


async def attachments_for_message(
    session: AsyncSession, *, workspace_id: UUID, message_id: UUID
) -> list[ChatAttachment]:
    return list(
        (
            await session.execute(
                select(ChatAttachment)
                .where(
                    ChatAttachment.workspace_id == workspace_id,
                    ChatAttachment.message_id == message_id,
                    ChatAttachment.deleted_at.is_(None),
                )
                .order_by(ChatAttachment.created_at)
            )
        ).scalars()
    )


async def unlinked_conversation_attachments(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    conversation_id: UUID,
    user_id: UUID,
) -> list[ChatAttachment]:
    return list(
        (
            await session.execute(
                select(ChatAttachment)
                .where(
                    ChatAttachment.workspace_id == workspace_id,
                    ChatAttachment.conversation_id == conversation_id,
                    ChatAttachment.user_id == user_id,
                    ChatAttachment.message_id.is_(None),
                    ChatAttachment.deleted_at.is_(None),
                )
                .order_by(ChatAttachment.created_at)
            )
        ).scalars()
    )


async def attachments_by_message(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    conversation_id: UUID,
    message_ids: Sequence[UUID],
) -> dict[UUID, list[ChatAttachment]]:
    if not message_ids:
        return {}
    rows = list(
        (
            await session.execute(
                select(ChatAttachment)
                .where(
                    ChatAttachment.workspace_id == workspace_id,
                    ChatAttachment.conversation_id == conversation_id,
                    ChatAttachment.message_id.in_(message_ids),
                    ChatAttachment.deleted_at.is_(None),
                )
                .order_by(ChatAttachment.created_at)
            )
        ).scalars()
    )
    grouped: dict[UUID, list[ChatAttachment]] = {}
    for row in rows:
        if row.message_id is not None:
            grouped.setdefault(row.message_id, []).append(row)
    return grouped


def _truncate(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit]


def build_attachment_context(attachments: Sequence[ChatAttachment]) -> str:
    parts: list[str] = []
    used = 0
    for attachment in attachments:
        if is_image(attachment) or not attachment.extracted_text:
            continue
        block = f"[附件: {attachment.filename}]\n{attachment.extracted_text}"
        if used + len(block) > MAX_PROMPT_ATTACHMENT_CHARS:
            block = _truncate(block, MAX_PROMPT_ATTACHMENT_CHARS - used)
        if not block.strip():
            break
        parts.append(block)
        used += len(block)
        if used >= MAX_PROMPT_ATTACHMENT_CHARS:
            break
    if not parts:
        return ""
    return "<attachments>\n" + "\n\n".join(parts) + "\n</attachments>"


def build_image_parts(attachments: Sequence[ChatAttachment]) -> list[dict[str, object]]:
    parts: list[dict[str, object]] = []
    for attachment in attachments:
        if len(parts) >= MAX_IMAGE_PARTS or not is_image(attachment):
            continue
        if attachment.size_bytes > MAX_IMAGE_PROMPT_BYTES:
            continue
        try:
            raw = Path(attachment.storage_path).read_bytes()
        except OSError:
            continue
        encoded = base64.b64encode(raw).decode("ascii")
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{attachment.mime};base64,{encoded}"},
            }
        )
    return parts


def build_user_content(
    text: str, attachments: Sequence[ChatAttachment], *, include_images: bool
) -> str | list[dict[str, object]]:
    context = build_attachment_context(attachments)
    merged = f"{text}\n\n{context}" if context else text
    images = build_image_parts(attachments) if include_images else []
    if not images:
        return merged
    names = ", ".join(item.filename for item in attachments if is_image(item))
    return [
        {"type": "text", "text": f"{merged}\n\n[图片附件: {names}]"},
        *images,
    ]


async def delete_attachment_rows(
    session: AsyncSession, conversation_ids: Sequence[UUID]
) -> None:
    if not conversation_ids:
        return
    rows = list(
        (
            await session.execute(
                select(ChatAttachment).where(
                    ChatAttachment.conversation_id.in_(conversation_ids)
                )
            )
        ).scalars()
    )
    for row in rows:
        Path(row.storage_path).unlink(missing_ok=True)
    for row in rows:
        await session.delete(row)