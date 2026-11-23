"""Minimal MCP client over streamable HTTP (JSON-RPC 2.0).

Only the operations needed by the workflow engine and admin tool discovery are
implemented: initialize, tools/list and tools/call. The transport reuses the
SSRF-safe outbound guards.
"""

import json
import logging
import time
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.models import McpServer
from app.services.outbound import OutboundError, validate_outbound_url
from app.services.provider_secrets import decrypt_api_key

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2025-03-26"
MCP_CLIENT_NAME = "ai-power"
MAX_TOOL_PAGES = 5
MAX_TOOLS = 100


class McpError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _auth_headers(server: McpServer) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if not server.auth_token_encrypted:
        return headers
    try:
        token = decrypt_api_key(server.auth_token_encrypted)
    except ValueError:
        raise McpError("mcp_auth_invalid", "MCP credential is invalid") from None
    headers["Authorization"] = f"Bearer {token}"
    return headers


def _parse_sse(text: str, request_id: int) -> dict[str, Any] | None:
    events: list[str] = []
    buffer: list[str] = []
    for line in text.splitlines():
        if line.strip() == "":
            if buffer:
                events.append("\n".join(buffer))
                buffer = []
            continue
        if line.startswith("data:"):
            buffer.append(line[5:].lstrip())
    if buffer:
        events.append("\n".join(buffer))
    match: dict[str, Any] | None = None
    for event in events:
        try:
            payload = json.loads(event)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("id") == request_id:
            match = payload
    return match


async def _rpc(
    server: McpServer,
    payload: dict[str, Any],
    *,
    settings: Settings,
    session_id: str | None = None,
    timeout_seconds: float | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[dict[str, Any], str | None]:
    try:
        await validate_outbound_url(server.endpoint_url, settings)
    except OutboundError as exc:
        raise McpError(exc.code, exc.message) from None
    headers = _auth_headers(server)
    headers["Accept"] = "application/json, text/event-stream"
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    timeout = min(
        float(timeout_seconds or server.timeout_seconds or settings.mcp_timeout_seconds),
        settings.mcp_timeout_seconds,
    )
    limit = settings.mcp_max_response_chars * 4
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            response = await client.post(
                server.endpoint_url,
                headers=headers,
                content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )
            next_session = response.headers.get("mcp-session-id", session_id)
            if response.status_code == 202:
                return {}, next_session
            if response.status_code >= 300:
                raise McpError(
                    "mcp_http_error",
                    f"MCP server returned HTTP {response.status_code}",
                )
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                if len(raw) + len(chunk) > limit:
                    raise McpError("mcp_response_too_large", "MCP response is too large")
                raw.extend(chunk)
            text = raw.decode("utf-8", errors="replace")
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                parsed = _parse_sse(text, int(payload.get("id", 0)))
                if parsed is None:
                    raise McpError("mcp_invalid_response", "MCP stream returned no result")
                return parsed, next_session
            try:
                parsed_json = json.loads(text)
            except json.JSONDecodeError:
                raise McpError(
                    "mcp_invalid_response", "MCP server returned invalid JSON"
                ) from None
            if not isinstance(parsed_json, dict):
                raise McpError("mcp_invalid_response", "MCP response must be an object")
            return parsed_json, next_session
    except McpError:
        raise
    except httpx.TimeoutException:
        raise McpError("mcp_timeout", "MCP request timed out") from None
    except httpx.HTTPError as exc:
        raise McpError(
            "mcp_unreachable", f"MCP server unreachable: {type(exc).__name__}"
        ) from None


async def _initialize(
    server: McpServer,
    *,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None,
) -> str | None:
    response, session_id = await _rpc(
        server,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": MCP_CLIENT_NAME, "version": "1.0"},
            },
        },
        settings=settings,
        transport=transport,
    )
    _raise_rpc_error(response)
    # Best-effort initialized notification; some servers answer 202.
    try:
        await _rpc(
            server,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            settings=settings,
            session_id=session_id,
            transport=transport,
        )
    except McpError:
        logger.debug("MCP initialized notification failed", exc_info=True)
    return session_id


def _raise_rpc_error(response: dict[str, Any]) -> None:
    error = response.get("error")
    if isinstance(error, dict):
        code = str(error.get("code", "mcp_error"))
        message = str(error.get("message") or "MCP request failed")
        raise McpError(code, message)


