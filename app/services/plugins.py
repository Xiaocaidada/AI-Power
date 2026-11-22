import asyncio
import json
import keyword
import re
import socket
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, create_model
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.models import (
    Conversation,
    ConversationPlugin,
    PluginCall,
    PluginConfig,
    PluginDefinition,
)
from app.services.provider_secrets import api_key_hint, decrypt_api_key, encrypt_api_key
from app.services.webhooks import _is_blocked_address, validate_url_shape
from app.tools.base import ToolContext, ToolError, ToolSpec

PLUGIN_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,40}$")
PLUGIN_TYPES = {"string": str, "integer": int, "number": float, "boolean": bool}
MAX_PARAMETERS = 10


class PluginError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_parameters(value: dict[str, Any] | None) -> dict[str, Any]:
    schema = value or {}
    if not isinstance(schema, dict):
        raise PluginError("invalid_parameters", "parameters must be a JSON object")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise PluginError("invalid_parameters", "parameters must contain properties/required")
    if len(properties) > MAX_PARAMETERS:
        raise PluginError("invalid_parameters", f"At most {MAX_PARAMETERS} parameters")
    normalized: dict[str, Any] = {}
    for name, spec in properties.items():
        if (
            not isinstance(name, str)
            or not PLUGIN_NAME_RE.match(name)
            or keyword.iskeyword(name)
        ):
            raise PluginError("invalid_parameters", f"Invalid parameter name: {name}")
        if not isinstance(spec, dict):
            raise PluginError("invalid_parameters", f"Invalid parameter: {name}")
        type_name = spec.get("type", "string")
        if type_name not in PLUGIN_TYPES:
            raise PluginError("invalid_parameters", f"Unsupported type for {name}: {type_name}")
        normalized[name] = {
            "type": type_name,
            "description": str(spec.get("description", ""))[:200],
        }
    return {
        "type": "object",
        "properties": normalized,
        "required": [name for name in required if name in normalized],
    }


def build_arguments_model(definition: PluginDefinition) -> type[BaseModel]:
    schema = definition.parameters or {}
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields: dict[str, Any] = {}
    for name, spec in properties.items():
        python_type = PLUGIN_TYPES.get(spec.get("type", "string"), str)
        fields[name] = (
            python_type if name in required else python_type | None,
            ... if name in required else None,
        )
    return create_model(
        f"PluginArgs_{definition.slug.replace('-', '_')}",
        **fields,
        __doc__=definition.description,
    )


def plugin_tool_name(definition: PluginDefinition) -> str:
    return f"plugin__{definition.slug.replace('-', '_')}"


def _allowed_host(host: str, settings: Settings) -> bool:
    allowed = [
        item.strip().lower()
        for item in settings.plugin_allowed_hosts.split(",")
        if item.strip()
    ]
    if not allowed:
        return True
    lowered = host.lower()
    return any(lowered == item or lowered.endswith(f".{item}") for item in allowed)


async def validate_plugin_endpoint(url: str, settings: Settings | None = None) -> None:
    current = settings or get_settings()
    try:
        validate_url_shape(url)
    except ValueError as exc:
        raise PluginError("invalid_url", str(exc)) from None
    parsed = urlsplit(url)
    if current.app_env != "dev" and parsed.scheme != "https":
        raise PluginError("invalid_url", "Plugin endpoints must use HTTPS outside dev")
    if not _allowed_host(parsed.hostname or "", current):
        raise PluginError("host_not_allowed", "Plugin host is not in PLUGIN_ALLOWED_HOSTS")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo, parsed.hostname, port, 0, socket.SOCK_STREAM
        )
    except OSError:
        raise PluginError("invalid_url", "Plugin hostname cannot be resolved") from None
    if not addresses:
        raise PluginError("invalid_url", "Plugin hostname cannot be resolved")
    for address in addresses:
        host = str(address[4][0])
        if _is_blocked_address(host, current.plugin_allow_private_hosts):
            raise PluginError("invalid_url", "Plugin URL resolves to a private or reserved address")


