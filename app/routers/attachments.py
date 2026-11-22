import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.config import get_settings
from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import ChatAttachment, Conversation
from app.schemas import AttachmentOut, ErrorOut
from app.services.attachments import extract_text
from app.services.parsing import UnsupportedDocumentType, detect_mime, parser_for_mime
from app.services.quotas import enforce_quota
from app.services.storage import EmptyUpload, UploadTooLarge, save_upload

router = APIRouter(prefix="/attachments", tags=["attachments"])
logger = logging.getLogger(__name__)
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]

IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}


@router.post(
    "",
    response_model=AttachmentOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        404: {"model": ErrorOut, "description": "Conversation not found"},
        413: {"model": ErrorOut, "description": "Upload exceeds MAX_UPLOAD_BYTES"},
        415: {"model": ErrorOut, "description": "Unsupported attachment type"},
        429: {"model": ErrorOut, "description": "Quota exceeded"},
    },
)
async def upload_attachment(
    file: Annotated[UploadFile, File()],
    context: JwtContext,
    session: SessionDep,
    redis: RedisDep,
    conversation_id: Annotated[UUID | None, Form()] = None,
) -> ChatAttachment:
    await enforce_quota(redis, context)
    settings = get_settings()
    try:
        mime = detect_mime(file.filename, file.content_type)
    except UnsupportedDocumentType as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from None
    if mime not in IMAGE_MIMES:
        try:
            parser_for_mime(mime)
        except UnsupportedDocumentType as exc:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from None

    if conversation_id is not None:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.workspace_id != context.workspace.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")

    try:
        saved = await save_upload(file, settings.upload_dir, settings.max_upload_bytes)
    except UploadTooLarge:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File too large") from None
    except EmptyUpload:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file") from None

    kind = "image" if saved.mime in IMAGE_MIMES else "document"
    extracted: str | None = None
    if kind == "document":
        try:
            extracted = extract_text(saved.path, saved.mime)
        except Exception:
            logger.warning("attachment parse failed for %s", saved.mime)
            saved.path.unlink(missing_ok=True)
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                {"code": "attachment_parse_failed", "message": "Cannot parse attachment"},
            ) from None

    attachment = ChatAttachment(
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        conversation_id=conversation_id,
        filename=Path(file.filename or saved.storage_name).name,
        mime=saved.mime,
        size_bytes=saved.size_bytes,
        storage_path=str(saved.path),
        kind=kind,
        status="ready",
        extracted_text=extracted,
    )
    session.add(attachment)
    await session.commit()
    await session.refresh(attachment)
    return attachment


@router.get("", response_model=list[AttachmentOut])
async def list_attachments(
    context: JwtContext,
    session: SessionDep,
    conversation_id: UUID | None = None,
    unlinked: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[ChatAttachment]:
    conditions = [
        ChatAttachment.workspace_id == context.workspace.id,
        ChatAttachment.deleted_at.is_(None),
    ]
    if conversation_id is not None:
        conditions.append(ChatAttachment.conversation_id == conversation_id)
    elif unlinked:
        conditions.append(ChatAttachment.user_id == context.user.id)
        conditions.append(ChatAttachment.message_id.is_(None))
    else:
        conditions.append(ChatAttachment.user_id == context.user.id)
    result = await session.execute(
        select(ChatAttachment)
        .where(*conditions)
        .order_by(ChatAttachment.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars())


def _contained_path(storage_path: str) -> Path:
    base = Path(get_settings().upload_dir).resolve()
    path = Path(storage_path).resolve()
    if not path.is_relative_to(base):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    return path


@router.get("/{attachment_id}/download")
async def download_attachment(
    attachment_id: UUID, context: JwtContext, session: SessionDep
) -> FileResponse:
    attachment = await session.get(ChatAttachment, attachment_id)
    if (
        attachment is None
        or attachment.workspace_id != context.workspace.id
        or attachment.deleted_at is not None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    path = _contained_path(attachment.storage_path)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    return FileResponse(path, media_type=attachment.mime, filename=attachment.filename)


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_id: UUID, context: JwtContext, session: SessionDep
) -> None:
    attachment = await session.get(ChatAttachment, attachment_id)
    if (
        attachment is None
        or attachment.workspace_id != context.workspace.id
        or attachment.user_id != context.user.id
        or attachment.deleted_at is not None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    attachment.deleted_at = datetime.now(UTC)
    await session.commit()