async def list_mcp_tools(
    server: McpServer,
    *,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    current = settings or get_settings()
    session_id = await _initialize(server, settings=current, transport=transport)
    tools: list[dict[str, Any]] = []
    cursor: str | None = None
    request_id = 2
    for _ in range(MAX_TOOL_PAGES):
        params: dict[str, Any] = {}
        if cursor:
            params["cursor"] = cursor
        response, session_id = await _rpc(
            server,
            {"jsonrpc": "2.0", "id": request_id, "method": "tools/list", "params": params},
            settings=current,
            session_id=session_id,
            transport=transport,
        )
        request_id += 1
        _raise_rpc_error(response)
        result = response.get("result")
        if not isinstance(result, dict):
            raise McpError("mcp_invalid_response", "MCP tools/list returned no result")
        page = result.get("tools")
        if isinstance(page, list):
            for item in page:
                if not isinstance(item, dict):
                    continue
                tools.append(
                    {
                        "name": str(item.get("name", ""))[:120],
                        "description": str(item.get("description", ""))[:500],
                        "input_schema": item.get("inputSchema")
                        if isinstance(item.get("inputSchema"), dict)
                        else {},
                    }
                )
                if len(tools) >= MAX_TOOLS:
                    return tools
        cursor = result.get("nextCursor")
        if not isinstance(cursor, str) or not cursor:
            break
    return tools


async def list_mcp_resources(
    server: McpServer,
    *,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    current = settings or get_settings()
    session_id = await _initialize(server, settings=current, transport=transport)
    resources: list[dict[str, Any]] = []
    cursor: str | None = None
    request_id = 2
    for _ in range(MAX_TOOL_PAGES):
        params: dict[str, Any] = {}
        if cursor:
            params["cursor"] = cursor
        response, session_id = await _rpc(
            server,
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "resources/list",
                "params": params,
            },
            settings=current,
            session_id=session_id,
            transport=transport,
        )
        request_id += 1
        _raise_rpc_error(response)
        result = response.get("result")
        if not isinstance(result, dict):
            raise McpError("mcp_invalid_response", "MCP resources/list returned no result")
        page = result.get("resources")
        if isinstance(page, list):
            for item in page:
                if not isinstance(item, dict):
                    continue
                resources.append(
                    {
                        "uri": str(item.get("uri", ""))[:2000],
                        "name": str(item.get("name", ""))[:120],
                        "description": str(item.get("description", ""))[:500],
                        "mime_type": str(item.get("mimeType", ""))[:120],
                    }
                )
                if len(resources) >= MAX_TOOLS:
                    return resources
        cursor = result.get("nextCursor")
        if not isinstance(cursor, str) or not cursor:
            break
    return resources


async def read_mcp_resource(
    server: McpServer,
    uri: str,
    *,
    timeout_seconds: float | None = None,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    current = settings or get_settings()
    session_id = await _initialize(server, settings=current, transport=transport)
    response, _ = await _rpc(
        server,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "resources/read",
            "params": {"uri": uri},
        },
        settings=current,
        session_id=session_id,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    _raise_rpc_error(response)
    result = response.get("result")
    if not isinstance(result, dict):
        raise McpError("mcp_invalid_response", "MCP resources/read returned no result")
    contents = result.get("contents")
    parts: list[str] = []
    if isinstance(contents, list):
        for item in contents:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("text"), str):
                parts.append(str(item["text"]))
            elif item.get("blob"):
                parts.append(f"[binary resource {item.get('mimeType', 'unknown')}]")
    text = "\n".join(part for part in parts if part).strip()
    if not text:
        text = json.dumps(result, ensure_ascii=False)
    return text[: current.mcp_max_response_chars]


async def list_mcp_prompts(
    server: McpServer,
    *,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    current = settings or get_settings()
    session_id = await _initialize(server, settings=current, transport=transport)
    prompts: list[dict[str, Any]] = []
    cursor: str | None = None
    request_id = 2
    for _ in range(MAX_TOOL_PAGES):
        params: dict[str, Any] = {}
        if cursor:
            params["cursor"] = cursor
        response, session_id = await _rpc(
            server,
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "prompts/list",
                "params": params,
            },
            settings=current,
            session_id=session_id,
            transport=transport,
        )
        request_id += 1
        _raise_rpc_error(response)
        result = response.get("result")
        if not isinstance(result, dict):
            raise McpError("mcp_invalid_response", "MCP prompts/list returned no result")
        page = result.get("prompts")
        if isinstance(page, list):
            for item in page:
                if not isinstance(item, dict):
                    continue
                arguments = item.get("arguments")
                prompts.append(
                    {
                        "name": str(item.get("name", ""))[:120],
                        "description": str(item.get("description", ""))[:500],
                        "arguments": arguments if isinstance(arguments, list) else [],
                    }
                )
                if len(prompts) >= MAX_TOOLS:
                    return prompts
        cursor = result.get("nextCursor")
        if not isinstance(cursor, str) or not cursor:
            break
    return prompts


async def get_mcp_prompt(
    server: McpServer,
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    timeout_seconds: float | None = None,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    current = settings or get_settings()
    session_id = await _initialize(server, settings=current, transport=transport)
    response, _ = await _rpc(
        server,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "prompts/get",
            "params": {"name": name, "arguments": arguments or {}},
        },
        settings=current,
        session_id=session_id,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    _raise_rpc_error(response)
    result = response.get("result")
    if not isinstance(result, dict):
        raise McpError("mcp_invalid_response", "MCP prompts/get returned no result")
    messages = result.get("messages")
    parts: list[str] = []
    if isinstance(messages, list):
        for item in messages:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, dict) and content.get("type") == "text":
                parts.append(str(content.get("text", "")))
            elif isinstance(content, str):
                parts.append(content)
    text = "\n".join(part for part in parts if part).strip()
    if not text:
        text = json.dumps(result, ensure_ascii=False)
    return text[: current.mcp_max_response_chars]


async def call_mcp_tool(
    server: McpServer,
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    timeout_seconds: float | None = None,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    current = settings or get_settings()
    session_id = await _initialize(server, settings=current, transport=transport)
    response, _ = await _rpc(
        server,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
        },
        settings=current,
        session_id=session_id,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )
    _raise_rpc_error(response)
    result = response.get("result")
    if not isinstance(result, dict):
        raise McpError("mcp_invalid_response", "MCP tools/call returned no result")
    parts: list[str] = []
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
    text = "\n".join(part for part in parts if part).strip()
    if result.get("isError") is True:
        raise McpError("mcp_tool_error", text or "MCP tool reported an error")
    if not text:
        text = json.dumps(result, ensure_ascii=False)
    return text[: current.mcp_max_response_chars]


def mcp_latency_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
