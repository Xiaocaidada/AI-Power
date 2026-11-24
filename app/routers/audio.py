import time
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.schemas import AudioSpeechIn
from app.services.integrations import (
    IntegrationError,
    elapsed_ms,
    log_external_call,
    resolve_config,
    synthesize_speech,
    transcribe_audio,
)

router = APIRouter(prefix="/audio", tags=["audio"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".webm", ".ogg", ".flac", ".mp4"}
AUDIO_FORMATS = {"mp3", "opus", "aac", "flac", "wav", "pcm"}


def _error(exc: IntegrationError) -> HTTPException:
    if exc.code == "not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    if exc.code in {
        "integration_timeout",
        "integration_unreachable",
        "integration_upstream_error",
        "integration_rate_limited",
        "integration_auth_failed",
        "integration_bad_response",
        "integration_response_too_large",
        "audio_bad_response",
    }:
        return HTTPException(
            status.HTTP_502_BAD_GATEWAY, {"code": exc.code, "message": exc.message}
        )
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"code": exc.code, "message": exc.message},
    )


@router.post("/transcriptions")
async def transcribe(
    context: JwtContext,
    session: SessionDep,
    file: Annotated[UploadFile, File()],
    integration_id: Annotated[str | None, Form()] = None,
    language: Annotated[str | None, Form()] = None,
    prompt: Annotated[str | None, Form()] = None,
) -> dict[str, str]:
    filename = Path(file.filename or "audio").name
    suffix = Path(filename).suffix.lower()
    if suffix not in AUDIO_EXTENSIONS:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            {"code": "unsupported_audio_type", "message": "Unsupported audio format"},
        )
    config_id: UUID | None = None
    if integration_id:
        try:
            config_id = UUID(integration_id)
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "not_found", "message": "Integration not found"},
            ) from None
    started = time.perf_counter()
    try:
        config = await resolve_config(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            kind="stt",
            config_id=config_id,
        )
    except IntegrationError as exc:
        raise _error(exc) from None
    limit = get_settings().integration_max_audio_bytes
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            {"code": "audio_too_large", "message": "Audio file exceeds the size limit"},
        )
    try:
        text = await transcribe_audio(
            config,
            filename=filename,
            content=content,
            content_type=file.content_type or "application/octet-stream",
            language=language,
            prompt=prompt,
        )
    except IntegrationError as exc:
        log_external_call(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            integration=config,
            operation="stt",
            status="failed",
            error_code=exc.code,
            duration_ms=elapsed_ms(started),
        )
        await session.commit()
        raise _error(exc) from None
    log_external_call(
        session,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        integration=config,
        operation="stt",
        duration_ms=elapsed_ms(started),
    )
    await session.commit()
    return {"text": text}


@router.post("/speech")
async def speech(payload: AudioSpeechIn, context: JwtContext, session: SessionDep) -> Response:
    if payload.response_format not in AUDIO_FORMATS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "invalid_format", "message": "Unsupported audio format"},
        )
    started = time.perf_counter()
    try:
        config = await resolve_config(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            kind="tts",
            config_id=payload.integration_id,
        )
    except IntegrationError as exc:
        raise _error(exc) from None
    try:
        audio, mime = await synthesize_speech(
            config,
            text=payload.text,
            voice=payload.voice,
            response_format=payload.response_format,
            speed=payload.speed,
        )
    except IntegrationError as exc:
        log_external_call(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            integration=config,
            operation="tts",
            status="failed",
            error_code=exc.code,
            duration_ms=elapsed_ms(started),
        )
        await session.commit()
        raise _error(exc) from None
    log_external_call(
        session,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        integration=config,
        operation="tts",
        duration_ms=elapsed_ms(started),
    )
    await session.commit()
    return Response(
        content=audio,
        media_type=mime,
        headers={"Content-Disposition": f'inline; filename="speech.{payload.response_format}"'},
    )