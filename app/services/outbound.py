"""SSRF-safe outbound HTTP used by workflow HTTP/MCP nodes.

This intentionally mirrors the plugin outbound guard but keeps its own settings
so administrators can tune allowlists per capability.
"""

import asyncio
import socket
from urllib.parse import urlsplit

import httpx

from app.config import Settings, get_settings
from app.services.webhooks import _is_blocked_address, validate_url_shape


class OutboundError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _allowed_host(host: str, settings: Settings) -> bool:
    allowed = [
        item.strip().lower()
        for item in settings.http_node_allowed_hosts.split(",")
        if item.strip()
    ]
    if not allowed:
        return True
    lowered = host.lower()
    return any(lowered == item or lowered.endswith(f".{item}") for item in allowed)


async def validate_outbound_url(url: str, settings: Settings | None = None) -> None:
    current = settings or get_settings()
    try:
        validate_url_shape(url)
    except ValueError as exc:
        raise OutboundError("invalid_url", str(exc)) from None
    parsed = urlsplit(url)
    if current.app_env != "dev" and parsed.scheme != "https":
        raise OutboundError(
            "invalid_url", "Outbound endpoints must use HTTPS outside dev"
        )
    if not _allowed_host(parsed.hostname or "", current):
        raise OutboundError(
            "host_not_allowed", "Host is not in HTTP_NODE_ALLOWED_HOSTS"
        )
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo, parsed.hostname, port, 0, socket.SOCK_STREAM
        )
    except OSError:
        raise OutboundError("invalid_url", "Hostname cannot be resolved") from None
    if not addresses:
        raise OutboundError("invalid_url", "Hostname cannot be resolved")
    for address in addresses:
        host = str(address[4][0])
        if _is_blocked_address(host, current.http_node_allow_private_hosts):
            raise OutboundError(
                "invalid_url", "URL resolves to a private or reserved address"
            )


def _clean_headers(headers: dict[str, str]) -> dict[str, str]:
    blocked = {"host", "content-length", "transfer-encoding", "connection"}
    return {
        key: value
        for key, value in headers.items()
        if key.strip().lower() not in blocked
    }


async def request_outbound(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: str = "",
    timeout_seconds: float | None = None,
    max_chars: int | None = None,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    current = settings or get_settings()
    await validate_outbound_url(url, current)
    timeout = min(
        float(timeout_seconds or current.http_node_timeout_seconds),
        current.http_node_timeout_seconds,
    )
    limit = max_chars or current.http_node_max_response_chars
    request_headers = _clean_headers(headers or {})
    request_headers.setdefault("Accept", "application/json, text/plain, */*")
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        ) as client:
            if method.upper() == "GET":
                response = await client.get(url, headers=request_headers)
            else:
                response = await client.post(
                    url,
                    headers=request_headers,
                    content=body.encode("utf-8") if body else None,
                )
            chunks: list[bytes] = []
            total = 0
            byte_limit = limit * 4
            async for chunk in response.aiter_bytes():
                remaining = byte_limit - total
                if remaining <= 0:
                    break
                chunks.append(chunk[:remaining])
                total += min(len(chunk), remaining)
            text = b"".join(chunks).decode("utf-8", errors="replace")[:limit]
            if response.status_code >= 300:
                raise OutboundError(
                    "http_status", f"Endpoint returned HTTP {response.status_code}"
                )
            return text
    except OutboundError:
        raise
    except httpx.TimeoutException:
        raise OutboundError("http_timeout", "Outbound request timed out") from None
    except httpx.HTTPError as exc:
        raise OutboundError(
            "http_unreachable", f"Endpoint unreachable: {type(exc).__name__}"
        ) from None