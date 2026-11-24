import json
from types import SimpleNamespace

import httpx
import pytest

from app.services.provider_secrets import encrypt_api_key
from app.services.web_search import (
    WebResult,
    WebSearchError,
    generate_search_queries,
    search_web,
)


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        event = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data = json.loads(
            next(line[len("data: ") :] for line in lines if line.startswith("data: "))
        )
        events.append((event, data))
    return events


def _config(provider: str, *, base_url: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        provider=provider,
        base_url=base_url,
        api_key_encrypted=encrypt_api_key("test-key") if provider != "searxng" else "",
        max_results=3,
        timeout_seconds=5,
    )


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_tavily_adapter_parses_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        body = json.loads(request.content)
        assert body["api_key"] == "test-key"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Example",
                        "url": "https://www.example.com/a",
                        "content": "First result",
                        "published_date": "2026-01-01",
                    }
                ]
            },
        )

    async with _mock_client(handler) as client:
        results = await search_web(_config("tavily"), "AI", client=client)

    assert results == [
        WebResult(
            title="Example",
            url="https://www.example.com/a",
            site="example.com",
            snippet="First result",
            published_at="2026-01-01",
        )
    ]


async def test_brave_adapter_parses_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Subscription-Token"] == "test-key"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Brave result",
                            "url": "https://news.example.org/x",
                            "description": "Snippet",
                            "page_age": "2 days ago",
                        }
                    ]
                }
            },
        )

    async with _mock_client(handler) as client:
        results = await search_web(_config("brave"), "AI", client=client)

    assert results[0].title == "Brave result"
    assert results[0].site == "news.example.org"
    assert results[0].published_at == "2 days ago"


async def test_serper_adapter_parses_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-KEY"] == "test-key"
        return httpx.Response(
            200,
            json={
                "organic": [
                    {
                        "title": "Serper",
                        "link": "https://serper.example/page",
                        "snippet": "Snippet",
                        "date": "Jan 1, 2026",
                    }
                ]
            },
        )

    async with _mock_client(handler) as client:
        results = await search_web(_config("serper"), "AI", client=client)

    assert results[0].url == "https://serper.example/page"


async def test_searxng_adapter_uses_json_search():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["format"] == "json"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "SearXNG",
                        "url": "https://searx.example/r",
                        "content": "Snippet",
                        "publishedDate": "2026-02-02",
                    }
                ]
            },
        )

    async with _mock_client(handler) as client:
        results = await search_web(
            _config("searxng", base_url="https://searx.example"),
            "AI",
            client=client,
        )

    assert results[0].title == "SearXNG"


async def test_search_adapter_maps_auth_errors():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    async with _mock_client(handler) as client:
        with pytest.raises(WebSearchError) as exc:
            await search_web(_config("tavily"), "AI", client=client)

    assert exc.value.code == "search_auth_failed"


def test_generate_search_queries_dedupes_and_strips_prefix():
    queries = generate_search_queries("帮我搜索 北京天气\n北京天气", max_queries=3)

    assert queries == ["北京天气"]


async def _create_provider(client, headers, **overrides):
    body = {
        "provider": "tavily",
        "name": "Tavily",
        "api_key": "tvly-secret",
        **overrides,
    }
    return await client.post("/search-providers", json=body, headers=headers)


async def test_search_provider_crud_masks_key_and_sets_default(client, api):
    alice = await api.headers("p12-s2-crud@example.com")

    created = await _create_provider(client, alice)
    assert created.status_code == 201
    body = created.json()
    assert body["api_key_hint"] == "••••cret"
    assert "tvly-secret" not in created.text
    assert body["is_default"] is True
    assert body["owned"] is True

    listed = await client.get("/search-providers", headers=alice)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == body["id"]

    patched = await client.patch(
        f"/search-providers/{body['id']}",
        json={"max_results": 8, "name": "Tavily 8"},
        headers=alice,
    )
    assert patched.status_code == 200
    assert patched.json()["max_results"] == 8
    assert patched.json()["name"] == "Tavily 8"

    deleted = await client.delete(f"/search-providers/{body['id']}", headers=alice)
    assert deleted.status_code == 204
    assert (await client.get("/search-providers", headers=alice)).json() == []


async def test_search_provider_requires_key_except_searxng(client, api):
    headers = await api.headers("p12-s2-key@example.com")

    missing = await _create_provider(client, headers, api_key="")
    searx = await _create_provider(
        client,
        headers,
        provider="searxng",
        name="Local",
        api_key="",
        base_url="https://search.example",
    )

    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "api_key_required"
    assert searx.status_code == 201


