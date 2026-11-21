import json

import httpx
import pytest


def _imports():
    from app.providers.base import ProviderError
    from app.providers.embedding import OpenAICompatEmbeddingProvider

    return ProviderError, OpenAICompatEmbeddingProvider


async def test_embed_returns_vectors_in_index_order():
    _ProviderError, OpenAICompatEmbeddingProvider = _imports()
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0, 1, 0, 0]},
                    {"index": 0, "embedding": [1, 0, 0, 0]},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatEmbeddingProvider(
            "https://example.test/v1",
            "key",
            model="bge-m3",
            dimensions=4,
            client=client,
        )
        vectors = await provider.embed(["a", "b"])

    assert vectors == [[1, 0, 0, 0], [0, 1, 0, 0]]
    assert seen["payload"] == {"model": "bge-m3", "input": ["a", "b"]}


async def test_embed_rejects_dimension_mismatch():
    ProviderError, OpenAICompatEmbeddingProvider = _imports()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1, 0]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatEmbeddingProvider(
            "https://example.test/v1", dimensions=4, client=client
        )
        with pytest.raises(ProviderError) as excinfo:
            await provider.embed(["a"])

    assert excinfo.value.code == "embedding_bad_response"


async def test_embed_raises_on_http_error():
    ProviderError, OpenAICompatEmbeddingProvider = _imports()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatEmbeddingProvider("https://example.test/v1", client=client)
        with pytest.raises(ProviderError) as excinfo:
            await provider.embed(["a"])

    assert excinfo.value.code == "embedding_http_error"


async def test_embed_raises_when_unreachable():
    ProviderError, OpenAICompatEmbeddingProvider = _imports()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatEmbeddingProvider("https://example.test/v1", client=client)
        with pytest.raises(ProviderError) as excinfo:
            await provider.embed(["a"])

    assert excinfo.value.code == "embedding_unreachable"


async def test_embed_rejects_missing_data():
    ProviderError, OpenAICompatEmbeddingProvider = _imports()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"object": "list"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenAICompatEmbeddingProvider("https://example.test/v1", client=client)
        with pytest.raises(ProviderError) as excinfo:
            await provider.embed(["a"])

    assert excinfo.value.code == "embedding_bad_response"
