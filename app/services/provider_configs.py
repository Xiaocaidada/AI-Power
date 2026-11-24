import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import ProviderConfig, ProviderModel
from app.providers.base import ProviderError
from app.providers.openai_compat import OpenAICompatProvider
from app.providers.registry import ProviderRegistry, build_registry
from app.services.chat_modes import THINKING_LEVELS
from app.services.provider_secrets import api_key_hint, decrypt_api_key, encrypt_api_key

logger = logging.getLogger(__name__)

PROVIDER_TYPES = frozenset({"openai_compatible", "custom"})
DEFAULT_CAPABILITIES = ["chat", "stream"]
ALLOWED_CAPABILITIES = frozenset(
    {
        "chat",
        "stream",
        "tools",
        "vision",
        "file",
        "structured",
        "reasoning",
        "long_context",
        "embedding",
        "rerank",
    }
)


class ProviderConfigError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _validate_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProviderConfigError("invalid_endpoint", "Endpoint must be an http(s) URL")
    if parsed.username or parsed.password:
        raise ProviderConfigError("invalid_endpoint", "Endpoint must not contain credentials")
    return base_url


def _normalize_capabilities(capabilities: list[str] | None) -> list[str]:
    values = capabilities or DEFAULT_CAPABILITIES
    unique = sorted({item for item in values if item in ALLOWED_CAPABILITIES})
    return unique or list(DEFAULT_CAPABILITIES)


def _normalize_reasoning_levels(levels: list[str] | None) -> list[str]:
    if not levels:
        return []
    allowed = {item for item in levels if item in THINKING_LEVELS}
    return [item for item in THINKING_LEVELS if item in allowed]


def _config_query(config_id: UUID, workspace_id: UUID, user_id: UUID, *, owner_only: bool):
    conditions = [
        ProviderConfig.id == config_id,
        ProviderConfig.workspace_id == workspace_id,
        ProviderConfig.deleted_at.is_(None),
    ]
    if owner_only:
        conditions.append(ProviderConfig.owner_user_id == user_id)
    else:
        conditions.append(
            or_(
                ProviderConfig.owner_user_id == user_id,
                ProviderConfig.shared.is_(True),
            )
        )
    return select(ProviderConfig).where(*conditions)


async def get_config(
    session: AsyncSession,
    config_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    *,
    owner_only: bool = False,
) -> ProviderConfig:
    config = (
        await session.execute(
            _config_query(config_id, workspace_id, user_id, owner_only=owner_only)
        )
    ).scalar_one_or_none()
    if config is None:
        raise ProviderConfigError("not_found", "Provider config not found")
    return config


