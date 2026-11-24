import time
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import MediaAsset
from app.schemas import ImageGenerateIn, MediaAssetOut
from app.services.integrations import (
    IntegrationError,
    delete_media,
    elapsed_ms,
    generate_images,
    get_media,
    list_media,
    log_external_call,
    resolve_config,
    store_image_assets,
)

router = APIRouter(tags=["media"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


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


@router.post("/images/generations", response_model=list[MediaAssetOut], status_code=201)
async def create_images(
    payload: ImageGenerateIn, context: JwtContext, session: SessionDep
) -> list[MediaAssetOut]:
    started = time.perf_counter()
    try:
        config = await resolve_config(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            kind="image_generation",
            config_id=payload.integration_id,
        )
    except IntegrationError as exc:
        raise _error(exc) from None
    try:
        images = await generate_images(
            config,
            prompt=payload.prompt,
            size=payload.size,
            n=payload.n,
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
    assets = store_image_assets(
        session,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        config=config,
        prompt=payload.prompt,
        images=images,
    )
    log_external_call(
        session,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        integration=config,
        operation="image_generation",
        duration_ms=elapsed_ms(started),
        units=len(assets),
    )
    await session.commit()
    for asset in assets:
        await session.refresh(asset)
    return [_out(asset) for asset in assets]


@router.get("/media", response_model=list[MediaAssetOut])
async def list_media_assets(
    context: JwtContext, session: SessionDep, limit: int = 50
) -> list[MediaAssetOut]:
    return [_out(asset) for asset in await list_media(session, context.workspace.id, limit=limit)]


def _contained_path(storage_path: str) -> Path:
    base = Path(get_settings().upload_dir).resolve()
    path = Path(storage_path).resolve()
    if not path.is_relative_to(base):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media asset not found")
    return path


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