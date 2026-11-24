import base64
import time
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.config import get_settings
from app.db import get_session
from app.deps import AuthContext, get_jwt_context, get_scoped_registry
from app.models import MediaAsset
from app.providers.base import ChatMessage
from app.providers.registry import ProviderRegistry
from app.schemas import ImageAnalyzeOut, ImageGenerateIn, MediaAssetOut
from app.services.chat_tasks import ChatTaskError, resolve_task_model
from app.services.integrations import (
    IntegrationError,
    delete_media,
    edit_images,
    elapsed_ms,
    generate_images,
    get_media,
    list_media,
    log_external_call,
    resolve_config,
    store_image_assets,
    variation_images,
)
from app.services.model_stream import ModelCompletion
from app.services.provider_configs import ProviderConfigError, ensure_model_capability
from app.services.usage_ledger import SOURCE_IMAGE_ANALYSIS

router = APIRouter(tags=["media"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_scoped_registry)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]

IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _error(exc: IntegrationError) -> HTTPException:
    if exc.code in {"not_found", "media_not_found"}:
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    if exc.code == "forbidden":
        return HTTPException(status.HTTP_403_FORBIDDEN, {"code": exc.code, "message": exc.message})
    if exc.code in {
        "integration_timeout",
        "integration_unreachable",
        "integration_upstream_error",
        "integration_rate_limited",
        "integration_auth_failed",
        "integration_bad_response",
        "integration_response_too_large",
        "image_bad_response",
        "image_too_large",
    }:
        return HTTPException(
            status.HTTP_502_BAD_GATEWAY, {"code": exc.code, "message": exc.message}
        )
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"code": exc.code, "message": exc.message},
    )


def _out(asset: MediaAsset) -> MediaAssetOut:
    return MediaAssetOut(
        id=asset.id,
        integration_id=asset.integration_id,
        kind=asset.kind,
        filename=asset.filename,
        mime=asset.mime,
        size_bytes=asset.size_bytes,
        prompt=asset.prompt,
        url=f"/media/{asset.id}",
        created_at=asset.created_at,
    )


def _contained_path(storage_path: str) -> Path:
    base = Path(get_settings().upload_dir).resolve()
    path = Path(storage_path).resolve()
    if not path.is_relative_to(base):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media asset not found")
    return path


async def _read_image(file: UploadFile, *, limit: int) -> tuple[str, bytes, str]:
    filename = Path(file.filename or "image").name
    suffix = Path(filename).suffix.lower()
    if suffix not in IMAGE_EXTS:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            {"code": "unsupported_image_type", "message": "Unsupported image format"},
        )
    content_type = (file.content_type or "").lower()
    if content_type not in IMAGE_MIMES:
        content_type = "image/png" if suffix == ".png" else "image/jpeg"
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            {"code": "image_too_large", "message": "Image exceeds the size limit"},
        )
    if not content:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "image_empty", "message": "Image file is empty"},
        )
    return filename, content, content_type


def _parse_uuid(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "not_found", "message": "Integration not found"},
        ) from None


async def _save_result(
    *,
    session: AsyncSession,
    context: AuthContext,
    config,
    images: list[tuple[bytes, str, str]],
    prompt: str,
    operation: str,
    started: float,
    metadata: dict | None = None,
) -> list[MediaAssetOut]:
    assets = store_image_assets(
        session,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        config=config,
        prompt=prompt,
        images=images,
        metadata={"operation": operation, **(metadata or {})},
    )
    log_external_call(
        session,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        integration=config,
        operation=operation,
        duration_ms=elapsed_ms(started),
        units=len(assets),
    )
    await session.commit()
    for asset in assets:
        await session.refresh(asset)
    return [_out(asset) for asset in assets]


async def _image_config(session: AsyncSession, context: AuthContext, integration_id: str | None):
    try:
        return await resolve_config(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            kind="image_generation",
            config_id=_parse_uuid(integration_id),
        )
    except IntegrationError as exc:
        raise _error(exc) from None


