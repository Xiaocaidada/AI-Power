import hashlib
from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ApiKey, UsageEvent


async def _create_key(client, headers, name="CI key", scopes=None):
    payload = {"name": name}
    if scopes is not None:
        payload["scopes"] = scopes
    return await client.post("/api-keys", json=payload, headers=headers)


async def _create_conversation(client, headers):
    return await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )


async def test_api_key_management_requires_jwt(client, api):
    headers = await api.headers("keys-jwt@example.com")
    created = await _create_key(client, headers)
    key = created.json()["key"]

    no_auth = await client.get("/api-keys")
    with_key = await client.get("/api-keys", headers={"X-API-Key": key})

    assert no_auth.status_code == 401
    assert with_key.status_code == 401


async def test_create_key_returns_plaintext_once_and_stores_hash(client, api):
    headers = await api.headers("keys-create@example.com")

    response = await _create_key(client, headers, "My key")

    assert response.status_code == 201
    body = response.json()
    assert body["key"].startswith("ap_")
    assert body["key"].startswith(body["prefix"] + "_")
    assert body["scopes"] == ["chat:write", "kb:read"]
    assert body["last_used_at"] is None
    assert body["revoked_at"] is None

    async with SessionLocal() as session:
        stored = (await session.execute(select(ApiKey))).scalar_one()
    assert stored.key_hash == hashlib.sha256(body["key"].encode()).hexdigest()
    assert stored.key_hash != body["key"]

    listed = await client.get("/api-keys", headers=headers)
    assert listed.status_code == 200
    item = listed.json()[0]
    assert "key" not in item
    assert "key_hash" not in item
    assert item["prefix"] == body["prefix"]


async def test_key_with_chat_scope_can_send_messages(client, api, registry, fake_provider):
    headers = await api.headers("keys-chat@example.com")
    created_key = await _create_key(client, headers, "chat", scopes=["chat:write"])
    key = created_key.json()["key"]
    conversation = await _create_conversation(client, headers)

    response = await client.post(
        f"/conversations/{conversation.json()['id']}/messages",
        json={"content": "Hi"},
        headers={"X-API-Key": key},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    async with SessionLocal() as session:
        event = (await session.execute(select(UsageEvent))).scalar_one()
        stored = (await session.execute(select(ApiKey))).scalar_one()
    assert event.user_id == stored.user_id
    assert stored.last_used_at is not None


async def test_key_scopes_are_enforced(client, api, registry):
    headers = await api.headers("keys-scope@example.com")
    kb = await client.post("/knowledge-bases", json={"name": "KB"}, headers=headers)
    read_key = (await _create_key(client, headers, "read", scopes=["kb:read"])).json()["key"]
    chat_key = (await _create_key(client, headers, "chat", scopes=["chat:write"])).json()["key"]
    conversation = await _create_conversation(client, headers)

    list_kb_with_read = await client.get("/knowledge-bases", headers={"X-API-Key": read_key})
    create_conv_with_read = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers={"X-API-Key": read_key},
    )
    send_with_read = await client.post(
        f"/conversations/{conversation.json()['id']}/messages",
        json={"content": "Hi"},
        headers={"X-API-Key": read_key},
    )
    list_kb_with_chat = await client.get("/knowledge-bases", headers={"X-API-Key": chat_key})

    assert list_kb_with_read.status_code == 200
    assert kb.status_code == 201
    assert create_conv_with_read.status_code == 403
    assert send_with_read.status_code == 403
    assert list_kb_with_chat.status_code == 403


async def test_revoked_key_is_rejected(client, api):
    headers = await api.headers("keys-revoke@example.com")
    created = (await _create_key(client, headers, "revoke")).json()

    revoked = await client.delete(f"/api-keys/{created['id']}", headers=headers)
    use_after = await client.get("/knowledge-bases", headers={"X-API-Key": created["key"]})
    again = await client.delete(f"/api-keys/{created['id']}", headers=headers)

    assert revoked.status_code == 204
    assert use_after.status_code == 401
    assert again.status_code == 204

    async with SessionLocal() as session:
        stored = await session.get(ApiKey, UUID(created["id"]))
    assert stored.revoked_at is not None


async def test_keys_are_isolated_by_user(client, api):
    alice = await api.headers("keys-alice@example.com")
    bob = await api.headers("keys-bob@example.com")
    created = (await _create_key(client, alice, "alice key")).json()

    bob_list = await client.get("/api-keys", headers=bob)
    bob_delete = await client.delete(f"/api-keys/{created['id']}", headers=bob)

    assert bob_list.json() == []
    assert bob_delete.status_code == 404


async def test_invalid_api_key_is_rejected(client):
    response = await client.get(
        "/knowledge-bases", headers={"X-API-Key": "ap_deadbeef_not-a-real-key"}
    )

    assert response.status_code == 401
