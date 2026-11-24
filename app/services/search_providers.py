import logging
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SearchProviderConfig
from app.services.provider_secrets import api_key_hint, encrypt_api_key
from app.services.web_search import (
    DEFAULT_BASE_URLS,
    SEARCH_PROVIDERS,
    WebSearchError,
    search_web,
)

logger = logging.getLogger(__name__)

MAX_RESULTS_LIMIT = 20
MIN_TIMEOUT_SECONDS = 3
MAX_TIMEOUT_SECONDS = 60
TEST_QUERY = "AI power"


class SearchProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _normalize_provider(value: str) -> str:
    provider = (value or "").strip().lower()
    if provider not in SEARCH_PROVIDERS:
        raise SearchProviderError("invalid_provider", "Unsupported search provider")
    return provider


def _normalize_base_url(provider: str, value: str | None) -> str:
    base = (value or "").strip().rstrip("/")
    if base == "":
        if provider == "searxng":
            raise SearchProviderError("invalid_endpoint", "SearXNG requires a base URL")
        return DEFAULT_BASE_URLS[provider]
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SearchProviderError("invalid_endpoint", "Base URL must be http(s)")
    if parsed.username or parsed.password:
        raise SearchProviderError("invalid_endpoint", "Base URL must not contain credentials")
    return base


def _clamp(value: int, minimum: int, maximum: int, fallback: int) -> int:
    if value is None:
        return fallback
    return max(minimum, min(int(value), maximum))


def _config_query(config_id: UUID, workspace_id: UUID, user_id: UUID, *, owner_only: bool):
    conditions = [
        SearchProviderConfig.id == config_id,
        SearchProviderConfig.workspace_id == workspace_id,
        SearchProviderConfig.deleted_at.is_(None),
    ]
    if owner_only:
        conditions.append(SearchProviderConfig.owner_user_id == user_id)
    else:
        conditions.append(
            or_(
                SearchProviderConfig.owner_user_id == user_id,
                SearchProviderConfig.shared.is_(True),
            )
        )
    return select(SearchProviderConfig).where(*conditions)


async def get_config(
    session: AsyncSession,
    config_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    *,
    owner_only: bool = False,
) -> SearchProviderConfig:
    config = (
        await session.execute(
            _config_query(config_id, workspace_id, user_id, owner_only=owner_only)
        )
    ).scalar_one_or_none()
    if config is None:
        raise SearchProviderError("not_found", "Search provider not found")
    return config