async def list_configs(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> list[tuple[ProviderConfig, int]]:
    configs = list(
        (
            await session.execute(
                select(ProviderConfig)
                .where(
                    ProviderConfig.workspace_id == workspace_id,
                    ProviderConfig.deleted_at.is_(None),
                    or_(
                        ProviderConfig.owner_user_id == user_id,
                        ProviderConfig.shared.is_(True),
                    ),
                )
                .order_by(ProviderConfig.created_at.desc(), ProviderConfig.id.desc())
            )
        ).scalars()
    )
    if not configs:
        return []
    count_rows = (
        await session.execute(
            select(ProviderModel.config_id, func.count())
            .where(ProviderModel.config_id.in_([config.id for config in configs]))
            .group_by(ProviderModel.config_id)
        )
    ).all()
    counts = {row[0]: row[1] for row in count_rows}
    return [(config, counts.get(config.id, 0)) for config in configs]


async def create_config(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    name: str,
    provider_type: str,
    base_url: str,
    api_key: str,
    note: str = "",
    shared: bool = False,
) -> ProviderConfig:
    if provider_type not in PROVIDER_TYPES:
        raise ProviderConfigError("invalid_type", "Unsupported provider type")
    if not api_key.strip():
        raise ProviderConfigError("invalid_api_key", "API key is required")
    config = ProviderConfig(
        workspace_id=workspace_id,
        owner_user_id=user_id,
        name=name.strip(),
        provider_type=provider_type,
        base_url=_validate_base_url(base_url),
        api_key_encrypted=encrypt_api_key(api_key.strip()),
        api_key_hint=api_key_hint(api_key.strip()),
        note=note.strip(),
        shared=shared,
        status="unknown",
    )
    session.add(config)
    await session.flush()
    return config


async def update_config(
    session: AsyncSession,
    config: ProviderConfig,
    *,
    name: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    note: str | None = None,
    shared: bool | None = None,
) -> ProviderConfig:
    if name is not None:
        config.name = name.strip()
    if base_url is not None:
        config.base_url = _validate_base_url(base_url)
    if api_key is not None and api_key.strip():
        config.api_key_encrypted = encrypt_api_key(api_key.strip())
        config.api_key_hint = api_key_hint(api_key.strip())
        config.status = "unknown"
        config.last_error = None
    if note is not None:
        config.note = note.strip()
    if shared is not None:
        config.shared = shared
    await session.flush()
    return config


def build_provider(config: ProviderConfig) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        str(config.id),
        config.base_url,
        decrypt_api_key(config.api_key_encrypted),
        timeout=get_settings().provider_timeout_seconds,
    )


async def test_config(session: AsyncSession, config: ProviderConfig) -> dict[str, Any]:
    try:
        provider = build_provider(config)
        models = await provider.list_models()
    except ProviderError as exc:
        config.status = "error"
        config.last_error = exc.code
        config.last_tested_at = datetime.now(UTC)
        await session.flush()
        return {"status": "error", "model_count": 0, "error_code": exc.code}
    except Exception:
        logger.exception("provider config test failed")
        config.status = "error"
        config.last_error = "provider_unreachable"
        config.last_tested_at = datetime.now(UTC)
        await session.flush()
        return {
            "status": "error",
            "model_count": 0,
            "error_code": "provider_unreachable",
        }
    config.status = "ok"
    config.last_error = None
    config.last_tested_at = datetime.now(UTC)
    await session.flush()
    return {"status": "ok", "model_count": len(models), "error_code": None}


async def sync_models(session: AsyncSession, config: ProviderConfig) -> dict[str, int]:
    try:
        models = await build_provider(config).list_models()
    except ProviderError as exc:
        config.status = "error"
        config.last_error = exc.code
        config.last_tested_at = datetime.now(UTC)
        await session.flush()
        raise ProviderConfigError(exc.code, exc.message) from None
    except Exception:
        config.status = "error"
        config.last_error = "provider_unreachable"
        config.last_tested_at = datetime.now(UTC)
        await session.flush()
        raise ProviderConfigError("provider_unreachable", "Provider is unreachable") from None

    existing = {
        model.model_id: model
        for model in (
            await session.execute(select(ProviderModel).where(ProviderModel.config_id == config.id))
        ).scalars()
    }
    added = 0
    updated = 0
    for info in models:
        model = existing.get(info.id)
        if model is None:
            session.add(
                ProviderModel(
                    config_id=config.id,
                    model_id=info.id,
                    display_name=info.id,
                    capabilities=list(DEFAULT_CAPABILITIES),
                    source="synced",
                )
            )
            added += 1
        else:
            if model.display_name == "":
                model.display_name = info.id
            model.source = "synced"
            updated += 1
    config.status = "ok"
    config.last_error = None
    config.last_tested_at = datetime.now(UTC)
    await session.flush()
    return {"added": added, "updated": updated, "total": len(models)}


async def list_models(session: AsyncSession, config_id: UUID) -> list[ProviderModel]:
    return list(
        (
            await session.execute(
                select(ProviderModel)
                .where(ProviderModel.config_id == config_id)
                .order_by(ProviderModel.model_id)
            )
        ).scalars()
    )