@router.post("/images/generations", response_model=list[MediaAssetOut], status_code=201)
async def create_images(
    payload: ImageGenerateIn, context: JwtContext, session: SessionDep
) -> list[MediaAssetOut]:
    started = time.perf_counter()
    config = await _image_config(
        session, context, str(payload.integration_id) if payload.integration_id else None
    )
    try:
        images = await generate_images(
            config,
            prompt=payload.prompt,
            size=payload.size,
            n=payload.n,
            quality=payload.quality,
            style=payload.style,
        )
    except IntegrationError as exc:
        log_external_call(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            integration=config,
            operation="image_generation",
            status="failed",
            error_code=exc.code,
            duration_ms=elapsed_ms(started),
            units=payload.n,
        )
        await session.commit()
        raise _error(exc) from None
    return await _save_result(
        session=session,
        context=context,
        config=config,
        images=images,
        prompt=payload.prompt,
        operation="image_generation",
        started=started,
    )


@router.post("/images/edits", response_model=list[MediaAssetOut], status_code=201)
async def create_image_edits(
    context: JwtContext,
    session: SessionDep,
    image: Annotated[UploadFile, File()],
    prompt: Annotated[str, Form()],
    mask: Annotated[UploadFile | None, File()] = None,
    size: Annotated[str | None, Form()] = None,
    n: Annotated[int, Form()] = 1,
    quality: Annotated[str | None, Form()] = None,
    style: Annotated[str | None, Form()] = None,
    integration_id: Annotated[str | None, Form()] = None,
) -> list[MediaAssetOut]:
    if prompt.strip() == "":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "prompt_required", "message": "Prompt is required"},
        )
    if n < 1 or n > 4:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "invalid_n", "message": "n must be between 1 and 4"},
        )
    settings = get_settings()
    image_part = await _read_image(image, limit=settings.integration_max_image_bytes)
    mask_part = (
        await _read_image(mask, limit=settings.integration_max_image_bytes)
        if mask is not None
        else None
    )
    started = time.perf_counter()
    config = await _image_config(session, context, integration_id)
    try:
        images = await edit_images(
            config,
            prompt=prompt.strip(),
            image=image_part,
            mask=mask_part,
            size=size,
            n=n,
            quality=quality,
            style=style,
        )
    except IntegrationError as exc:
        log_external_call(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            integration=config,
            operation="image_edit",
            status="failed",
            error_code=exc.code,
            duration_ms=elapsed_ms(started),
            units=n,
        )
        await session.commit()
        raise _error(exc) from None
    return await _save_result(
        session=session,
        context=context,
        config=config,
        images=images,
        prompt=prompt.strip(),
        operation="image_edit",
        started=started,
        metadata={"source_filename": image_part[0]},
    )


@router.post("/images/variations", response_model=list[MediaAssetOut], status_code=201)
async def create_image_variations(
    context: JwtContext,
    session: SessionDep,
    image: Annotated[UploadFile, File()],
    size: Annotated[str | None, Form()] = None,
    n: Annotated[int, Form()] = 1,
    integration_id: Annotated[str | None, Form()] = None,
) -> list[MediaAssetOut]:
    if n < 1 or n > 4:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "invalid_n", "message": "n must be between 1 and 4"},
        )
    image_part = await _read_image(
        image, limit=get_settings().integration_max_image_bytes
    )
    started = time.perf_counter()
    config = await _image_config(session, context, integration_id)
    try:
        images = await variation_images(config, image=image_part, size=size, n=n)
    except IntegrationError as exc:
        log_external_call(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            integration=config,
            operation="image_variation",
            status="failed",
            error_code=exc.code,
            duration_ms=elapsed_ms(started),
            units=n,
        )
        await session.commit()
        raise _error(exc) from None
    return await _save_result(
        session=session,
        context=context,
        config=config,
        images=images,
        prompt="",
        operation="image_variation",
        started=started,
        metadata={"source_filename": image_part[0]},
    )


