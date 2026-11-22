import json

import httpx
import pytest

from app.config import Settings
from app.providers.base import ProviderError


async def test_reranker_posts_openai_compatible_payload_and_sorts_results():
    from app.providers.rerank import HttpReranker, RerankResult

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 1, "relevance_score": 0.2},
                    {"index": 0, "relevance_score": 0.9},
                ]
            },
        )

    reranker = HttpReranker(
        base_url="http://rerank.local/v1",
        model="bge-reranker-v2-m3",
        timeout=5.0,
        transport=httpx.MockTransport(handler),
    )

    results = await reranker.rerank("退款多久到账", ["错误段落", "正确段落"], top_n=2)

    assert captured["url"] == "http://rerank.local/v1/rerank"
    assert captured["json"] == {
        "model": "bge-reranker-v2-m3",
        "query": "退款多久到账",
        "documents": ["错误段落", "正确段落"],
        "top_n": 2,
    }
    assert results == [
        RerankResult(index=0, score=0.9),
        RerankResult(index=1, score=0.2),
    ]


async def test_reranker_sends_api_key_header_without_logging_it():
    from app.providers.rerank import HttpReranker

    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 1.0}]})

    reranker = HttpReranker(
        base_url="http://rerank.local",
        model="rerank",
        timeout=5.0,
        api_key="secret-token",
        transport=httpx.MockTransport(handler),
    )

    await reranker.rerank("q", ["a"])

    assert seen["authorization"] == "Bearer secret-token"


async def test_reranker_raises_typed_error_on_http_failure():
    from app.providers.rerank import HttpReranker

    reranker = HttpReranker(
        base_url="http://rerank.local",
        model="rerank",
        timeout=5.0,
        transport=httpx.MockTransport(lambda _request: httpx.Response(503, text="down")),
    )

    with pytest.raises(ProviderError) as excinfo:
        await reranker.rerank("q", ["a"])

    assert excinfo.value.code == "rerank_http_error"


async def test_reranker_rejects_malformed_results():
    from app.providers.rerank import HttpReranker

    reranker = HttpReranker(
        base_url="http://rerank.local",
        model="rerank",
        timeout=5.0,
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200, json={"results": [{"index": 9, "relevance_score": 0.5}]}
            )
        ),
    )

    with pytest.raises(ProviderError) as excinfo:
        await reranker.rerank("q", ["a"])

    assert excinfo.value.code == "rerank_bad_response"


def test_build_reranker_respects_settings_toggle():
    from app.providers.rerank import HttpReranker, build_reranker

    enabled = Settings(
        rerank_enabled=True,
        rerank_base_url="http://rerank.local/v1",
        rerank_model="bge-reranker-v2-m3",
    )
    disabled = Settings(rerank_enabled=False, rerank_base_url="http://rerank.local/v1")

    assert isinstance(build_reranker(enabled), HttpReranker)
    assert build_reranker(disabled) is None
