from uuid import UUID

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Conversation, PluginCall, User
from app.services.plugins import PluginError, build_plugin_tools, validate_plugin_endpoint
from app.tools.base import ToolContext, ToolRegistry


async def _make_admin(email: str) -> None:
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        user.role = "admin"
        await session.commit()


@pytest.fixture(autouse=True)
def _registry(registry):
    yield registry


@pytest.fixture
def allow_plugin_endpoint(monkeypatch):
    async def _noop(_url: str, _settings=None) -> None:
        return None

    monkeypatch.setattr("app.services.plugins.validate_plugin_endpoint", _noop)


@pytest.fixture
def fake_http(monkeypatch):
    calls: list[tuple[str, str, dict, dict]] = []

    class FakeResponse:
        status_code = 200

        async def aiter_bytes(self):
            yield b'{"ok": true}'

    class FakeClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> bool:
            return False

        async def post(self, url, json=None, headers=None):
            calls.append(("POST", url, json or {}, headers or {}))
            return FakeResponse()

        async def get(self, url, params=None, headers=None):
            calls.append(("GET", url, params or {}, headers or {}))
            return FakeResponse()

    monkeypatch.setattr("app.services.plugins.httpx.AsyncClient", FakeClient)
    return calls


def _agent_payload(**overrides):
    payload = {
        "name": "Pirate",
        "description": "Talks like a pirate",
        "instructions": "You are a pirate. Answer briefly.",
        "category": "writing",
        "default_provider_id": "fake",
        "default_model": "fake-model",
        "tools": ["calculator"],
        "visibility": "private",
    }
    payload.update(overrides)
    return payload


def _plugin_payload(**overrides):
    payload = {
        "slug": "weather",
        "name": "Weather",
        "description": "Looks up weather",
        "category": "data",
        "endpoint_url": "https://example.com/weather",
        "method": "POST",
        "auth_type": "none",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "sensitive": False,
    }
    payload.update(overrides)
    return payload


