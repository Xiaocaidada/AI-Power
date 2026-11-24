from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select


async def _create_memory(client, headers, **overrides):
    body = {
        "content": "User prefers concise answers and dark mode.",
        "title": "Answer style",
        "category": "preference",
        "scope_type": "global",
        "importance": 4,
        "tags": ["style", "ui"],
        "sensitivity": "normal",
        "status": "active",
    }
    body.update(overrides)
    response = await client.post("/memories", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_memory_stats_completeness_usage_lifecycle(client, api):
    headers = await api.headers("p11s7-stats@example.com")
    memory = await _create_memory(
        client, headers, retention_days=1, content="alpha beta gamma delta " * 8
    )
    await _create_memory(
        client,
        headers,
        title="Sparse",
        content="short",
        category="fact",
        tags=[],
        importance=1,
    )

    settings = await client.patch(
        "/memories/settings",
        json={"blocked_topics": ["forbidden-topic"], "retention_days": 1},
        headers=headers,
    )
    assert settings.status_code == 200, settings.text

    blocked = await client.post(
        "/memories",
        json={"content": "This mentions forbidden-topic directly", "title": "blocked"},
        headers=headers,
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "blocked_topic"
    blocked_update = await client.patch(
        f"/memories/{memory['id']}",
        json={"content": "forbidden-topic in updated content"},
        headers=headers,
    )
    assert blocked_update.status_code == 422

    from app.db import SessionLocal
    from app.models import AgentMemory, MemoryUsageEvent

    async with SessionLocal() as session:
        row = await session.get(AgentMemory, UUID(memory["id"]))
        assert row is not None
        session.add(
            MemoryUsageEvent(
                workspace_id=row.workspace_id,
                user_id=row.user_id,
                memory_id=row.id,
                context_type="chat",
                context_id="conversation-1",
                provider_id="fake",
                model="fake-model",
                relevance=0.9,
                injected_chars=120,
            )
        )
        row.updated_at = datetime.now(UTC) - timedelta(days=40)
        await session.commit()

    stats = await client.get("/memories/stats", headers=headers)
    assert stats.status_code == 200, stats.text
    payload = stats.json()
    assert payload["total"] == 2
    assert payload["completeness"]["average_score"] > 0
    assert payload["completeness"]["partial"] >= 1
    assert payload["usage_total"] == 1
    assert payload["usage_chars"] == 120
    assert payload["usage_by_model"][0]["model"] == "fake-model"
    assert payload["usage_by_context"] == {"chat": 1}
    assert payload["retention_days"] == 1
    assert payload["expiring_soon"] == 0

    lifecycle = await client.get("/memories/lifecycle", headers=headers)
    assert lifecycle.status_code == 200, lifecycle.text
    assert lifecycle.json()["retention_days"] == 1
    assert lifecycle.json()["expiring_count"] == 1
    assert lifecycle.json()["items"][0]["id"] == memory["id"]

    from app.services.memories import expire_retention_memories

    async with SessionLocal() as session:
        result = await expire_retention_memories(session)
        await session.commit()
    assert result["expired"] >= 1
    expired = await client.get(f"/memories/{memory['id']}", headers=headers)
    assert expired.json()["status"] == "expired"


async def test_memory_version_diff(client, api):
    headers = await api.headers("p11s7-diff@example.com")
    memory = await _create_memory(
        client, headers, content="Original content about alpha.", tags=["old"]
    )
    updated = await client.patch(
        f"/memories/{memory['id']}",
        json={
            "content": "Updated content about beta and gamma.",
            "status": "archived",
            "sensitivity": "sensitive",
            "tags": ["new"],
            "confidence": 0.4,
            "change_reason": "manual update",
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text

    diff = await client.get(
        f"/memories/{memory['id']}/versions/diff?from_version=1&to_version=2",
        headers=headers,
    )
    assert diff.status_code == 200, diff.text
    body = diff.json()
    fields = {change["field"] for change in body["changes"]}
    assert {"content", "status", "sensitivity", "tags", "confidence"} <= fields
    assert "-Original content about alpha." in body["content_diff"]
    assert "+Updated content about beta and gamma." in body["content_diff"]
    assert "sensitivity_increased" in body["risk_flags"]
    assert "deactivated" in body["risk_flags"]
    assert body["to_reason"] == "manual update"

    missing = await client.get(
        f"/memories/{memory['id']}/versions/diff?from_version=1&to_version=99",
        headers=headers,
    )
    assert missing.status_code == 404
    other = await api.headers("p11s7-diff-other@example.com")
    assert (
        await client.get(
            f"/memories/{memory['id']}/versions/diff", headers=other
        )
    ).status_code == 404


async def test_memory_retention_clears_and_form_fields(client, api):
    headers = await api.headers("p11s7-retention@example.com")
    memory = await _create_memory(client, headers, retention_days=30)
    assert memory["retention_days"] == 30
    cleared = await client.patch(
        f"/memories/{memory['id']}",
        json={"retention_days": 0},
        headers=headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["retention_days"] is None

    from app.db import SessionLocal
    from app.models import MemoryVersion

    async with SessionLocal() as session:
        versions = list(
            (
                await session.execute(
                    select(MemoryVersion)
                    .where(MemoryVersion.memory_id == UUID(memory["id"]))
                    .order_by(MemoryVersion.version)
                )
            ).scalars()
        )
    assert versions[0].snapshot["retention_days"] == 30
    assert versions[-1].snapshot["retention_days"] is None