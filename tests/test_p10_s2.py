import json
from uuid import UUID

from app.config import get_settings
from app.db import SessionLocal
from app.models import Conversation, Message
from app.services.memory_extraction import run_memory_extraction_for_message


async def _seed_turn(client, headers, text: str, *, project_id: str | None = None):
    payload = {"provider_id": "fake", "model": "fake-model"}
    if project_id is not None:
        payload["project_id"] = project_id
    conversation = await client.post("/conversations", json=payload, headers=headers)
    assert conversation.status_code == 201, conversation.text
    conversation_id = UUID(conversation.json()["id"])
    me = await client.get("/auth/me", headers=headers)
    user_id = UUID(me.json()["id"])
    async with SessionLocal() as session:
        stored = await session.get(Conversation, conversation_id)
        assert stored is not None
        user_message = Message(
            conversation_id=conversation_id,
            user_id=user_id,
            role="user",
            content=text,
            status="completed",
        )
        assistant = Message(
            conversation_id=conversation_id,
            user_id=user_id,
            role="assistant",
            content="Understood.",
            status="completed",
            provider_id="fake",
            model="fake-model",
        )
        session.add_all([user_message, assistant])
        await session.commit()
        await session.refresh(assistant)
        return stored, assistant


async def _enable_memory(client, headers, **overrides):
    payload = {
        "enabled": True,
        "auto_extract": True,
        "require_confirmation": True,
        "auto_save": False,
        **overrides,
    }
    response = await client.patch("/memories/settings", json=payload, headers=headers)
    assert response.status_code == 200, response.text


def _extraction_payload(
    category="preference", content="Prefers concise Chinese answers."
):
    return json.dumps(
        [
            {
                "category": category,
                "title": "Answer style",
                "content": content,
                "scope_type": "global",
                "confidence": 0.9,
                "tags": ["style"],
                "reason": "stable preference",
            }
        ]
    )


async def test_extraction_creates_candidate_and_accepts(client, api, registry):
    headers = await api.headers("p10s2-accept@example.com")
    await _enable_memory(client, headers)
    _, assistant = await _seed_turn(
        client, headers, "I prefer concise Chinese answers."
    )
    registry.get("fake").complete_content = _extraction_payload()

    result = await run_memory_extraction_for_message(
        assistant.id, registry=registry, settings=get_settings()
    )
    assert result["status"] == "completed", result
    assert result["pending"] == 1

    listed = await client.get("/memories/candidates?status=pending", headers=headers)
    assert listed.status_code == 200, listed.text
    candidates = listed.json()
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["suggested_action"] == "create"
    assert candidate["source_id"] == str(assistant.id)

    accepted = await client.post(
        f"/memories/candidates/{candidate['id']}/accept",
        json={},
        headers=headers,
    )
    assert accepted.status_code == 200, accepted.text
    memory = accepted.json()
    assert memory["category"] == "preference"
    assert memory["status"] == "active"
    assert memory["tags"] == ["style"]

    remaining = await client.get(
        "/memories/candidates?status=pending", headers=headers
    )
    assert remaining.json() == []


async def test_explicit_remember_saves_directly(client, api, registry):
    headers = await api.headers("p10s2-explicit@example.com")
    await _enable_memory(client, headers)
    _, assistant = await _seed_turn(
        client, headers, "请记住：我偏好简洁的中文回答。"
    )
    registry.get("fake").complete_content = _extraction_payload()

    result = await run_memory_extraction_for_message(
        assistant.id, registry=registry, settings=get_settings()
    )
    assert result["status"] == "completed", result
    assert result["explicit"] is True
    assert result["saved"] == 1

    memories = await client.get("/memories?category=preference", headers=headers)
    assert len(memories.json()) == 1
    assert memories.json()[0]["source_type"] == "chat"
    candidates = await client.get(
        "/memories/candidates?status=pending", headers=headers
    )
    assert candidates.json() == []


async def test_auto_save_policy(client, api, registry):
    headers = await api.headers("p10s2-autosave@example.com")
    await _enable_memory(
        client,
        headers,
        require_confirmation=False,
        auto_save=True,
        allowed_categories=["preference"],
    )
    _, assistant = await _seed_turn(client, headers, "I prefer concise answers.")
    registry.get("fake").complete_content = _extraction_payload()

    result = await run_memory_extraction_for_message(
        assistant.id, registry=registry, settings=get_settings()
    )
    assert result["saved"] == 1
    memories = await client.get("/memories", headers=headers)
    assert len(memories.json()) == 1


