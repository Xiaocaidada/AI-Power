"""P12-S1 chat mode and model capability framework.

Modes are persisted and validated here, but only ``chat`` and ``agent`` are
executable in this slice. Later slices add search, research and study runners.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelCatalog, ProviderConfig, ProviderModel

CHAT_MODE_CHAT = "chat"
CHAT_MODE_WEB_SEARCH = "web_search"
CHAT_MODE_DEEP_RESEARCH = "deep_research"
CHAT_MODE_STUDY = "study"
CHAT_MODE_AGENT = "agent"

CHAT_MODES: tuple[str, ...] = (
    CHAT_MODE_CHAT,
    CHAT_MODE_WEB_SEARCH,
    CHAT_MODE_DEEP_RESEARCH,
    CHAT_MODE_STUDY,
    CHAT_MODE_AGENT,
)

THINKING_FAST = "fast"
THINKING_STANDARD = "standard"
THINKING_DEEP = "deep"

THINKING_LEVELS: tuple[str, ...] = (THINKING_FAST, THINKING_STANDARD, THINKING_DEEP)
DEFAULT_THINKING_LEVEL = THINKING_STANDARD

_MODE_SPECS: dict[str, tuple[bool, tuple[str, ...]]] = {
    CHAT_MODE_CHAT: (True, ()),
    CHAT_MODE_WEB_SEARCH: (True, ()),
    CHAT_MODE_DEEP_RESEARCH: (True, ()),
    CHAT_MODE_STUDY: (True, ()),
    CHAT_MODE_AGENT: (True, ("tools",)),
}

_MODE_META_KEYS = frozenset(
    {
        "thinking_level",
        "search_provider_id",
        "research_task_id",
        "study_session_id",
        "agent_task_id",
        "web_search_enabled",
    }
)
_MAX_META_VALUE_LENGTH = 128


class ChatModeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ModelCapabilities:
    # ``None`` means the platform does not publish a full capability manifest
    # for this model; callers must not infer that a capability is unsupported.
    capabilities: list[str] | None
    reasoning_levels: list[str]


def mode_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": mode,
            "implemented": implemented,
            "requires": list(requires),
        }
        for mode, (implemented, requires) in _MODE_SPECS.items()
    ]


def normalize_mode(value: str | None, *, fallback: str = CHAT_MODE_CHAT) -> str:
    mode = (value or fallback).strip()
    if mode not in CHAT_MODES:
        raise ChatModeError("invalid_mode", f"Unknown chat mode: {mode}")
    return mode


def normalize_mode_meta(raw: dict[str, Any] | None) -> dict[str, Any]:
    source = raw or {}
    meta: dict[str, Any] = {"thinking_level": DEFAULT_THINKING_LEVEL}
    for key, value in source.items():
        if key not in _MODE_META_KEYS or value is None:
            continue
        if key == "web_search_enabled":
            if not isinstance(value, bool):
                raise ChatModeError("invalid_mode_meta", "web_search_enabled must be a boolean")
            meta[key] = value
            continue
        if not isinstance(value, str):
            raise ChatModeError("invalid_mode_meta", f"{key} must be a string")
        text = value.strip()
        if text == "":
            continue
        if len(text) > _MAX_META_VALUE_LENGTH:
            raise ChatModeError("invalid_mode_meta", f"{key} is too long")
        meta[key] = text
    level = meta["thinking_level"]
    if level not in THINKING_LEVELS:
        raise ChatModeError("invalid_thinking_level", f"Unknown thinking level: {level}")
    return meta


def reasoning_levels_for(
    capabilities: list[str] | None,
    declared: list[str] | None = None,
) -> list[str]:
    """Return supported levels in canonical order.

    A model that declares ``reasoning`` but no explicit levels supports standard
    and deep. Everything else supports standard only; a level is never silently
    downgraded after being accepted.
    """
    if declared:
        allowed = {item for item in declared if item in THINKING_LEVELS}
        levels = [item for item in THINKING_LEVELS if item in allowed]
        if levels:
            return levels
    if capabilities is not None and "reasoning" in capabilities:
        return [THINKING_STANDARD, THINKING_DEEP]
    return [THINKING_STANDARD]


# Real OpenAI-compatible parameter mapping. ``standard`` deliberately sends no
# override so models that only expose a default behaviour are never mutated.
THINKING_PROVIDER_PARAMS: dict[str, dict[str, object]] = {
    THINKING_FAST: {"reasoning_effort": "low"},
    THINKING_STANDARD: {},
    THINKING_DEEP: {"reasoning_effort": "high"},
}


def thinking_provider_opts(level: str) -> dict[str, object]:
    """Map a validated level to provider request parameters."""
    return dict(THINKING_PROVIDER_PARAMS.get(level, {}))


def ensure_thinking_supported(
    level: str,
    *,
    capabilities: list[str] | None,
    reasoning_levels: list[str] | None,
) -> list[str]:
    supported = reasoning_levels_for(capabilities, reasoning_levels)
    if level not in supported:
        raise ChatModeError(
            "thinking_level_unsupported",
            f"Model does not support thinking level '{level}'",
        )
    return supported


def validate_turn_mode(
    *,
    mode: str | None,
    mode_meta: dict[str, Any] | None,
    capabilities: list[str] | None,
    reasoning_levels: list[str] | None,
    agent: bool,
) -> tuple[str, dict[str, Any]]:
    resolved_mode = normalize_mode(mode)
    meta = normalize_mode_meta(mode_meta)
    implemented, requires = _MODE_SPECS[resolved_mode]
    if not implemented:
        raise ChatModeError(
            "mode_not_available",
            f"Chat mode '{resolved_mode}' is planned for a later slice",
        )
    if resolved_mode == CHAT_MODE_AGENT and not agent:
        raise ChatModeError(
            "mode_requires_agent",
            "Agent mode requires an Agent conversation",
        )
    if resolved_mode == CHAT_MODE_CHAT and agent:
        raise ChatModeError(
            "mode_conflict",
            "An Agent conversation must use agent mode",
        )
    if capabilities is not None and "tools" in requires and "tools" not in capabilities:
        raise ChatModeError("mode_requires_tools", "This model does not support tools")
    ensure_thinking_supported(
        meta["thinking_level"],
        capabilities=capabilities,
        reasoning_levels=reasoning_levels,
    )
    return resolved_mode, meta


def mode_for_agent(agent: bool) -> str:
    return CHAT_MODE_AGENT if agent else CHAT_MODE_CHAT


async def resolve_model_capabilities(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    provider_id: str,
    model_id: str,
) -> ModelCapabilities:
    """Resolve declared capabilities for the conversation's concrete model."""
    if provider_id == "auto" or model_id == "auto":
        return ModelCapabilities(capabilities=None, reasoning_levels=[])

    try:
        config_id = UUID(provider_id)
    except ValueError:
        config_id = None

    if config_id is not None:
        config = (
            await session.execute(
                select(ProviderConfig).where(
                    ProviderConfig.id == config_id,
                    ProviderConfig.workspace_id == workspace_id,
                    ProviderConfig.deleted_at.is_(None),
                    or_(
                        ProviderConfig.owner_user_id == user_id,
                        ProviderConfig.shared.is_(True),
                    ),
                )
            )
        ).scalar_one_or_none()
        if config is not None:
            model = (
                await session.execute(
                    select(ProviderModel).where(
                        ProviderModel.config_id == config.id,
                        ProviderModel.model_id == model_id,
                        ProviderModel.enabled.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if model is not None:
                capabilities = list(model.capabilities or [])
                return ModelCapabilities(
                    capabilities=capabilities,
                    reasoning_levels=reasoning_levels_for(
                        capabilities, list(model.reasoning_levels or [])
                    ),
                )
        return ModelCapabilities(capabilities=None, reasoning_levels=[])

    catalog = (
        await session.execute(
            select(ModelCatalog).where(
                ModelCatalog.provider_id == provider_id,
                ModelCatalog.model_id == model_id,
            )
        )
    ).scalar_one_or_none()
    if catalog is None:
        return ModelCapabilities(capabilities=None, reasoning_levels=[])
    tags = [tag for tag in (catalog.tags or "").split(",") if tag]
    declared = list(catalog.reasoning_levels or [])
    return ModelCapabilities(
        capabilities=None,
        reasoning_levels=reasoning_levels_for(
            ["reasoning"] if "reasoning" in tags else [],
            declared or (["standard", "deep"] if "reasoning" in tags else []),
        ),
    )