async def add_model(
    session: AsyncSession,
    config: ProviderConfig,
    *,
    model_id: str,
    display_name: str,
    capabilities: list[str] | None,
    reasoning_levels: list[str] | None = None,
) -> ProviderModel:
    existing = (
        await session.execute(
            select(ProviderModel).where(
                ProviderModel.config_id == config.id,
                ProviderModel.model_id == model_id.strip(),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ProviderConfigError("model_exists", "Model already exists for this provider")
    model = ProviderModel(
        config_id=config.id,
        model_id=model_id.strip(),
        display_name=display_name.strip() or model_id.strip(),
        capabilities=_normalize_capabilities(capabilities),
        reasoning_levels=_normalize_reasoning_levels(reasoning_levels),
        source="manual",
    )
    session.add(model)
    await session.flush()
    return model


async def update_model(
    session: AsyncSession,
    model: ProviderModel,
    *,
    display_name: str | None = None,
    capabilities: list[str] | None = None,
    reasoning_levels: list[str] | None = None,
    enabled: bool | None = None,
) -> ProviderModel:
    if display_name is not None:
        model.display_name = display_name.strip() or model.model_id
    if capabilities is not None:
        model.capabilities = _normalize_capabilities(capabilities)
    if reasoning_levels is not None:
        model.reasoning_levels = _normalize_reasoning_levels(reasoning_levels)
    if enabled is not None:
        model.enabled = enabled
    await session.flush()
    return model


async def accessible_models(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(ProviderModel, ProviderConfig)
            .join(ProviderConfig, ProviderConfig.id == ProviderModel.config_id)
            .where(
                ProviderConfig.workspace_id == workspace_id,
                ProviderConfig.deleted_at.is_(None),
                or_(
                    ProviderConfig.owner_user_id == user_id,
                    ProviderConfig.shared.is_(True),
                ),
                ProviderModel.enabled.is_(True),
            )
            .order_by(ProviderConfig.name, ProviderModel.model_id)
        )
    ).all()
    return [
        {
            "provider_id": str(config.id),
            "provider_name": config.name,
            "model_id": model.model_id,
            "display_name": model.display_name or model.model_id,
            "capabilities": list(model.capabilities),
            "reasoning_levels": list(model.reasoning_levels or []),
        }
        for model, config in rows
    ]


async def build_user_registry(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    *,
    base: ProviderRegistry | None = None,
) -> ProviderRegistry:
    registry = base or build_registry()
    providers = {provider.id: provider for provider in registry.all()}
    configs = (
        await session.execute(
            select(ProviderConfig).where(
                ProviderConfig.workspace_id == workspace_id,
                ProviderConfig.deleted_at.is_(None),
                or_(
                    ProviderConfig.owner_user_id == user_id,
                    ProviderConfig.shared.is_(True),
                ),
            )
        )
    ).scalars()
    for config in configs:
        try:
            providers[str(config.id)] = build_provider(config)
        except Exception:
            logger.warning("skipping unusable provider config %s", config.id, exc_info=True)
    return ProviderRegistry(providers)


async def ensure_model_capability(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    provider_id: str,
    model_id: str,
    capability: str,
) -> None:
    """Validate a user provider model and capability; platform providers pass through."""
    try:
        config_id = UUID(provider_id)
    except ValueError:
        return
    config = (
        await session.execute(_config_query(config_id, workspace_id, user_id, owner_only=False))
    ).scalar_one_or_none()
    if config is None:
        raise ProviderConfigError("not_found", "Provider config not found")
    model = (
        await session.execute(
            select(ProviderModel).where(
                ProviderModel.config_id == config.id,
                ProviderModel.model_id == model_id,
            )
        )
    ).scalar_one_or_none()
    if model is None or not model.enabled:
        raise ProviderConfigError("model_not_found", "Provider model not found")
    if capability not in model.capabilities:
        raise ProviderConfigError(
            "capability_unsupported",
            f"Model does not support {capability}",
        )
