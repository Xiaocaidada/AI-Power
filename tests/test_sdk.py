import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk" / "python"))

from ai_power_sdk import (  # noqa: E402
    AIPowerClient,
    AIPowerError,
    AsyncAIPowerClient,
    SSEEvent,
)
from ai_power_sdk.sse import iter_sse  # noqa: E402

SSE_BODY = (
    "event: meta\n"
    'data: {"message_id":"m1"}\n'
    "\n"
    "event: delta\n"
    'data: {"text":"Hel"}\n'
    "\n"
    "event: done\n"
    'data: {"usage":{"prompt_tokens":1}}\n'
    "\n"
)


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/auth/login":
        return httpx.Response(
            200,
            json={
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 1800,
            },
        )
    if request.url.path == "/models":
        assert request.headers["authorization"] == "Bearer access-1"
        return httpx.Response(200, json=[{"id": "fake", "provider_id": "fake"}])
    if request.url.path == "/conversations/c1/messages":
        return httpx.Response(
            200,
            text=SSE_BODY,
            headers={"content-type": "text/event-stream"},
        )
    if request.url.path == "/missing":
        return httpx.Response(
            404,
            json={"detail": {"code": "not_found", "message": "nope"}},
            headers={"x-request-id": "req-1"},
        )
    return httpx.Response(404, json={"detail": "unknown"})


def test_sync_login_models_and_sse_stream():
    client = AIPowerClient("http://test", transport=httpx.MockTransport(_handler))
    login = client.login("a@example.com", "secret")
    assert login["access_token"] == "access-1"
    assert client.models() == [{"id": "fake", "provider_id": "fake"}]

    events = list(client.chat_stream("c1", "hello"))

    assert [event.event for event in events] == ["meta", "delta", "done"]
    assert events[1].json() == {"text": "Hel"}
    client.close()


def test_sync_error_mapping_includes_code_and_request_id():
    client = AIPowerClient("http://test", access_token="a", transport=httpx.MockTransport(_handler))

    with pytest.raises(AIPowerError) as excinfo:
        client._request("GET", "/missing")

    assert excinfo.value.status_code == 404
    assert excinfo.value.code == "not_found"
    assert excinfo.value.request_id == "req-1"
    assert "not_found" in str(excinfo.value)
    client.close()


def test_api_key_mode_sends_x_api_key():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["api_key"] = request.headers.get("x-api-key", "")
        return httpx.Response(200, json=[])

    client = AIPowerClient("http://test", api_key="ap_test", transport=httpx.MockTransport(handler))
    client.models()
    assert seen["api_key"] == "ap_test"
    client.close()


def test_get_retries_429_with_retry_after():
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, json=[])

    client = AIPowerClient("http://test", transport=httpx.MockTransport(handler))
    assert client.models() == []
    assert calls["count"] == 2
    client.close()


def _run_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/workflows/w1/runs" and request.method == "POST":
        return httpx.Response(202, json={"run_id": "r1", "status": "queued"})
    if request.url.path == "/workflows/runs/r1/events":
        assert request.url.params["after"] == "0"
        return httpx.Response(
            200,
            text=(
                "id: 1\n"
                "event: workflow_start\n"
                'data: {"run_id":"r1"}\n'
                "\n"
                "id: 2\n"
                "event: workflow_end\n"
                'data: {"run_id":"r1","status":"completed"}\n'
                "\n"
            ),
            headers={"content-type": "text/event-stream"},
        )
    if request.url.path == "/workflows/runs/r1/cancel":
        return httpx.Response(200, json={"run_id": "r1", "status": "cancelled"})
    return httpx.Response(404, json={"detail": "unknown"})


def test_sync_workflow_run_queues_then_streams_events():
    client = AIPowerClient(
        "http://test", access_token="a", transport=httpx.MockTransport(_run_handler)
    )

    events = list(client.workflow_run("w1", "hello"))

    assert [event.event for event in events] == ["workflow_start", "workflow_end"]
    assert events[-1].json()["status"] == "completed"
    started = client.start_workflow_run("w1", "hello")
    assert started["run_id"] == "r1"
    assert client.cancel_workflow_run("r1")["status"] == "cancelled"
    client.close()


def test_sse_parser_supports_comments_and_multiline_data():
    events = list(iter_sse([": keepalive", "event: x", "data: a", "data: b", ""]))
    assert events == [SSEEvent(event="x", data="a\nb")]


async def test_async_workflow_run_queues_then_streams_events():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/workflows/w1/runs":
            return httpx.Response(202, json={"run_id": "r1", "status": "queued"})
        if request.url.path == "/workflows/runs/r1/events":
            return httpx.Response(
                200,
                text=(
                    "event: workflow_start\n"
                    'data: {"run_id":"r1"}\n'
                    "\n"
                    "event: workflow_end\n"
                    'data: {"run_id":"r1","status":"completed"}\n'
                    "\n"
                ),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(404, json={"detail": "unknown"})

    client = AsyncAIPowerClient(
        "http://test", access_token="a", transport=httpx.MockTransport(handler)
    )
    events = [event async for event in client.workflow_run("w1", "hello")]
    assert [event.event for event in events] == ["workflow_start", "workflow_end"]
    assert (await client.start_workflow_run("w1", "hello"))["run_id"] == "r1"
    await client.aclose()


async def test_async_login_and_stream():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/login":
            return httpx.Response(
                200, json={"access_token": "access-1", "refresh_token": "refresh-1"}
            )
        if request.url.path == "/conversations/c1/messages":
            return httpx.Response(200, text=SSE_BODY, headers={"content-type": "text/event-stream"})
        return httpx.Response(404, json={"detail": "unknown"})

    client = AsyncAIPowerClient("http://test", transport=httpx.MockTransport(handler))
    await client.login("a@example.com", "secret")
    events = [event async for event in client.chat_stream("c1", "hello")]
    assert [event.event for event in events] == ["meta", "delta", "done"]
    await client.aclose()