async def _create_plugin(client, admin, **overrides):
    response = await client.post(
        "/admin/plugins", json=_plugin_payload(**overrides), headers=admin
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _configure(client, headers, plugin_id, **payload):
    response = await client.patch(f"/plugins/{plugin_id}", json=payload, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _conversation(client, headers, **payload):
    response = await client.post("/conversations", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def _tool_specs(conversation_id: str):
    async with SessionLocal() as session:
        conversation = await session.get(Conversation, UUID(conversation_id))
        return await build_plugin_tools(session, conversation)


async def test_agent_marketplace_and_custom_crud(client, api):
    alice = await api.headers("agent-alice@example.com")
    bob = await api.headers("agent-bob@example.com")

    listed = await client.get("/agents", headers=alice)
    assert listed.status_code == 200
    builtin_ids = {item["id"] for item in listed.json() if item["builtin"]}
    assert builtin_ids == {"builtin:supervisor", "builtin:retrieval", "builtin:math"}

    created = await client.post("/agents", json=_agent_payload(), headers=alice)
    assert created.status_code == 201
    agent = created.json()
    assert agent["tools"] == ["calculator"]
    assert agent["owned"] is True
    agent_id = agent["id"]

    detail = await client.get(f"/agents/{agent_id}", headers=alice)
    assert detail.status_code == 200
    assert detail.json()["instructions"].startswith("You are a pirate")

    assert (await client.get(f"/agents/{agent_id}", headers=bob)).status_code == 404
    bob_ids = {item["id"] for item in (await client.get("/agents", headers=bob)).json()}
    assert agent_id not in bob_ids

    duplicate = await client.post("/agents", json=_agent_payload(), headers=alice)
    assert duplicate.status_code == 422

    invalid_tool = await client.post(
        "/agents", json=_agent_payload(name="Bad", tools=["shell"]), headers=alice
    )
    assert invalid_tool.status_code == 422

    assert (await client.delete(f"/agents/{agent_id}", headers=alice)).status_code == 204
    assert (await client.get(f"/agents/{agent_id}", headers=alice)).status_code == 404


async def test_shared_agent_is_read_only_for_members(client, api):
    alice = await api.headers("agent-team-alice@example.com")
    bob = await api.headers("agent-team-bob@example.com")
    team = await client.post("/workspaces", json={"name": "Agent team"}, headers=alice)
    team_id = team.json()["id"]
    assert (
        await client.post(
            f"/workspaces/{team_id}/members",
            json={"email": "agent-team-bob@example.com"},
            headers=alice,
        )
    ).status_code == 201
    alice_team = {**alice, "X-Workspace-Id": team_id}
    bob_team = {**bob, "X-Workspace-Id": team_id}

    created = await client.post(
        "/agents", json=_agent_payload(visibility="shared"), headers=alice_team
    )
    agent_id = created.json()["id"]

    bob_list = await client.get("/agents", headers=bob_team)
    bob_agent = next(item for item in bob_list.json() if item["id"] == agent_id)
    assert bob_agent["owned"] is False
    assert (
        await client.patch(
            f"/agents/{agent_id}", json={"name": "Hijack"}, headers=bob_team
        )
    ).status_code == 403


async def test_conversation_uses_custom_agent(client, api, fake_provider):
    headers = await api.headers("agent-chat@example.com")
    agent = (
        await client.post("/agents", json=_agent_payload(), headers=headers)
    ).json()

    conversation = await _conversation(client, headers, custom_agent_id=agent["id"])
    assert conversation["agent"] is True
    assert conversation["custom_agent_id"] == agent["id"]
    assert conversation["provider_id"] == "fake"
    assert conversation["model"] == "fake-model"

    sent = await client.post(
        f"/conversations/{conversation['id']}/messages",
        json={"content": "Hello"},
        headers=headers,
    )
    assert sent.status_code == 200
    system = fake_provider.calls[-1][0][0]
    assert system.role == "system"
    assert "You are a pirate" in system.content
    assert "supervisor" not in system.content.lower()


async def test_plugin_configuration_and_admin_surface(client, api, allow_plugin_endpoint):
    alice = await api.headers("plugin-owner@example.com")
    bob = await api.headers("plugin-member@example.com")
    admin = await api.headers("plugin-admin@example.com")
    await _make_admin("plugin-admin@example.com")

    assert (await client.get("/admin/plugins", headers=alice)).status_code == 404

    plugin = await _create_plugin(client, admin)
    assert plugin["sensitive"] is False
    assert plugin["configured"] is False

    listed = await client.get("/plugins", headers=alice)
    assert [item["id"] for item in listed.json()] == [plugin["id"]]
    assert listed.json()[0]["configured"] is False

    configured = await _configure(
        client, alice, plugin["id"], enabled=True, credential=None
    )
    assert configured["configured"] is True
    assert configured["config_enabled"] is True
    assert configured["status"] == "configured"

    team = await client.post("/workspaces", json={"name": "Plugin team"}, headers=alice)
    team_id = team.json()["id"]
    assert (
        await client.post(
            f"/workspaces/{team_id}/members",
            json={"email": "plugin-member@example.com"},
            headers=alice,
        )
    ).status_code == 201
    bob_team = {**bob, "X-Workspace-Id": team_id}
    assert (
        await client.patch(
            f"/plugins/{plugin['id']}", json={"enabled": False}, headers=bob_team
        )
    ).status_code == 403


async def test_plugin_execution_and_sensitive_confirmation(
    client, api, allow_plugin_endpoint, fake_http
):
    headers = await api.headers("plugin-exec@example.com")
    admin = await api.headers("plugin-exec-admin@example.com")
    await _make_admin("plugin-exec-admin@example.com")

    plugin = await _create_plugin(client, admin, sensitive=True)
    await _configure(client, headers, plugin["id"], enabled=True)
    conversation = await _conversation(
        client,
        headers,
        provider_id="fake",
        model="fake-model",
        agent=True,
        plugin_ids=[plugin["id"]],
    )

    specs = await _tool_specs(conversation["id"])
    assert [spec.name for spec in specs] == ["plugin__weather"]
    registry = ToolRegistry(specs, timeout_seconds=5)
    async with SessionLocal() as session:
        row = await session.get(Conversation, UUID(conversation["id"]))
        context = ToolContext(
            workspace_id=row.workspace_id,
            user_id=row.user_id,
            conversation_id=row.id,
        )

    blocked = await registry.execute("plugin__weather", {"query": "Paris"}, context)
    assert blocked.ok is False
    assert blocked.error_code == "plugin_confirmation_required"

    confirmed = await client.post(
        f"/conversations/{conversation['id']}/plugins/{plugin['id']}/confirm",
        headers=headers,
    )
    assert confirmed.status_code == 200
    assert confirmed.json()[0]["confirmed_at"] is not None

    result = await registry.execute("plugin__weather", {"query": "Paris"}, context)
    assert result.ok is True
    assert "ok" in result.output
    assert fake_http[-1][0] == "POST"
    assert fake_http[-1][2] == {"query": "Paris"}

    async with SessionLocal() as session:
        calls = list((await session.execute(select(PluginCall))).scalars())
    assert [call.status for call in calls] == ["ok"]
    assert "Paris" in calls[0].request_summary

    listed_calls = await client.get("/plugins/calls", headers=headers)
    assert listed_calls.status_code == 200
    assert listed_calls.json()[0]["status"] == "ok"


async def test_conversation_plugins_require_agent_mode(client, api, allow_plugin_endpoint):
    headers = await api.headers("plugin-agent-mode@example.com")
    admin = await api.headers("plugin-agent-admin@example.com")
    await _make_admin("plugin-agent-admin@example.com")
    plugin = await _create_plugin(client, admin)
    await _configure(client, headers, plugin["id"], enabled=True)
    conversation = await _conversation(
        client, headers, provider_id="fake", model="fake-model"
    )

    response = await client.put(
        f"/conversations/{conversation['id']}/plugins",
        json={"plugin_ids": [plugin["id"]]},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "agent_required"


async def test_plugin_ssrf_rejects_private_hosts():
    with pytest.raises(PluginError):
        await validate_plugin_endpoint("http://127.0.0.1:9000/internal")