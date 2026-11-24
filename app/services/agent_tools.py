"""Agent tool catalog, MCP bindings and safe single-tool execution.

MCP tools are referenced in ``custom_agents.tools`` as
``mcp:<server_uuid>:<remote_tool_name>``. Remote tool schemas are discovered
best-effort and cached in-process; execution always goes through the existing
SSRF-safe MCP client and per-tool timeout.
"""

import time
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CustomAgent, McpServer
from app.services.mcp import McpError, call_mcp_tool, list_mcp_tools
from app.tools.base import ToolContext, ToolError, ToolSpec
from app.tools.mcp import MCP_TOOL_PREFIX, format_mcp_tool, parse_mcp_tool_ref
from app.tools.registry import build_tool_registry

SELECTABLE_BUILTIN_TOOLS = (
    "kb_search",
    "current_time",
    "calculator",
    "project_files",
)
MCP_TOOL_NAME_MAX = 120
DISCOVERY_TTL_SECONDS = 120.0

_discovery_cache: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}


class AgentToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class McpToolArgs(BaseModel):
    model_config = ConfigDict(extra="allow")


def is_mcp_tool(name: str) -> bool:
    return name.startswith(MCP_TOOL_PREFIX)


async def validate_agent_tools(
    session: AsyncSession, tools: list[str]
) -> list[str]:
    unique = list(dict.fromkeys(tools))
    server_ids: list[UUID] = []
    for tool in unique:
        if tool in SELECTABLE_BUILTIN_TOOLS or tool in {
            "memory_search",
            "memory_save",
        }:
            continue
        parsed = parse_mcp_tool_ref(tool)
        if parsed is None:
            raise AgentToolError("invalid_tools", f"Unknown tools: {tool}")
        server_id, remote_name = parsed
        if not remote_name or len(remote_name) > MCP_TOOL_NAME_MAX:
            raise AgentToolError("invalid_tools", "Invalid MCP tool name")
        if server_id not in server_ids:
            server_ids.append(server_id)
    if server_ids:
        enabled = set(
            (
                await session.execute(
                    select(McpServer.id).where(
                        McpServer.id.in_(server_ids),
                        McpServer.enabled.is_(True),
                    )
                )
            ).scalars()
        )
        missing = [str(item) for item in server_ids if item not in enabled]
        if missing:
            raise AgentToolError(
                "invalid_tools", "MCP server is missing or disabled"
            )
    return unique


async def _discover_server(server: McpServer) -> dict[str, dict[str, Any]]:
    key = str(server.id)
    cached = _discovery_cache.get(key)
    now = time.monotonic()
    if cached is not None and now - cached[0] < DISCOVERY_TTL_SECONDS:
        return cached[1]
    try:
        rows = await list_mcp_tools(server)
    except McpError:
        return {}
    mapping: dict[str, dict[str, Any]] = {}
    for item in rows:
        name = str(item.get("name", ""))
        if name:
            mapping[name[:MCP_TOOL_NAME_MAX]] = item
    _discovery_cache[key] = (now, mapping)
    return mapping


def _mcp_handler(server: McpServer, remote_name: str):
    async def handler(_context: ToolContext, arguments: BaseModel) -> str:
        try:
            return await call_mcp_tool(
                server, remote_name, arguments.model_dump(exclude_none=True)
            )
        except McpError as exc:
            raise ToolError(exc.code, exc.message) from None

    return handler


