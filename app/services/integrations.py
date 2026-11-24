"""BYOK integrations for image generation, speech and read-only GitHub.

Credentials are supplied by the user and encrypted with the same Fernet helper as
LLM provider keys. The platform only proxies requests; external vendors bill the
credential owner.
"""

import base64
import logging
import re
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ExternalCall, IntegrationConfig, MediaAsset
from app.services.provider_secrets import api_key_hint, decrypt_api_key, encrypt_api_key

logger = logging.getLogger(__name__)

INTEGRATION_KINDS = ("image_generation", "stt", "tts", "github")
PROVIDERS_BY_KIND = {
    "image_generation": ("openai_compatible",),
    "stt": ("openai_compatible",),
    "tts": ("openai_compatible",),
    "github": ("github",),
}
DEFAULT_BASE_URLS = {
    "image_generation": "https://api.openai.com/v1",
    "stt": "https://api.openai.com/v1",
    "tts": "https://api.openai.com/v1",
    "github": "https://api.github.com",
}
DEFAULT_MODELS = {
    "image_generation": "gpt-image-1",
    "stt": "whisper-1",
    "tts": "tts-1",
    "github": "",
}
DEFAULT_AUTH = {"image_generation": "api_key", "stt": "api_key", "tts": "api_key", "github": "pat"}
IMAGE_SIZES = ("256x256", "512x512", "1024x1024", "1024x1536", "1536x1024", "auto")
AUDIO_RESPONSE_FORMATS = ("mp3", "opus", "aac", "flac", "wav", "pcm")
MEDIA_MIME_BY_FORMAT = {
    "mp3": "audio/mpeg",
    "opus": "audio/ogg",
    "aac": "audio/aac",
    "flac": "audio/flac",
    "wav": "audio/wav",
    "pcm": "audio/L16",
}


class IntegrationError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _validate_base_url(value: str | None, kind: str) -> str:
    base = (value or DEFAULT_BASE_URLS[kind]).strip().rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise IntegrationError("invalid_endpoint", "Base URL must be an http(s) URL")
    if parsed.username or parsed.password:
        raise IntegrationError("invalid_endpoint", "Base URL must not contain credentials")
    return base


def _normalize_kind(value: str) -> str:
    kind = (value or "").strip()
    if kind not in INTEGRATION_KINDS:
        raise IntegrationError("invalid_kind", "Unsupported integration kind")
    return kind


def _normalize_provider(kind: str, value: str | None) -> str:
    provider = (value or PROVIDERS_BY_KIND[kind][0]).strip()
    if provider not in PROVIDERS_BY_KIND[kind]:
        raise IntegrationError("invalid_provider", "Unsupported provider for this integration")
    return provider


