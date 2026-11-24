import json
from uuid import UUID

from app.config import get_settings
from app.db import SessionLocal
from app.models import AgentMemory
from app.services.memory_semantic import detect_semantic_contradictions


async def _memory(client, headers, *, title: str, content: str, category="technical"):
    response = await client.post(
        "/memories",
        json={
            "title": title,
            "content": content,
            "category": category,
            "scope_type": "global",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _enable_memory(client, headers):
    response = await client.patch(
        "/memories/settings",
        json={"enabled": True, "auto_extract": True, "require_confirmation": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def _contradiction_payload():
    return json.dumps(
        [
            {
                "pair_id": "0",
                "contradicts": True,
                "confidence": 0.92,
                "reason": "One memory says PostgreSQL, the other says MongoDB.",
            }
        ]
    )


async def test_semantic_contradiction_creates_deduplicated_suggestion(
    client, api, registry
):
    headers = await api.headers("p11s9-semantic@example.com")
    first = await _memory(
        client,
        headers,
        title="Primary database",
        content="The project uses PostgreSQL for durable storage.",
    )
    second = await _memory(
        client,
        headers,
        title="Primary database choice",
        content="The project uses MongoDB for durable storage.",
    )
    await _enable_memory(client, headers)
    registry.get("fake").complete_content = _contradiction_payload()

    async with SessionLocal() as session:
        memory = await session.get(AgentMemory, UUID(first["id"]))
        assert memory is not None
        workspace_id, user_id = memory.workspace_id, memory.user_id
        result = await detect_semantic_contradictions(
            session,
            workspace_id,
            user_id,
            provider_id="fake",
            model="fake-model",
            registry=registry,
            settings=get_settings(),
        )
        created = [
            (row.kind, dict(row.payload), list(row.memory_ids))
            for row in result["suggestions"]
        ]
        await session.commit()

    assert result["pairs_checked"] == 1
    assert result["contradictions"] == 1
    assert len(created) == 1
    kind, payload, memory_ids = created[0]
    assert kind == "resolve_conflict"
    assert payload["semantic"] is True
    assert set(memory_ids) == {first["id"], second["id"]}

    async with SessionLocal() as session:
        again = await detect_semantic_contradictions(
            session,
            workspace_id,
            user_id,
            provider_id="fake",
            model="fake-model",
            registry=registry,
            settings=get_settings(),
        )
        await session.commit()
    assert again["contradictions"] == 1
    assert again["suggestions"] == []


async def test_semantic_endpoint_validates_memory_switch_and_provider(
    client, api
):
    headers = await api.headers("p11s9-semantic-api@example.com")
    await _memory(
        client,
        headers,
        title="Cache choice A",
        content="The cache uses Redis.",
    )
    await _memory(
        client,
        headers,
        title="Cache choice B",
        content="The cache uses Memcached.",
    )
    disabled = await client.post(
        "/memories/quality/semantic", json={"limit": 5}, headers=headers
    )
    assert disabled.status_code == 422
    assert disabled.json()["detail"]["code"] == "memory_disabled"

    await _enable_memory(client, headers)
    configured = await client.post(
        "/memories/quality/semantic",
        json={"provider_id": "missing", "model": "missing", "limit": 5},
        headers=headers,
    )
    assert configured.status_code == 422
    assert configured.json()["detail"]["code"] == "provider_unavailable"


async def test_semantic_analysis_is_scoped_to_the_caller(client, api, registry):
    alice = await api.headers("p11s9-alice@example.com")
    bob = await api.headers("p11s9-bob@example.com")
    await _memory(
        client, alice, title="Alice DB", content="Alice uses PostgreSQL."
    )
    await _memory(
        client, alice, title="Alice DB alt", content="Alice uses MongoDB."
    )
    await _memory(client, bob, title="Bob DB", content="Bob uses SQLite.")
    await _memory(
        client, bob, title="Bob DB alt", content="Bob uses DuckDB."
    )
    await _enable_memory(client, alice)
    registry.get("fake").complete_content = _contradiction_payload()

    listed = await client.get("/memories?limit=1", headers=alice)
    assert listed.status_code == 200, listed.text
    async with SessionLocal() as session:
        row = await session.get(AgentMemory, UUID(listed.json()[0]["id"]))
        assert row is not None
        workspace_id, user_id = row.workspace_id, row.user_id
        result = await detect_semantic_contradictions(
            session,
            workspace_id,
            user_id,
            provider_id="fake",
            model="fake-model",
            registry=registry,
            settings=get_settings(),
        )
        suggestion_ids = (
            list(result["suggestions"][0].memory_ids)
            if isinstance(result["suggestions"], list) and result["suggestions"]
            else []
        )
        await session.commit()

    assert result["pairs_checked"] == 1
    assert len(suggestion_ids) == 2
    for memory_id in suggestion_ids:
        async with SessionLocal() as session:
            memory = await session.get(AgentMemory, UUID(memory_id))
            assert memory is not None
            assert memory.user_id == user_id