async def list_plugin_rows(
    session: AsyncSession, workspace_id: UUID
) -> list[tuple[PluginDefinition, PluginConfig | None]]:
    definitions = list(
        (
            await session.execute(
                select(PluginDefinition)
                .where(PluginDefinition.enabled.is_(True))
                .order_by(PluginDefinition.category, PluginDefinition.name)
            )
        ).scalars()
    )
    configs = {
        config.plugin_id: config
        for config in (
            await session.execute(
                select(PluginConfig).where(PluginConfig.workspace_id == workspace_id)
            )
        ).scalars()
    }
    return [(definition, configs.get(definition.id)) for definition in definitions]


async def get_definition(session: AsyncSession, plugin_id: UUID) -> PluginDefinition:
    definition = await session.get(PluginDefinition, plugin_id)
    if definition is None:
        raise PluginError("not_found", "Plugin not found")
    return definition


async def get_workspace_config(
    session: AsyncSession, workspace_id: UUID, plugin_id: UUID
) -> PluginConfig | None:
    return (
        await session.execute(
            select(PluginConfig).where(
                PluginConfig.workspace_id == workspace_id,
                PluginConfig.plugin_id == plugin_id,
            )
        )
    ).scalar_one_or_none()


async def create_definition(
    session: AsyncSession, values: dict[str, Any], settings: Settings | None = None
) -> PluginDefinition:
    await validate_plugin_endpoint(values["endpoint_url"], settings)
    values["parameters"] = normalize_parameters(values.get("parameters"))
    existing = (
        await session.execute(
            select(PluginDefinition.id).where(PluginDefinition.slug == values["slug"])
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise PluginError("duplicate", "Plugin slug already exists")
    definition = PluginDefinition(**values)
    session.add(definition)
    await session.flush()
    return definition


async def update_definition(
    session: AsyncSession,
    definition: PluginDefinition,
    values: dict[str, Any],
    settings: Settings | None = None,
) -> PluginDefinition:
    if "endpoint_url" in values and values["endpoint_url"] is not None:
        await validate_plugin_endpoint(values["endpoint_url"], settings)
    if "parameters" in values and values["parameters"] is not None:
        values["parameters"] = normalize_parameters(values["parameters"])
    for key, value in values.items():
        setattr(definition, key, value)
    await session.flush()
    return definition


async def delete_definition(session: AsyncSession, definition: PluginDefinition) -> None:
    await session.execute(
        delete(PluginCall).where(PluginCall.plugin_id == definition.id)
    )
    await session.execute(
        delete(ConversationPlugin).where(ConversationPlugin.plugin_id == definition.id)
    )
    await session.execute(
        delete(PluginConfig).where(PluginConfig.plugin_id == definition.id)
    )
    await session.delete(definition)
    await session.flush()


async def upsert_workspace_config(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    definition: PluginDefinition,
    enabled: bool,
    credential: str | None,
    user_id: UUID,
) -> PluginConfig:
    config = await get_workspace_config(session, workspace_id, definition.id)
    if config is None:
        config = PluginConfig(
            workspace_id=workspace_id,
            plugin_id=definition.id,
            created_by=user_id,
        )
        session.add(config)
    config.enabled = enabled
    if credential is not None:
        if credential.strip() == "":
            config.credential_encrypted = ""
            config.credential_hint = ""
        else:
            config.credential_encrypted = encrypt_api_key(credential)
            config.credential_hint = api_key_hint(credential)
    config.status = (
        "configured"
        if definition.auth_type == "none" or config.credential_encrypted
        else "missing_credential"
    )
    await session.flush()
    return config


async def list_conversation_plugins(
    session: AsyncSession, conversation_id: UUID
) -> list[tuple[ConversationPlugin, PluginDefinition]]:
    rows = (
        await session.execute(
            select(ConversationPlugin, PluginDefinition)
            .join(PluginDefinition, PluginDefinition.id == ConversationPlugin.plugin_id)
            .where(ConversationPlugin.conversation_id == conversation_id)
            .order_by(PluginDefinition.name)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def set_conversation_plugins(
    session: AsyncSession,
    conversation: Conversation,
    plugin_ids: list[UUID],
    *,
    confirmed_ids: set[UUID] | None = None,
) -> list[tuple[ConversationPlugin, PluginDefinition]]:
    unique_ids = list(dict.fromkeys(plugin_ids))
    if unique_ids:
        definitions = list(
            (
                await session.execute(
                    select(PluginDefinition).where(
                        PluginDefinition.id.in_(unique_ids),
                        PluginDefinition.enabled.is_(True),
                    )
                )
            ).scalars()
        )
        if len(definitions) != len(unique_ids):
            raise PluginError("not_found", "Plugin not found")
        configs = {
            config.plugin_id: config
            for config in (
                await session.execute(
                    select(PluginConfig).where(
                        PluginConfig.workspace_id == conversation.workspace_id,
                        PluginConfig.plugin_id.in_(unique_ids),
                        PluginConfig.enabled.is_(True),
                    )
                )
            ).scalars()
        }
        if len(configs) != len(unique_ids):
            raise PluginError("not_configured", "Plugin is not enabled for this workspace")
    await session.execute(
        delete(ConversationPlugin).where(
            ConversationPlugin.conversation_id == conversation.id,
            ConversationPlugin.plugin_id.notin_(unique_ids) if unique_ids else True,
        )
    )
    existing = {
        row.plugin_id: row
        for row in (
            await session.execute(
                select(ConversationPlugin).where(
                    ConversationPlugin.conversation_id == conversation.id
                )
            )
        ).scalars()
    }
    now = datetime.now(UTC)
    for plugin_id in unique_ids:
        row = existing.get(plugin_id)
        if row is None:
            row = ConversationPlugin(conversation_id=conversation.id, plugin_id=plugin_id)
            session.add(row)
        if confirmed_ids is not None and plugin_id in confirmed_ids:
            row.confirmed_at = now
    await session.flush()
    return await list_conversation_plugins(session, conversation.id)


async def confirm_conversation_plugin(
    session: AsyncSession, conversation_id: UUID, plugin_id: UUID, confirmed: bool
) -> ConversationPlugin:
    row = (
        await session.execute(
            select(ConversationPlugin).where(
                ConversationPlugin.conversation_id == conversation_id,
                ConversationPlugin.plugin_id == plugin_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise PluginError("not_found", "Plugin is not enabled for this conversation")
    row.confirmed_at = datetime.now(UTC) if confirmed else None
    await session.flush()
    return row


async def build_plugin_tools(
    session: AsyncSession, conversation: Conversation
) -> list[ToolSpec]:
    rows = (
        await session.execute(
            select(ConversationPlugin, PluginDefinition)
            .join(PluginDefinition, PluginDefinition.id == ConversationPlugin.plugin_id)
            .join(
                PluginConfig,
                (PluginConfig.plugin_id == PluginDefinition.id)
                & (PluginConfig.workspace_id == conversation.workspace_id)
                & (PluginConfig.enabled.is_(True)),
            )
            .where(
                ConversationPlugin.conversation_id == conversation.id,
                PluginDefinition.enabled.is_(True),
            )
        )
    ).all()
    tools: list[ToolSpec] = []
    for _conversation_plugin, definition in rows:
        tools.append(
            ToolSpec(
                name=plugin_tool_name(definition),
                description=(
                    f"{definition.description} "
                    + ("Sensitive: requires explicit confirmation." if definition.sensitive else "")
                ).strip(),
                args_model=build_arguments_model(definition),
                handler=_plugin_handler(definition.id),
            )
        )
    return tools


def plugin_tool_names(tools: list[ToolSpec]) -> tuple[str, ...]:
    return tuple(tool.name for tool in tools)


def _plugin_handler(plugin_id: UUID):
    async def handler(context: ToolContext, arguments: BaseModel) -> str:
        payload = arguments.model_dump(exclude_none=True)
        return await execute_plugin(plugin_id, payload, context)

    return handler


async def execute_plugin(
    plugin_id: UUID, arguments: dict[str, Any], context: ToolContext
) -> str:
    reference = get_settings()
    async with SessionLocal() as session:
        definition = await session.get(PluginDefinition, plugin_id)
        if definition is None or not definition.enabled:
            raise ToolError("plugin_not_found", "Plugin is not available")
        config = await get_workspace_config(session, context.workspace_id, plugin_id)
        if config is None or not config.enabled:
            raise ToolError("plugin_not_configured", "Plugin is not enabled for this workspace")
        if context.conversation_id is not None:
            row = (
                await session.execute(
                    select(ConversationPlugin).where(
                        ConversationPlugin.conversation_id == context.conversation_id,
                        ConversationPlugin.plugin_id == plugin_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                raise ToolError("plugin_not_enabled", "Plugin is not enabled for this conversation")
            if definition.sensitive and row.confirmed_at is None:
                raise ToolError(
                    "plugin_confirmation_required",
                    "Sensitive plugin requires user confirmation",
                )
        elif definition.sensitive:
            raise ToolError(
                "plugin_confirmation_required",
                "Sensitive plugin requires a conversation confirmation",
            )
        credential = ""
        if definition.auth_type == "bearer":
            if not config.credential_encrypted:
                raise ToolError("plugin_missing_credential", "Plugin credential is not configured")
            try:
                credential = decrypt_api_key(config.credential_encrypted)
            except ValueError:
                raise ToolError(
                    "plugin_missing_credential", "Plugin credential is invalid"
                ) from None
        endpoint = definition.endpoint_url
        method = definition.method
        timeout = min(float(definition.timeout_seconds), reference.plugin_timeout_seconds)
        max_chars = reference.plugin_max_response_chars

    await validate_plugin_endpoint(endpoint, reference)
    headers = {"Accept": "application/json"}
    if credential:
        headers["Authorization"] = f"Bearer {credential}"
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False, trust_env=False
        ) as client:
            if method == "GET":
                response = await client.get(endpoint, params=arguments, headers=headers)
            else:
                response = await client.post(endpoint, json=arguments, headers=headers)
            chunks: list[bytes] = []
            total = 0
            limit = max_chars * 4
            async for chunk in response.aiter_bytes():
                remaining = limit - total
                if remaining <= 0:
                    break
                chunks.append(chunk[:remaining])
                total += min(len(chunk), remaining)
            raw = b"".join(chunks).decode("utf-8", errors="replace")
            text = raw[:max_chars]
            latency = round((time.perf_counter() - started) * 1000)
            if response.status_code >= 300:
                await _record_call(
                    context,
                    plugin_id,
                    "error",
                    arguments,
                    text,
                    latency,
                    f"http_{response.status_code}",
                )
                raise ToolError(
                    "plugin_http_error", f"Plugin returned HTTP {response.status_code}"
                )
            await _record_call(context, plugin_id, "ok", arguments, text, latency, None)
            return text or f"Plugin {definition.name} returned an empty response"
    except ToolError:
        raise
    except httpx.TimeoutException:
        await _record_call(
            context, plugin_id, "error", arguments, "", int(timeout * 1000), "plugin_timeout"
        )
        raise ToolError("plugin_timeout", "Plugin request timed out") from None
    except httpx.HTTPError as exc:
        await _record_call(
            context, plugin_id, "error", arguments, "", 0, "plugin_unreachable"
        )
        raise ToolError("plugin_unreachable", f"Plugin unreachable: {type(exc).__name__}") from None


async def _record_call(
    context: ToolContext,
    plugin_id: UUID,
    status: str,
    arguments: dict[str, Any],
    response_text: str,
    latency_ms: int,
    error_code: str | None,
) -> None:
    try:
        async with SessionLocal() as session:
            session.add(
                PluginCall(
                    workspace_id=context.workspace_id,
                    conversation_id=context.conversation_id,
                    plugin_id=plugin_id,
                    status=status,
                    request_summary=json.dumps(arguments, ensure_ascii=False)[:500],
                    response_summary=response_text[:500],
                    latency_ms=latency_ms,
                    error_code=error_code,
                )
            )
            await session.commit()
    except Exception:
        return


async def list_plugin_calls(
    session: AsyncSession, workspace_id: UUID, conversation_id: UUID | None = None
) -> list[PluginCall]:
    conditions = [PluginCall.workspace_id == workspace_id]
    if conversation_id is not None:
        conditions.append(PluginCall.conversation_id == conversation_id)
    return list(
        (
            await session.execute(
                select(PluginCall)
                .where(*conditions)
                .order_by(PluginCall.created_at.desc())
                .limit(100)
            )
        ).scalars()
    )