@router.post("/images/analyze", response_model=ImageAnalyzeOut)
async def analyze_image(
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
    redis: RedisDep,
    file: Annotated[UploadFile | None, File()] = None,
    media_id: Annotated[str | None, Form()] = None,
    question: Annotated[str, Form()] = "Describe this image in detail.",
    provider_id: Annotated[str, Form()] = "auto",
    model: Annotated[str, Form()] = "auto",
) -> ImageAnalyzeOut:
    settings = get_settings()
    asset_id: UUID | None = None
    if file is not None:
        filename, content, mime = await _read_image(
            file, limit=settings.integration_max_image_bytes
        )
    elif media_id:
        try:
            asset_id = UUID(media_id)
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "media_not_found", "message": "Media asset not found"},
            ) from None
        try:
            asset = await get_media(session, asset_id, context.workspace.id)
        except IntegrationError as exc:
            raise _error(exc) from None
        path = _contained_path(asset.storage_path)
        if not path.exists():
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                {"code": "media_not_found", "message": "Media asset file is missing"},
            )
        content = path.read_bytes()
        if len(content) > settings.integration_max_image_bytes:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                {"code": "image_too_large", "message": "Image exceeds the size limit"},
            )
        _filename, mime = asset.filename, asset.mime
    else:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "image_required", "message": "Upload an image or select a media asset"},
        )

    try:
        resolved_provider, resolved_model = await resolve_task_model(
            session,
            registry,
            redis,
            provider_id=provider_id,
            model=model,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
        )
        await ensure_model_capability(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            provider_id=resolved_provider,
            model_id=resolved_model,
            capability="vision",
        )
        provider = registry.get(resolved_provider)
    except ChatTaskError as exc:
        if exc.code == "provider_not_found":
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                {"code": exc.code, "message": exc.message},
            ) from None
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": exc.code, "message": exc.message},
        ) from None
    except ProviderConfigError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": exc.code, "message": exc.message},
        ) from None
    except Exception as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"code": "provider_not_found", "message": str(exc)},
        ) from None

    encoded = base64.b64encode(content).decode("ascii")
    messages = [
        ChatMessage(
            role="user",
            content=[
                {"type": "text", "text": question.strip()[:4000]},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{encoded}"},
                },
            ],
        )
    ]
    completion = ModelCompletion(
        provider=provider,
        model=resolved_model,
        messages=messages,
        opts={"temperature": 0.2, "max_tokens": 1500},
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        source=SOURCE_IMAGE_ANALYSIS,
    )
    metrics = await completion.run()
    if metrics.status != "completed":
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            {
                "code": metrics.error_code or "image_analysis_failed",
                "message": "Image analysis failed",
            },
        )
    return ImageAnalyzeOut(
        answer=metrics.content.strip(),
        media_id=asset_id,
        provider_id=resolved_provider,
        model=resolved_model,
        prompt_tokens=metrics.prompt_tokens,
        completion_tokens=metrics.completion_tokens,
    )


@router.get("/media", response_model=list[MediaAssetOut])
async def list_media_assets(
    context: JwtContext, session: SessionDep, limit: int = 50
) -> list[MediaAssetOut]:
    return [_out(asset) for asset in await list_media(session, context.workspace.id, limit=limit)]


@router.get("/media/{media_id}")
async def read_media(
    media_id: UUID, context: JwtContext, session: SessionDep
) -> FileResponse:
    try:
        asset = await get_media(session, media_id, context.workspace.id)
    except IntegrationError as exc:
        raise _error(exc) from None
    path = _contained_path(asset.storage_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media asset file is missing")
    return FileResponse(path, media_type=asset.mime, filename=asset.filename)


@router.delete("/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_media(
    media_id: UUID, context: JwtContext, session: SessionDep
) -> None:
    try:
        asset = await get_media(session, media_id, context.workspace.id)
        await delete_media(session, asset, context.user.id, context.role)
    except IntegrationError as exc:
        raise _error(exc) from None
    await session.commit()