async def test_duplicate_and_idempotency(client, api, registry):
    headers = await api.headers("p10s2-duplicate@example.com")
    await _enable_memory(client, headers)
    _, assistant = await _seed_turn(
        client, headers, "I prefer concise Chinese answers."
    )
    created = await client.post(
        "/memories",
        json={
            "content": "Prefers concise Chinese answers.",
            "title": "Answer style",
            "category": "preference",
            "scope_type": "global",
        },
        headers=headers,
    )
    assert created.status_code == 201
    registry.get("fake").complete_content = _extraction_payload()

    result = await run_memory_extraction_for_message(
        assistant.id, registry=registry, settings=get_settings()
    )
    assert result["status"] == "completed"
    duplicates = await client.get(
        "/memories/candidates?status=duplicate", headers=headers
    )
    assert len(duplicates.json()) == 1
    assert duplicates.json()[0]["target_memory_id"] == created.json()["id"]

    again = await run_memory_extraction_for_message(
        assistant.id, registry=registry, settings=get_settings()
    )
    assert again["status"] == "skipped"
    assert again["reason"] == "already_processed"


async def test_reject_candidate(client, api, registry):
    headers = await api.headers("p10s2-reject@example.com")
    await _enable_memory(client, headers)
    _, assistant = await _seed_turn(client, headers, "I prefer concise answers.")
    registry.get("fake").complete_content = _extraction_payload()
    await run_memory_extraction_for_message(
        assistant.id, registry=registry, settings=get_settings()
    )
    candidate = (
        await client.get("/memories/candidates?status=pending", headers=headers)
    ).json()[0]
    rejected = await client.post(
        f"/memories/candidates/{candidate['id']}/reject", headers=headers
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert (await client.get("/memories", headers=headers)).json() == []

async def test_scope_unavailable_forces_review(client, api, registry):
    headers = await api.headers("p10s2-scope@example.com")
    await _enable_memory(
        client,
        headers,
        require_confirmation=False,
        auto_save=True,
        allowed_categories=["project"],
    )
    _, assistant = await _seed_turn(
        client, headers, "The project uses FastAPI."
    )
    registry.get("fake").complete_content = json.dumps(
        [
            {
                "category": "project",
                "title": "Stack",
                "content": "The project uses FastAPI.",
                "scope_type": "project",
                "confidence": 0.9,
                "tags": ["stack"],
                "reason": "project fact",
            }
        ]
    )
    result = await run_memory_extraction_for_message(
        assistant.id, registry=registry, settings=get_settings()
    )
    assert result["saved"] == 0
    assert result["pending"] == 1
    candidate = (
        await client.get("/memories/candidates?status=pending", headers=headers)
    ).json()[0]
    assert candidate["scope_type"] == "global"
    assert candidate["sensitivity"] == "sensitive"
    assert "scope_unavailable" in candidate["reason"]
    assert (await client.get("/memories", headers=headers)).json() == []


async def test_secret_patterns_block_and_filter(client, api, registry):
    headers = await api.headers("p10s2-secrets@example.com")
    blocked = await client.post(
        "/memories",
        json={
            "content": "Use Bearer abcdefghijklmnopqrstuvwxyz123456 for the API.",
            "category": "technical",
        },
        headers=headers,
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "secret_blocked"

    await _enable_memory(client, headers)
    _, assistant = await _seed_turn(client, headers, "Here is my key.")
    registry.get("fake").complete_content = json.dumps(
        [
            {
                "category": "technical",
                "title": "Key",
                "content": "api_key = sk-abcdefghijklmnop123456",
                "scope_type": "global",
                "confidence": 0.9,
                "tags": [],
                "reason": "secret",
            }
        ]
    )
    result = await run_memory_extraction_for_message(
        assistant.id, registry=registry, settings=get_settings()
    )
    assert result["status"] == "completed"
    assert result["saved"] == 0
    assert result["pending"] == 0
    assert (
        await client.get("/memories/candidates?status=pending", headers=headers)
    ).json() == []