async def list_configs(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> list[SearchProviderConfig]:
    return list(
        (
            await session.execute(
                select(SearchProviderConfig)
                .where(
                    SearchProviderConfig.workspace_id == workspace_id,
                    SearchProviderConfig.deleted_at.is_(None),
                    or_(
                        SearchProviderConfig.owner_user_id == user_id,
                        SearchProviderConfig.shared.is_(True),
                    ),
                )
                .order_by(
                    SearchProviderConfig.is_default.desc(),
                    SearchProviderConfig.created_at,
                )
            )
        ).scalars()
    )


async def create_config(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    provider: str,
    name: str,
    base_url: str | None,
    api_key: str | None,
    max_results: int,
    timeout_seconds: int,
    shared: bool,
    enabled: bool,
) -> SearchProviderConfig:
    kind = _normalize_provider(provider)
    key = (api_key or "").strip()
    if kind != "searxng" and key == "":
        raise SearchProviderError("api_key_required", "This provider requires an API key")
    existing = await list_configs(session, workspace_id, user_id)
    owns_any = any(item.owner_user_id == user_id for item in existing)
    config = SearchProviderConfig(
        workspace_id=workspace_id,
        owner_user_id=user_id,
        provider=kind,
        name=(name or "").strip()[:100] or kind.title(),
        base_url=_normalize_base_url(kind, base_url),
        api_key_encrypted=encrypt_api_key(key) if key else "",
        api_key_hint=api_key_hint(key) if key else "",
        max_results=_clamp(max_results, 1, MAX_RESULTS_LIMIT, 5),
        timeout_seconds=_clamp(timeout_seconds, MIN_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS, 15),
        shared=shared,
        enabled=enabled,
        is_default=not owns_any,
    )
    session.add(config)
    await session.flush()
    return config


async def update_config(
    session: AsyncSession,
    config: SearchProviderConfig,
    *,
    name: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    max_results: int | None = None,
    timeout_seconds: int | None = None,
    enabled: bool | None = None,
    shared: bool | None = None,
    is_default: bool | None = None,
) -> SearchProviderConfig:
    if name is not None:
        config.name = name.strip()[:100] or config.provider.title()
    if base_url is not None:
        config.base_url = _normalize_base_url(config.provider, base_url)
    if api_key is not None and api_key.strip() != "":
        config.api_key_encrypted = encrypt_api_key(api_key.strip())
        config.api_key_hint = api_key_hint(api_key.strip())
    if max_results is not None:
        config.max_results = _clamp(max_results, 1, MAX_RESULTS_LIMIT, config.max_results)
    if timeout_seconds is not None:
        config.timeout_seconds = _clamp(
            timeout_seconds,
            MIN_TIMEOUT_SECONDS,
            MAX_TIMEOUT_SECONDS,
            config.timeout_seconds,
        )
    if enabled is not None:
        config.enabled = enabled
        if not enabled:
            config.is_default = False
    if shared is not None:
        config.shared = shared
    if is_default is True:
        await session.execute(
            update(SearchProviderConfig)
            .where(
                SearchProviderConfig.workspace_id == config.workspace_id,
                SearchProviderConfig.owner_user_id == config.owner_user_id,
                SearchProviderConfig.id != config.id,
            )
            .values(is_default=False)
        )
        config.is_default = True
    await session.flush()
    return config


async def set_default(session: AsyncSession, config: SearchProviderConfig) -> SearchProviderConfig:
    if not config.enabled:
        raise SearchProviderError("provider_disabled", "Enable the provider first")
    await session.execute(
        update(SearchProviderConfig)
        .where(
            SearchProviderConfig.workspace_id == config.workspace_id,
            SearchProviderConfig.owner_user_id == config.owner_user_id,
            SearchProviderConfig.id != config.id,
        )
        .values(is_default=False)
    )
    config.is_default = True
    await session.flush()
    return config


async def delete_config(session: AsyncSession, config: SearchProviderConfig) -> None:
    from datetime import UTC, datetime

    config.deleted_at = datetime.now(UTC)
    config.is_default = False
    config.enabled = False
    await session.flush()


async def resolve_search_config(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    config_id: str | UUID | None = None,
) -> SearchProviderConfig:
    if config_id:
        try:
            target = UUID(str(config_id))
        except ValueError:
            raise SearchProviderError("not_found", "Search provider not found") from None
        config = await get_config(session, target, workspace_id, user_id)
        if not config.enabled:
            raise SearchProviderError(
                "provider_disabled", "The selected search provider is disabled"
            )
        return config
    own = list(
        (
            await session.execute(
                select(SearchProviderConfig)
                .where(
                    SearchProviderConfig.workspace_id == workspace_id,
                    SearchProviderConfig.owner_user_id == user_id,
                    SearchProviderConfig.deleted_at.is_(None),
                    SearchProviderConfig.enabled.is_(True),
                )
                .order_by(
                    SearchProviderConfig.is_default.desc(),
                    SearchProviderConfig.created_at,
                )
                .limit(1)
            )
        ).scalars()
    )
    if own:
        return own[0]
    shared = (
        await session.execute(
            select(SearchProviderConfig)
            .where(
                SearchProviderConfig.workspace_id == workspace_id,
                SearchProviderConfig.shared.is_(True),
                SearchProviderConfig.deleted_at.is_(None),
                SearchProviderConfig.enabled.is_(True),
            )
            .order_by(SearchProviderConfig.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if shared is not None:
        return shared
    raise SearchProviderError("search_not_configured", "Configure a web search provider first")


async def test_config(config: SearchProviderConfig) -> dict[str, Any]:
    from datetime import UTC, datetime

    config.last_tested_at = datetime.now(UTC)
    try:
        results = await search_web(config, TEST_QUERY, max_results=3)
    except WebSearchError as exc:
        config.status = "error"
        config.last_error = exc.code
        return {
            "status": "error",
            "error_code": exc.code,
            "message": exc.message,
            "result_count": 0,
        }
    config.status = "ok"
    config.last_error = None
    return {
        "status": "ok",
        "error_code": None,
        "message": "",
        "result_count": len(results),
    }