async def test_search_provider_cross_user_isolation(client, api):
    alice = await api.headers("p12-s2-alice@example.com")
    bob = await api.headers("p12-s2-bob@example.com")
    created = await _create_provider(client, alice)

    listed = await client.get("/search-providers", headers=bob)
    patched = await client.patch(
        f"/search-providers/{created.json()['id']}",
        json={"name": "hijack"},
        headers=bob,
    )
    tested = await client.post(f"/search-providers/{created.json()['id']}/test", headers=bob)

    assert listed.json() == []
    assert patched.status_code == 404
    assert tested.status_code == 404


async def test_search_provider_test_connection(client, api, monkeypatch):
    headers = await api.headers("p12-s2-test@example.com")
    created = await _create_provider(client, headers)

    async def fake_search(config, query, **kwargs):
        return [WebResult("A", "https://a.example", "a.example", "s")]

    monkeypatch.setattr("app.services.search_providers.search_web", fake_search)
    response = await client.post(f"/search-providers/{created.json()['id']}/test", headers=headers)

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["result_count"] == 1


async def test_web_search_mode_without_provider_returns_typed_error(client, api, registry):
    headers = await api.headers("p12-s2-none@example.com")
    created = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model", "mode": "web_search"},
        headers=headers,
    )

    response = await client.post(
        f"/conversations/{created.json()['id']}/messages",
        json={"content": "今天有什么新闻"},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "search_not_configured"


async def test_web_search_streams_sources_and_persists_them(client, api, registry, monkeypatch):
    headers = await api.headers("p12-s2-chat@example.com")
    provider = await _create_provider(client, headers)
    created = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model", "mode": "web_search"},
        headers=headers,
    )

    async def fake_search(config, query, **kwargs):
        assert config.id is not None
        return [
            WebResult(
                title="Source one",
                url="https://one.example/a",
                site="one.example",
                snippet="First",
                published_at="2026-01-01",
            ),
            WebResult(
                title="Source two",
                url="https://two.example/b",
                site="two.example",
                snippet="Second",
            ),
        ]

    monkeypatch.setattr("app.routers.conversations.search_multi", fake_search)
    response = await client.post(
        f"/conversations/{created.json()['id']}/messages",
        json={
            "content": "帮我搜索 AI 新闻",
            "mode_meta": {
                "thinking_level": "standard",
                "search_provider_id": provider.json()["id"],
            },
        },
        headers=headers,
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    names = [event for event, _ in events]
    assert names[0] == "meta"
    assert names[1] == "stage"
    assert events[1][1]["stage"] == "searching"
    assert [data["title"] for event, data in events if event == "web_source"] == [
        "Source one",
        "Source two",
    ]
    assert "answering" in [data["stage"] for event, data in events if event == "stage"]
    assert "".join(data["text"] for event, data in events if event == "delta") == "Hello"
    assert events[0][1]["mode"] == "web_search"
    assert events[0][1]["mode_meta"]["search_provider_id"] == provider.json()["id"]

    detail = await client.get(f"/conversations/{created.json()['id']}", headers=headers)
    assistant = detail.json()["messages"][1]
    assert assistant["mode"] == "web_search"
    assert [item["title"] for item in assistant["web_sources"]] == [
        "Source one",
        "Source two",
    ]
    assert assistant["web_sources"][0]["provider"] == "tavily"


async def test_web_search_unexpected_error_emits_terminal_error(client, api, registry, monkeypatch):
    headers = await api.headers("p12-s2-internal@example.com")
    await _create_provider(client, headers)
    created = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model", "mode": "web_search"},
        headers=headers,
    )

    async def broken_search(config, query, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.routers.conversations.search_multi", broken_search)
    response = await client.post(
        f"/conversations/{created.json()['id']}/messages",
        json={"content": "AI"},
        headers=headers,
    )

    events = _parse_sse(response.text)
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "internal_error"


async def test_web_search_failure_emits_terminal_error(client, api, registry, monkeypatch):
    headers = await api.headers("p12-s2-fail@example.com")
    await _create_provider(client, headers)
    created = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model", "mode": "web_search"},
        headers=headers,
    )

    async def failing_search(config, query, **kwargs):
        raise WebSearchError("search_timeout", "Search provider timed out")

    monkeypatch.setattr("app.routers.conversations.search_multi", failing_search)
    response = await client.post(
        f"/conversations/{created.json()['id']}/messages",
        json={"content": "AI"},
        headers=headers,
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert [event for event, _ in events] == [
        "meta",
        "stage",
        "stage",
        "error",
    ]
    assert events[-1][1]["code"] == "search_timeout"
    detail = await client.get(f"/conversations/{created.json()['id']}", headers=headers)
    assistant = detail.json()["messages"][1]
    assert assistant["status"] == "failed"
    assert assistant["web_sources"] == []