def _normalize_options(kind: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    source = raw or {}
    options: dict[str, Any] = {}
    if kind == "image_generation":
        size = str(source.get("size") or "1024x1024")
        options["size"] = size if size in IMAGE_SIZES else "1024x1024"
        quality = str(source.get("quality") or "").strip()
        if quality in {"low", "medium", "high", "standard", "hd"}:
            options["quality"] = quality
        style = str(source.get("style") or "").strip()
        if style in {"natural", "vivid"}:
            options["style"] = style
    elif kind == "stt":
        language = str(source.get("language") or "").strip()
        if language:
            options["language"] = language[:20]
    elif kind == "tts":
        voice = str(source.get("voice") or "alloy").strip()
        options["voice"] = voice[:80] or "alloy"
        fmt = str(source.get("response_format") or "mp3").strip()
        options["response_format"] = fmt if fmt in AUDIO_RESPONSE_FORMATS else "mp3"
        try:
            options["speed"] = min(max(float(source.get("speed") or 1.0), 0.25), 4.0)
        except (TypeError, ValueError):
            options["speed"] = 1.0
    return options


def _credential(config: IntegrationConfig) -> str:
    encrypted = config.credentials_encrypted or ""
    if not encrypted:
        raise IntegrationError("integration_not_configured", "Integration credential is missing")
    try:
        return decrypt_api_key(encrypted)
    except ValueError:
        raise IntegrationError(
            "integration_auth_failed", "Integration credential cannot be decrypted"
        ) from None


def _headers(config: IntegrationConfig) -> dict[str, str]:
    credential = _credential(config)
    if config.provider == "github":
        return {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": f"Bearer {credential}",
        }
    return {"Authorization": f"Bearer {credential}", "Content-Type": "application/json"}


def _status_error(status_code: int) -> IntegrationError:
    if status_code in {401, 403}:
        return IntegrationError("integration_auth_failed", "Provider rejected the credential")
    if status_code == 429:
        return IntegrationError("integration_rate_limited", "Provider rate limit reached")
    return IntegrationError(
        "integration_upstream_error", f"Provider returned HTTP {status_code}"
    )


async def _http_request(
    config: IntegrationConfig,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
    timeout: float | None = None,
    max_bytes: int | None = None,
) -> httpx.Response:
    url = f"{config.base_url.rstrip('/')}{path}"
    current = get_settings()
    limit = max_bytes or current.integration_max_image_bytes
    try:
        async with httpx.AsyncClient(
            timeout=timeout or current.integration_audio_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            request = client.build_request(
                method,
                url,
                headers=_headers(config),
                json=json_body,
                files=files,
                data=data,
            )
            response = await client.send(request, stream=True)
            try:
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > limit:
                        raise IntegrationError(
                            "integration_response_too_large",
                            "Provider response exceeded the size limit",
                        )
                    chunks.append(chunk)
                response._content = b"".join(chunks)  # noqa: SLF001
                return response
            finally:
                await response.aclose()
    except IntegrationError:
        raise
    except httpx.TimeoutException:
        raise IntegrationError("integration_timeout", "Provider request timed out") from None
    except httpx.RequestError:
        raise IntegrationError("integration_unreachable", "Provider is unreachable") from None


def _require_json(response: httpx.Response) -> dict[str, Any]:
    if response.status_code >= 400:
        raise _status_error(response.status_code)
    try:
        payload = response.json()
    except ValueError:
        raise IntegrationError(
            "integration_bad_response", "Provider returned invalid JSON"
        ) from None
    if not isinstance(payload, dict):
        raise IntegrationError("integration_bad_response", "Provider returned invalid data")
    return payload


def _query(config_id: UUID, workspace_id: UUID, user_id: UUID, *, owner_only: bool):
    conditions = [
        IntegrationConfig.id == config_id,
        IntegrationConfig.workspace_id == workspace_id,
        IntegrationConfig.deleted_at.is_(None),
    ]
    if owner_only:
        conditions.append(IntegrationConfig.owner_user_id == user_id)
    else:
        conditions.append(
            or_(
                IntegrationConfig.owner_user_id == user_id,
                IntegrationConfig.shared.is_(True),
            )
        )
    return select(IntegrationConfig).where(*conditions)


async def get_config(
    session: AsyncSession,
    config_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    *,
    owner_only: bool = False,
) -> IntegrationConfig:
    config = (
        await session.execute(_query(config_id, workspace_id, user_id, owner_only=owner_only))
    ).scalar_one_or_none()
    if config is None:
        raise IntegrationError("not_found", "Integration not found")
    return config


async def list_configs(
    session: AsyncSession, workspace_id: UUID, user_id: UUID, kind: str | None = None
) -> list[IntegrationConfig]:
    conditions = [
        IntegrationConfig.workspace_id == workspace_id,
        IntegrationConfig.deleted_at.is_(None),
        or_(
            IntegrationConfig.owner_user_id == user_id,
            IntegrationConfig.shared.is_(True),
        ),
    ]
    if kind is not None:
        conditions.append(IntegrationConfig.kind == _normalize_kind(kind))
    return list(
        (
            await session.execute(
                select(IntegrationConfig)
                .where(*conditions)
                .order_by(
                    IntegrationConfig.kind,
                    IntegrationConfig.is_default.desc(),
                    IntegrationConfig.created_at,
                )
            )
        ).scalars()
    )


async def create_config(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    kind: str,
    provider: str | None,
    name: str,
    base_url: str | None,
    credential: str,
    model: str,
    options: dict[str, Any] | None,
    shared: bool,
    enabled: bool,
) -> IntegrationConfig:
    normalized_kind = _normalize_kind(kind)
    normalized_provider = _normalize_provider(normalized_kind, provider)
    secret = (credential or "").strip()
    if secret == "" and normalized_provider == "github":
        raise IntegrationError("credential_required", "A GitHub token is required")
    existing = await list_configs(session, workspace_id, user_id, normalized_kind)
    owns_any = any(item.owner_user_id == user_id for item in existing)
    config = IntegrationConfig(
        workspace_id=workspace_id,
        owner_user_id=user_id,
        kind=normalized_kind,
        provider=normalized_provider,
        name=(name or "").strip()[:100] or normalized_kind.replace("_", " ").title(),
        base_url=_validate_base_url(base_url, normalized_kind),
        auth_type=DEFAULT_AUTH[normalized_kind],
        credentials_encrypted=encrypt_api_key(secret) if secret else "",
        credential_hint=api_key_hint(secret) if secret else "",
        model=(model or DEFAULT_MODELS[normalized_kind]).strip()[:200],
        options=_normalize_options(normalized_kind, options),
        shared=shared,
        enabled=enabled,
        is_default=not owns_any,
    )
    session.add(config)
    await session.flush()
    return config


async def update_config(
    session: AsyncSession,
    config: IntegrationConfig,
    *,
    name: str | None = None,
    base_url: str | None = None,
    credential: str | None = None,
    model: str | None = None,
    options: dict[str, Any] | None = None,
    shared: bool | None = None,
    enabled: bool | None = None,
    is_default: bool | None = None,
) -> IntegrationConfig:
    if name is not None:
        config.name = name.strip()[:100] or config.kind.replace("_", " ").title()
    if base_url is not None:
        config.base_url = _validate_base_url(base_url, config.kind)
    if credential is not None and credential.strip() != "":
        config.credentials_encrypted = encrypt_api_key(credential.strip())
        config.credential_hint = api_key_hint(credential.strip())
    if model is not None:
        config.model = model.strip()[:200] or DEFAULT_MODELS[config.kind]
    if options is not None:
        config.options = _normalize_options(config.kind, options)
    if shared is not None:
        config.shared = shared
    if enabled is not None:
        config.enabled = enabled
        if not enabled:
            config.is_default = False
    if is_default is True:
        await _clear_defaults(session, config)
        config.is_default = True
    await session.flush()
    return config


async def _clear_defaults(session: AsyncSession, config: IntegrationConfig) -> None:
    await session.execute(
        update(IntegrationConfig)
        .where(
            IntegrationConfig.workspace_id == config.workspace_id,
            IntegrationConfig.owner_user_id == config.owner_user_id,
            IntegrationConfig.kind == config.kind,
            IntegrationConfig.id != config.id,
        )
        .values(is_default=False)
    )


async def set_default(session: AsyncSession, config: IntegrationConfig) -> IntegrationConfig:
    if not config.enabled:
        raise IntegrationError("integration_disabled", "Enable the integration first")
    await _clear_defaults(session, config)
    config.is_default = True
    await session.flush()
    return config


async def delete_config(session: AsyncSession, config: IntegrationConfig) -> None:
    config.deleted_at = datetime.now(UTC)
    config.enabled = False
    config.is_default = False
    await session.flush()


async def resolve_config(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    kind: str,
    config_id: str | UUID | None = None,
) -> IntegrationConfig:
    normalized_kind = _normalize_kind(kind)
    if config_id:
        try:
            target = UUID(str(config_id))
        except ValueError:
            raise IntegrationError("not_found", "Integration not found") from None
        config = await get_config(session, target, workspace_id, user_id)
        if config.kind != normalized_kind:
            raise IntegrationError("not_found", "Integration not found")
        if not config.enabled:
            raise IntegrationError("integration_disabled", "The integration is disabled")
        return config
    config = (
        await session.execute(
            select(IntegrationConfig)
            .where(
                IntegrationConfig.workspace_id == workspace_id,
                IntegrationConfig.kind == normalized_kind,
                IntegrationConfig.owner_user_id == user_id,
                IntegrationConfig.deleted_at.is_(None),
                IntegrationConfig.enabled.is_(True),
            )
            .order_by(IntegrationConfig.is_default.desc(), IntegrationConfig.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if config is not None:
        return config
    shared = (
        await session.execute(
            select(IntegrationConfig)
            .where(
                IntegrationConfig.workspace_id == workspace_id,
                IntegrationConfig.kind == normalized_kind,
                IntegrationConfig.shared.is_(True),
                IntegrationConfig.deleted_at.is_(None),
                IntegrationConfig.enabled.is_(True),
            )
            .order_by(IntegrationConfig.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if shared is not None:
        return shared
    raise IntegrationError(
        "integration_not_configured",
        f"Configure a {normalized_kind.replace('_', ' ')} integration first",
    )


async def test_config(config: IntegrationConfig) -> dict[str, Any]:
    config.last_tested_at = datetime.now(UTC)
    path = "/user" if config.provider == "github" else "/models"
    try:
        response = await _http_request(
            config,
            "GET",
            path,
            timeout=get_settings().integration_github_timeout_seconds,
            max_bytes=1_000_000,
        )
        if response.status_code >= 400:
            raise _status_error(response.status_code)
    except IntegrationError as exc:
        config.status = "error"
        config.last_error = exc.code
        return {"status": "error", "error_code": exc.code, "message": exc.message}
    config.status = "ok"
    config.last_error = None
    return {"status": "ok", "error_code": None, "message": ""}


def log_external_call(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    integration: IntegrationConfig | None,
    operation: str,
    status: str = "completed",
    error_code: str | None = None,
    duration_ms: int = 0,
    units: int = 1,
) -> ExternalCall:
    row = ExternalCall(
        workspace_id=workspace_id,
        user_id=user_id,
        integration_id=integration.id if integration is not None else None,
        kind=integration.kind if integration is not None else "",
        provider=integration.provider if integration is not None else "",
        operation=operation[:60],
        status=status,
        error_code=error_code,
        duration_ms=max(0, duration_ms),
        units=max(1, units),
    )
    session.add(row)
    return row


def _image_mime(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return "image/png", "png"


def _image_request_options(
    config: IntegrationConfig,
    *,
    prompt: str,
    size: str | None,
    n: int,
    quality: str | None,
    style: str | None,
) -> tuple[dict[str, Any], int]:
    settings = get_settings()
    chosen_size = size or str((config.options or {}).get("size") or "1024x1024")
    if chosen_size not in IMAGE_SIZES:
        raise IntegrationError("invalid_size", "Unsupported image size")
    count = max(1, min(n, settings.integration_max_images_per_request))
    options = config.options or {}
    body: dict[str, Any] = {
        "model": config.model or DEFAULT_MODELS["image_generation"],
        "prompt": prompt[: settings.integration_max_prompt_chars],
        "n": count,
        "size": chosen_size,
    }
    for key, value in (("quality", quality), ("style", style)):
        chosen = value or options.get(key)
        if chosen:
            body[key] = chosen
    return body, count


async def _decode_image_payload(
    config: IntegrationConfig, payload: dict[str, Any], count: int
) -> list[tuple[bytes, str, str]]:
    settings = get_settings()
    rows = payload.get("data")
    if not isinstance(rows, list) or not rows:
        raise IntegrationError("image_bad_response", "Provider returned no images")
    images: list[tuple[bytes, str, str]] = []
    for row in rows[:count]:
        if not isinstance(row, dict):
            continue
        raw: bytes | None = None
        if isinstance(row.get("b64_json"), str):
            try:
                raw = base64.b64decode(row["b64_json"], validate=False)
            except (ValueError, TypeError):
                raw = None
        elif isinstance(row.get("url"), str):
            url = row["url"]
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            try:
                async with httpx.AsyncClient(
                    timeout=settings.integration_image_timeout_seconds,
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    async with client.stream("GET", url) as fetched:
                        if fetched.status_code >= 400:
                            continue
                        chunks: list[bytes] = []
                        total = 0
                        async for chunk in fetched.aiter_bytes():
                            total += len(chunk)
                            if total > settings.integration_max_image_bytes:
                                raise IntegrationError(
                                    "image_too_large",
                                    "Generated image exceeded the size limit",
                                )
                            chunks.append(chunk)
                        raw = b"".join(chunks)
            except IntegrationError:
                raise
            except httpx.HTTPError:
                continue
        if raw is None:
            continue
        if len(raw) > settings.integration_max_image_bytes:
            raise IntegrationError(
                "image_too_large", "Generated image exceeded the size limit"
            )
        mime, extension = _image_mime(raw)
        images.append((raw, mime, extension))
    if not images:
        raise IntegrationError("image_bad_response", "Provider returned no usable images")
    return images


async def generate_images(
    config: IntegrationConfig,
    *,
    prompt: str,
    size: str | None,
    n: int,
    quality: str | None = None,
    style: str | None = None,
) -> list[tuple[bytes, str, str]]:
    body, count = _image_request_options(
        config, prompt=prompt, size=size, n=n, quality=quality, style=style
    )
    response = await _http_request(
        config,
        "POST",
        "/images/generations",
        json_body=body,
        timeout=get_settings().integration_image_timeout_seconds,
    )
    return await _decode_image_payload(config, _require_json(response), count)


async def edit_images(
    config: IntegrationConfig,
    *,
    prompt: str,
    image: tuple[str, bytes, str],
    mask: tuple[str, bytes, str] | None,
    size: str | None,
    n: int,
    quality: str | None = None,
    style: str | None = None,
) -> list[tuple[bytes, str, str]]:
    body, count = _image_request_options(
        config, prompt=prompt, size=size, n=n, quality=quality, style=style
    )
    files: dict[str, Any] = {"image": image}
    if mask is not None:
        files["mask"] = mask
    response = await _http_request(
        config,
        "POST",
        "/images/edits",
        files=files,
        data=body,
        timeout=get_settings().integration_image_timeout_seconds,
    )
    return await _decode_image_payload(config, _require_json(response), count)


async def variation_images(
    config: IntegrationConfig,
    *,
    image: tuple[str, bytes, str],
    size: str | None,
    n: int,
) -> list[tuple[bytes, str, str]]:
    settings = get_settings()
    chosen_size = size or str((config.options or {}).get("size") or "1024x1024")
    if chosen_size not in IMAGE_SIZES:
        raise IntegrationError("invalid_size", "Unsupported image size")
    count = max(1, min(n, settings.integration_max_images_per_request))
    body = {
        "model": config.model or DEFAULT_MODELS["image_generation"],
        "n": count,
        "size": chosen_size,
    }
    response = await _http_request(
        config,
        "POST",
        "/images/variations",
        files={"image": image},
        data=body,
        timeout=settings.integration_image_timeout_seconds,
    )
    return await _decode_image_payload(config, _require_json(response), count)


def store_image_assets(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    config: IntegrationConfig,
    prompt: str,
    images: list[tuple[bytes, str, str]],
    metadata: dict[str, Any] | None = None,
) -> list[MediaAsset]:
    upload_dir = Path(get_settings().upload_dir) / "media"
    upload_dir.mkdir(parents=True, exist_ok=True)
    assets: list[MediaAsset] = []
    for raw, mime, extension in images:
        name = f"{secrets.token_hex(16)}.{extension}"
        path = upload_dir / name
        path.write_bytes(raw)
        asset = MediaAsset(
            workspace_id=workspace_id,
            user_id=user_id,
            integration_id=config.id,
            kind="image",
            filename=f"generated-{name}",
            mime=mime,
            size_bytes=len(raw),
            storage_path=str(path),
            prompt=prompt[:4000],
            asset_metadata={
                "provider": config.provider,
                "model": config.model,
                "integration_id": str(config.id),
                **(metadata or {}),
            },
        )
        session.add(asset)
        assets.append(asset)
    return assets


async def list_media(
    session: AsyncSession, workspace_id: UUID, *, limit: int = 50
) -> list[MediaAsset]:
    return list(
        (
            await session.execute(
                select(MediaAsset)
                .where(
                    MediaAsset.workspace_id == workspace_id,
                    MediaAsset.deleted_at.is_(None),
                )
                .order_by(MediaAsset.created_at.desc(), MediaAsset.id.desc())
                .limit(max(1, min(limit, 100)))
            )
        ).scalars()
    )


async def get_media(session: AsyncSession, media_id: UUID, workspace_id: UUID) -> MediaAsset:
    asset = (
        await session.execute(
            select(MediaAsset).where(
                MediaAsset.id == media_id,
                MediaAsset.workspace_id == workspace_id,
                MediaAsset.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if asset is None:
        raise IntegrationError("media_not_found", "Media asset not found")
    return asset


async def delete_media(
    session: AsyncSession, asset: MediaAsset, user_id: UUID, role: str
) -> None:
    if asset.user_id != user_id and role != "owner":
        raise IntegrationError("forbidden", "Only the creator can delete this asset")
    asset.deleted_at = datetime.now(UTC)
    await session.flush()


async def transcribe_audio(
    config: IntegrationConfig,
    *,
    filename: str,
    content: bytes,
    content_type: str,
    language: str | None,
    prompt: str | None,
) -> str:
    settings = get_settings()
    if len(content) > settings.integration_max_audio_bytes:
        raise IntegrationError("audio_too_large", "Audio file exceeds the size limit")
    data: dict[str, Any] = {"model": config.model or DEFAULT_MODELS["stt"]}
    chosen_language = language or (config.options or {}).get("language")
    if chosen_language:
        data["language"] = str(chosen_language)[:20]
    if prompt:
        data["prompt"] = prompt[:1000]
    response = await _http_request(
        config,
        "POST",
        "/audio/transcriptions",
        files={"file": (filename, content, content_type or "application/octet-stream")},
        data=data,
        timeout=settings.integration_audio_timeout_seconds,
    )
    payload = _require_json(response)
    text = payload.get("text")
    if not isinstance(text, str):
        raise IntegrationError("audio_bad_response", "Provider returned no transcript")
    return text


async def synthesize_speech(
    config: IntegrationConfig,
    *,
    text: str,
    voice: str | None,
    response_format: str | None,
    speed: float | None,
) -> tuple[bytes, str]:
    settings = get_settings()
    options = config.options or {}
    fmt = response_format or str(options.get("response_format") or "mp3")
    if fmt not in AUDIO_RESPONSE_FORMATS:
        raise IntegrationError("invalid_format", "Unsupported audio format")
    body = {
        "model": config.model or DEFAULT_MODELS["tts"],
        "input": text[: settings.integration_tts_max_chars],
        "voice": (voice or str(options.get("voice") or "alloy"))[:80],
        "response_format": fmt,
        "speed": min(max(float(speed or options.get("speed") or 1.0), 0.25), 4.0),
    }
    response = await _http_request(
        config,
        "POST",
        "/audio/speech",
        json_body=body,
        timeout=settings.integration_audio_timeout_seconds,
    )
    if response.status_code >= 400:
        raise _status_error(response.status_code)
    if not response.content:
        raise IntegrationError("audio_bad_response", "Provider returned no audio")
    return response.content, MEDIA_MIME_BY_FORMAT[fmt]


async def list_github_repos(config: IntegrationConfig) -> list[dict[str, Any]]:
    settings = get_settings()
    response = await _http_request(
        config,
        "GET",
        "/user/repos?sort=updated&per_page=30",
        timeout=settings.integration_github_timeout_seconds,
        max_bytes=2_000_000,
    )
    if response.status_code >= 400:
        raise _status_error(response.status_code)
    payload = response.json()
    if not isinstance(payload, list):
        raise IntegrationError("integration_bad_response", "GitHub returned invalid data")
    repos: list[dict[str, Any]] = []
    for item in payload[:30]:
        if not isinstance(item, dict):
            continue
        full_name = item.get("full_name")
        if not isinstance(full_name, str):
            continue
        repos.append(
            {
                "full_name": full_name,
                "description": str(item.get("description") or "")[:500],
                "private": bool(item.get("private")),
                "html_url": str(item.get("html_url") or ""),
                "updated_at": item.get("updated_at"),
            }
        )
    return repos


def _github_segment(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value):
        raise IntegrationError("invalid_repo", "Invalid repository path")
    return quote(value, safe="")


async def list_github_issues(
    config: IntegrationConfig, *, owner: str, repo: str, state: str
) -> list[dict[str, Any]]:
    settings = get_settings()
    if state not in {"open", "closed", "all"}:
        raise IntegrationError("invalid_state", "Unsupported issue state")
    path = (
        f"/repos/{_github_segment(owner)}/{_github_segment(repo)}/issues"
        f"?state={state}&per_page=30"
    )
    response = await _http_request(
        config,
        "GET",
        path,
        timeout=settings.integration_github_timeout_seconds,
        max_bytes=2_000_000,
    )
    if response.status_code >= 400:
        raise _status_error(response.status_code)
    payload = response.json()
    if not isinstance(payload, list):
        raise IntegrationError("integration_bad_response", "GitHub returned invalid data")
    issues: list[dict[str, Any]] = []
    for item in payload[:30]:
        if not isinstance(item, dict):
            continue
        issues.append(
            {
                "number": item.get("number"),
                "title": str(item.get("title") or "")[:500],
                "state": str(item.get("state") or ""),
                "html_url": str(item.get("html_url") or ""),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
            }
        )
    return issues


def elapsed_ms(started: float) -> int:
    return int(round((time.perf_counter() - started) * 1000))