import json
from uuid import UUID

from app.db import SessionLocal
from app.models import ProviderConfig, ProviderModel


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


async def _create(client, headers, **payload):
    body = {"provider_id": "fake", "model": "fake-model", **payload}
    return await client.post("/conversations", json=body, headers=headers)


async def test_chat_modes_require_auth(client):
    response = await client.get("/chat/modes")

    assert response.status_code == 401


async def test_chat_modes_expose_unimplemented_modes(client, api):
    headers = await api.headers("p12-modes@example.com")

    response = await client.get("/chat/modes", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["thinking_levels"] == ["fast", "standard", "deep"]
    modes = {item["id"]: item for item in body["modes"]}
    assert set(modes) == {"chat", "web_search", "deep_research", "study", "agent"}
    assert modes["chat"]["implemented"] is True
    assert modes["agent"]["implemented"] is True
    assert modes["web_search"]["implemented"] is True
    assert modes["deep_research"]["implemented"] is False
    assert modes["study"]["implemented"] is False


async def test_create_conversation_defaults_to_chat_mode(client, api, registry):
    headers = await api.headers("p12-default-mode@example.com")

    response = await _create(client, headers)

    assert response.status_code == 201
    assert response.json()["default_mode"] == "chat"
    assert response.json()["agent"] is False


async def test_create_conversation_persists_planned_mode(client, api, registry):
    headers = await api.headers("p12-study-mode@example.com")

    response = await _create(client, headers, mode="study")

    assert response.status_code == 201
    assert response.json()["default_mode"] == "study"
    conversation_id = response.json()["id"]
    detail = await client.get(f"/conversations/{conversation_id}", headers=headers)
    assert detail.json()["default_mode"] == "study"


async def test_planned_mode_send_returns_typed_error(client, api, registry):
    headers = await api.headers("p12-planned-send@example.com")
    created = await _create(client, headers, mode="deep_research")

    response = await client.post(
        f"/conversations/{created.json()['id']}/messages",
        json={"content": "Research this"},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "mode_not_available"
    detail = await client.get(f"/conversations/{created.json()['id']}", headers=headers)
    assert detail.json()["messages"] == []


async def test_create_conversation_rejects_unknown_mode(client, api, registry):
    headers = await api.headers("p12-bad-mode@example.com")

    response = await _create(client, headers, mode="telepathy")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_mode"


async def test_create_conversation_mode_agent_enables_agent(client, api, registry):
    headers = await api.headers("p12-agent-mode@example.com")

    response = await _create(client, headers, mode="agent")

    assert response.status_code == 201
    assert response.json()["default_mode"] == "agent"
    assert response.json()["agent"] is True


async def test_create_conversation_rejects_agent_with_planned_mode(client, api, registry):
    headers = await api.headers("p12-mode-conflict@example.com")

    response = await _create(client, headers, mode="study", agent=True)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "mode_conflict"


async def test_send_records_mode_and_thinking_level(client, api, registry):
    headers = await api.headers("p12-send-metadata@example.com")
    created = await _create(client, headers)

    response = await client.post(
        f"/conversations/{created.json()['id']}/messages",
        json={"content": "Hi", "mode_meta": {"thinking_level": "standard"}},
        headers=headers,
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events[0][0] == "meta"
    assert events[0][1]["mode"] == "chat"
    assert events[0][1]["mode_meta"] == {"thinking_level": "standard"}

    detail = await client.get(f"/conversations/{created.json()['id']}", headers=headers)
    messages = detail.json()["messages"]
    assert [message["mode"] for message in messages] == ["chat", "chat"]
    assert messages[0]["mode_meta"] == {"thinking_level": "standard"}
    assert messages[1]["mode_meta"] == {"thinking_level": "standard"}


async def test_send_rejects_unsupported_thinking_level(client, api, registry):
    headers = await api.headers("p12-thinking@example.com")
    created = await _create(client, headers)

    response = await client.post(
        f"/conversations/{created.json()['id']}/messages",
        json={"content": "Hi", "mode_meta": {"thinking_level": "deep"}},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "thinking_level_unsupported"


async def test_update_conversation_mode(client, api, registry):
    alice = await api.headers("p12-patch-mode@example.com")
    bob = await api.headers("p12-patch-intruder@example.com")
    created = await _create(client, alice)
    conversation_id = created.json()["id"]

    response = await client.patch(
        f"/conversations/{conversation_id}",
        json={"default_mode": "study"},
        headers=alice,
    )
    intruder = await client.patch(
        f"/conversations/{conversation_id}",
        json={"default_mode": "chat"},
        headers=bob,
    )

    assert response.status_code == 200
    assert response.json()["default_mode"] == "study"
    assert intruder.status_code == 404


async def test_capabilities_endpoint_reports_declared_levels(client, api):
    headers = await api.headers("p12-capabilities@example.com")
    me = await client.get("/auth/me", headers=headers)
    workspaces = await client.get("/workspaces", headers=headers)
    async with SessionLocal() as session:
        config = ProviderConfig(
            workspace_id=UUID(workspaces.json()[0]["id"]),
            owner_user_id=UUID(me.json()["id"]),
            name="Reasoner",
            base_url="https://reasoner.example/v1",
            api_key_encrypted="test-only",
        )
        session.add(config)
        await session.flush()
        session.add(
            ProviderModel(
                config_id=config.id,
                model_id="reasoner-1",
                display_name="Reasoner 1",
                capabilities=["chat", "tools", "reasoning"],
                reasoning_levels=["fast", "standard", "deep"],
            )
        )
        await session.commit()
        config_id = str(config.id)

    response = await client.get(
        f"/chat/capabilities?provider_id={config_id}&model=reasoner-1",
        headers=headers,
    )
    personal = await client.get("/provider-configs/models", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["capabilities"] == ["chat", "tools", "reasoning"]
    assert all(item["supported"] for item in body["thinking_levels"])
    assert personal.status_code == 200
    assert personal.json()[0]["reasoning_levels"] == ["fast", "standard", "deep"]


async def test_capabilities_without_manifest_supports_standard_only(client, api, registry):
    headers = await api.headers("p12-capabilities-fallback@example.com")

    response = await client.get(
        "/chat/capabilities?provider_id=fake&model=fake-model", headers=headers
    )

    assert response.status_code == 200
    supported = {item["id"]: item["supported"] for item in response.json()["thinking_levels"]}
    assert supported == {"fast": False, "standard": True, "deep": False}