async def build_mcp_tool_specs(
    session: AsyncSession, refs: list[str]
) -> list[ToolSpec]:
    parsed_refs: list[tuple[str, UUID, str]] = []
    server_ids: list[UUID] = []
    for ref in dict.fromkeys(refs):
        parsed = parse_mcp_tool_ref(ref)
        if parsed is None:
            continue
        server_id, remote_name = parsed
        parsed_refs.append((ref, server_id, remote_name))
        if server_id not in server_ids:
            server_ids.append(server_id)
    if not parsed_refs:
        return []
    servers = {
        server.id: server
        for server in (
            await session.execute(
                select(McpServer).where(
                    McpServer.id.in_(server_ids),
                    McpServer.enabled.is_(True),
                )
            )
        ).scalars()
    }
    discovery: dict[UUID, dict[str, dict[str, Any]]] = {}
    for server_id in server_ids:
        server = servers.get(server_id)
        if server is not None:
            discovery[server_id] = await _discover_server(server)
    specs: list[ToolSpec] = []
    for ref, server_id, remote_name in parsed_refs:
        server = servers.get(server_id)
        if server is None:
            continue
        meta = discovery.get(server_id, {}).get(remote_name, {})
        schema = meta.get("input_schema")
        parameters = (
            schema
            if isinstance(schema, dict) and schema
            else {"type": "object", "additionalProperties": True}
        )
        description = str(meta.get("description") or "")
        specs.append(
            ToolSpec(
                name=ref,
                description=(
                    f"MCP tool {remote_name} on {server.name}"
                    + (f": {description}" if description else "")
                )[:500],
                args_model=McpToolArgs,
                handler=_mcp_handler(server, remote_name),
                parameters_schema_override=parameters,
            )
        )
    return specs


async def agent_tool_catalog(
    session: AsyncSession,
) -> dict[str, Any]:
    registry = build_tool_registry()
    builtin = []
    for name in SELECTABLE_BUILTIN_TOOLS:
        spec = registry.get(name)
        if spec is None:
            continue
        builtin.append(
            {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters_schema(),
            }
        )
    servers = list(
        (
            await session.execute(
                select(McpServer)
                .where(McpServer.enabled.is_(True))
                .order_by(McpServer.name)
            )
        ).scalars()
    )
    return {
        "builtin": builtin,
        "mcp_servers": [
            {
                "id": server.id,
                "name": server.name,
                "description": server.description,
            }
            for server in servers
        ],
    }


async def list_server_mcp_tools(
    session: AsyncSession, server_id: UUID
) -> list[dict[str, Any]]:
    server = await session.get(McpServer, server_id)
    if server is None or not server.enabled:
        raise AgentToolError("not_found", "MCP server not found")
    try:
        rows = await list_mcp_tools(server)
    except McpError as exc:
        raise AgentToolError(exc.code, exc.message) from None
    result: list[dict[str, Any]] = []
    for item in rows:
        name = str(item.get("name", ""))
        if not name:
            continue
        result.append(
            {
                "name": name[:MCP_TOOL_NAME_MAX],
                "description": str(item.get("description", ""))[:500],
                "input_schema": item.get("input_schema")
                if isinstance(item.get("input_schema"), dict)
                else {},
                "ref": format_mcp_tool(server.id, name[:MCP_TOOL_NAME_MAX]),
            }
        )
    return result


async def execute_agent_tool(
    session: AsyncSession,
    agent: CustomAgent,
    tool: str,
    arguments: dict[str, Any],
    *,
    workspace_id: UUID,
    user_id: UUID,
) -> dict[str, Any]:
    if tool not in agent.tools:
        raise AgentToolError("tool_not_allowed", "Tool is not enabled for this Agent")
    registry = build_tool_registry()
    if is_mcp_tool(tool):
        specs = await build_mcp_tool_specs(session, [tool])
        if not specs:
            raise AgentToolError("tool_not_found", "MCP tool is unavailable")
        registry = registry.with_tools(specs)
    kb_ids = [UUID(item) for item in agent.kb_ids if item]
    if not kb_ids and agent.default_kb_id is not None:
        kb_ids = [agent.default_kb_id]
    context = ToolContext(
        workspace_id=workspace_id,
        user_id=user_id,
        kb_id=kb_ids[0] if kb_ids else None,
        kb_ids=kb_ids or None,
        agent_id=agent.id,
    )
    started = time.perf_counter()
    result = await registry.execute(tool, arguments, context)
    return {
        "ok": result.ok,
        "output": result.output,
        "error_code": result.error_code,
        "error": result.error,
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }