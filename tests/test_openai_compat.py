import json

import httpx
import pytest


def _imports():
    from app.providers.base import ChatMessage, ProviderError, Usage
    from app.providers.openai_compat import OpenAICompatProvider

    return ChatMessage, ProviderError, Usage, OpenAICompatProvider


async def _collect(provider, messages, model="test-model"):
    return [chunk async for chunk in provider.stream_chat(messages, model)]


async def test_stream_parses_deltas_usage_and_finish():
    ChatMessage, _ProviderError, Usage, OpenAICompatProvider = _imports()
    body = (
        'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":2}}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body.encode(), headers={"content-type": "text/event-stream"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatProvider("p", "https://example.test/v1", "key", client=client)
        chunks = await _collect(provider, [ChatMessage(role="user", content="hi")])

    assert "".join(chunk.delta for chunk in chunks) == "Hello"
    assert chunks[2].finish_reason == "stop"
    assert chunks[3].usage == Usage(prompt_tokens=1, completion_tokens=2)


async def test_stream_sends_bearer_token_and_stream_flag():
    ChatMessage, _ProviderError, _Usage, OpenAICompatProvider = _imports()
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization")
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatProvider("p", "https://example.test/v1", "secret-key", client=client)
        await _collect(provider, [ChatMessage(role="user", content="hi")], model="m1")

    assert seen["authorization"] == "Bearer secret-key"
    payload = seen["payload"]
    assert payload["model"] == "m1"
    assert payload["stream"] is True
    assert payload["messages"] == [{"role": "user", "content": "hi"}]


async def test_stream_omits_authorization_without_api_key():
    ChatMessage, _ProviderError, _Usage, OpenAICompatProvider = _imports()
    seen: dict[str, bool] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["has_auth"] = "authorization" in request.headers
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatProvider("p", "https://example.test/v1", "", client=client)
        await _collect(provider, [ChatMessage(role="user", content="hi")])

    assert seen["has_auth"] is False


async def test_stream_raises_provider_error_on_http_failure():
    ChatMessage, ProviderError, _Usage, OpenAICompatProvider = _imports()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatProvider("p", "https://example.test/v1", "key", client=client)
        with pytest.raises(ProviderError) as excinfo:
            await _collect(provider, [ChatMessage(role="user", content="hi")])

    assert excinfo.value.code == "provider_http_error"


async def test_stream_raises_provider_error_when_unreachable():
    ChatMessage, ProviderError, _Usage, OpenAICompatProvider = _imports()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatProvider("p", "https://example.test/v1", "key", client=client)
        with pytest.raises(ProviderError) as excinfo:
            await _collect(provider, [ChatMessage(role="user", content="hi")])

    assert excinfo.value.code == "provider_unreachable"


async def test_stream_ignores_malformed_sse_lines():
    ChatMessage, _ProviderError, _Usage, OpenAICompatProvider = _imports()
    body = (
        "data: not-json\n\n"
        'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatProvider("p", "https://example.test/v1", "key", client=client)
        chunks = await _collect(provider, [ChatMessage(role="user", content="hi")])

    assert "".join(chunk.delta for chunk in chunks) == "ok"


async def test_list_models_parses_ids_and_provider():
    _ChatMessage, _ProviderError, _Usage, OpenAICompatProvider = _imports()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "m1"}, {"id": "m2"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatProvider("p", "https://example.test/v1", "key", client=client)
        models = await provider.list_models()

    assert [(model.id, model.provider_id) for model in models] == [("m1", "p"), ("m2", "p")]