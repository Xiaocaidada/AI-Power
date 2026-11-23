from types import SimpleNamespace

import pytest


@pytest.fixture
def quota_settings(monkeypatch):
    import app.services.quotas as quotas

    settings = SimpleNamespace(
        quota_free_requests_per_minute=100,
        quota_free_tokens_per_day=1_000_000,
        quota_free_max_keys=5,
        quota_pro_requests_per_minute=100,
        quota_pro_tokens_per_day=1_000_000,
        quota_pro_max_keys=5,
        quota_free_daily_cost_usd=1,
        quota_pro_daily_cost_usd=50,
        quota_free_max_kbs=10,
        quota_pro_max_kbs=100,
        quota_free_max_documents_per_kb=200,
        quota_pro_max_documents_per_kb=5000,
        quota_free_max_kb_bytes=100_000_000,
        quota_pro_max_kb_bytes=10_000_000_000,
        quota_free_max_memories=500,
        quota_pro_max_memories=10_000,
    )
    monkeypatch.setattr(quotas, "get_settings", lambda: settings)
    return settings


async def _conversation(client, headers):
    return await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model", "kb_id": None},
        headers=headers,
    )


async def _send(client, headers, conversation_id):
    return await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "hello"},
        headers=headers,
    )


async def test_workspace_request_quota_returns_429_with_headers(
    client, api, registry, quota_settings
):
    quota_settings.quota_free_requests_per_minute = 2
    headers = await api.headers("quota-req@example.com")
    conversation = await _conversation(client, headers)

    first = await _send(client, headers, conversation.json()["id"])
    second = await _send(client, headers, conversation.json()["id"])
    third = await _send(client, headers, conversation.json()["id"])

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    detail = third.json()["detail"]
    assert detail["code"] == "quota_exceeded"
    assert detail["scope"] == "workspace"
    assert detail["metric"] == "requests_per_minute"
    assert third.headers["x-quota-limit"] == "2"
    assert third.headers["x-quota-scope"] == "workspace"
    assert int(third.headers["retry-after"]) > 0


async def test_daily_token_quota_blocks_further_messages(client, api, registry, quota_settings):
    quota_settings.quota_free_tokens_per_day = 1
    headers = await api.headers("quota-tokens@example.com")
    conversation = await _conversation(client, headers)

    first = await _send(client, headers, conversation.json()["id"])
    second = await _send(client, headers, conversation.json()["id"])

    assert first.status_code == 200
    assert second.status_code == 429
    detail = second.json()["detail"]
    assert detail["scope"] == "workspace"
    assert detail["metric"] == "tokens_per_day"


async def test_api_key_rate_limit_applies_per_key(client, api, registry, quota_settings):
    headers = await api.headers("quota-key@example.com")
    conversation = await _conversation(client, headers)
    created = await client.post(
        "/api-keys",
        json={"name": "limited", "rate_limit_per_minute": 1},
        headers=headers,
    )
    key_headers = {"X-API-Key": created.json()["key"]}

    first = await _send(client, key_headers, conversation.json()["id"])
    second = await _send(client, key_headers, conversation.json()["id"])

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"]["scope"] == "api_key"


async def test_quota_summary_reports_limits_and_usage(client, api, registry, quota_settings):
    headers = await api.headers("quota-summary@example.com")
    conversation = await _conversation(client, headers)
    await _send(client, headers, conversation.json()["id"])

    response = await client.get("/usage/quota", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == "free"
    assert body["requests"]["limit"] == 100
    assert body["requests"]["used"] == 1
    assert body["requests"]["remaining"] == 99
    assert body["tokens"]["used"] == 3
    assert body["tokens"]["remaining"] == 999_997
    assert body["requests"]["reset_seconds"] > 0
    assert body["max_keys"] == 5
    assert body["active_keys"] == 0


async def test_workspace_key_limit_blocks_creation(client, api, quota_settings):
    quota_settings.quota_free_max_keys = 1
    headers = await api.headers("quota-keys-max@example.com")

    first = await client.post("/api-keys", json={"name": "one"}, headers=headers)
    second = await client.post("/api-keys", json={"name": "two"}, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 429
    assert second.json()["detail"]["metric"] == "api_keys"


async def test_expired_key_is_rejected(client, api):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import ApiKey

    headers = await api.headers("quota-expired@example.com")
    created = await client.post("/api-keys", json={"name": "short"}, headers=headers)
    async with SessionLocal() as session:
        stored = (
            await session.execute(select(ApiKey).where(ApiKey.prefix == created.json()["prefix"]))
        ).scalar_one()
        stored.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()

    response = await client.get("/knowledge-bases", headers={"X-API-Key": created.json()["key"]})

    assert response.status_code == 401
