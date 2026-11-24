import json

from sqlalchemy import select


async def _make_admin(email: str) -> None:
    from app.db import SessionLocal
    from app.models import User

    async with SessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one()
        user.role = "admin"
        await session.commit()


async def _seed_model_catalog() -> None:
    from app.db import SessionLocal
    from app.models import ModelCatalog

    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(ModelCatalog.id).where(
                    ModelCatalog.provider_id == "fake",
                    ModelCatalog.model_id == "fake-model",
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                ModelCatalog(
                    provider_id="fake",
                    model_id="fake-model",
                    display_name="Fake Model",
                    enabled=True,
                )
            )
            await session.commit()


async def _create_mcp_server(client, admin_headers, monkeypatch) -> dict:
    async def fake_validate(*_args, **_kwargs):
        return None

    async def fake_tools(*_args, **_kwargs):
        return [
            {
                "name": "search_docs",
                "description": "Search documentation",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                },
            }
        ]

    monkeypatch.setattr("app.routers.mcp_servers.validate_outbound_url", fake_validate)
    monkeypatch.setattr("app.routers.mcp_servers.list_mcp_tools", fake_tools)
    response = await client.post(
        "/admin/mcp-servers",
        json={
            "name": "Agent tools MCP",
            "description": "internal docs",
            "endpoint_url": "https://mcp.example.com/mcp",
            "enabled": True,
            "timeout_seconds": 10,
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_agent_generation_settings_and_conversation_inheritance(client, api):
    headers = await api.headers("p11s4-settings@example.com")
    created = await client.post(
        "/agents",
        json={
            "name": "Settings agent",
            "instructions": "Be precise.",
            "generation_settings": {
                "temperature": 2.5,
                "max_tokens": 999999,
                "top_p": -1,
            },
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    assert agent["generation_settings"] == {
        "temperature": 2.0,
        "max_tokens": 32768,
        "top_p": 0.0,
    }

    updated = await client.patch(
        f"/agents/{agent['id']}",
        json={"generation_settings": {"temperature": 0.4, "top_p": 0.9}},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["generation_settings"] == {
        "temperature": 0.4,
        "top_p": 0.9,
    }

    conversation = await client.post(
        "/conversations",
        json={"custom_agent_id": agent["id"]},
        headers=headers,
    )
    assert conversation.status_code == 201, conversation.text
    assert conversation.json()["generation_settings"] == {
        "temperature": 0.4,
        "top_p": 0.9,
    }
    assert conversation.json()["agent"] is True

    other = await api.headers("p11s4-settings-other@example.com")
    assert (await client.get(f"/agents/{agent['id']}", headers=other)).status_code == 404
    assert (
        await client.patch(
            f"/agents/{agent['id']}",
            json={"description": "nope"},
            headers=other,
        )
    ).status_code == 404


async def test_agent_tool_catalog_mcp_binding_and_test(client, api, monkeypatch):
    headers = await api.headers("p11s4-tools@example.com")
    admin = await api.headers("p11s4-tools-admin@example.com")
    await _make_admin("p11s4-tools-admin@example.com")
    server = await _create_mcp_server(client, admin, monkeypatch)

    catalog = await client.get("/agent-tools/catalog", headers=headers)
    assert catalog.status_code == 200, catalog.text
    payload = catalog.json()
    assert {item["name"] for item in payload["builtin"]} == {
        "kb_search",
        "current_time",
        "calculator",
        "project_files",
    }
    assert payload["mcp_servers"][0]["id"] == server["id"]

    async def fake_tools(*_args, **_kwargs):
        return [
            {
                "name": "search_docs",
                "description": "Search documentation",
                "input_schema": {"type": "object"},
            }
        ]

    monkeypatch.setattr("app.services.agent_tools.list_mcp_tools", fake_tools)
    tools = await client.get(
        f"/agent-tools/mcp?server_id={server['id']}", headers=headers
    )
    assert tools.status_code == 200, tools.text
    ref = tools.json()[0]["ref"]
    assert ref.startswith(f"mcp:{server['id']}:")

    invalid = await client.post(
        "/agents",
        json={"name": "Bad tools", "instructions": "x", "tools": ["mcp:not-a-uuid:x"]},
        headers=headers,
    )
    assert invalid.status_code == 422

    missing = await client.post(
        "/agents",
        json={
            "name": "Missing MCP",
            "instructions": "x",
            "tools": ["mcp:00000000-0000-0000-0000-000000000123:search"],
        },
        headers=headers,
    )
    assert missing.status_code == 422

    created = await client.post(
        "/agents",
        json={
            "name": "Tool agent",
            "instructions": "Use tools.",
            "tools": ["calculator", ref],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    assert set(agent["tools"]) == {"calculator", ref}

    calc = await client.post(
        f"/agents/{agent['id']}/tools/test",
        json={"tool": "calculator", "arguments": {"expression": "2 + 3"}},
        headers=headers,
    )
    assert calc.status_code == 200, calc.text
    assert calc.json()["ok"] is True
    assert calc.json()["output"] == "5"

    not_allowed = await client.post(
        f"/agents/{agent['id']}/tools/test",
        json={"tool": "current_time", "arguments": {}},
        headers=headers,
    )
    assert not_allowed.status_code == 422
    assert not_allowed.json()["detail"]["code"] == "tool_not_allowed"

    async def fake_call(_server, tool, arguments, **_kwargs):
        assert tool == "search_docs"
        assert arguments == {"query": "p11"}
        return "mcp result"

    monkeypatch.setattr("app.services.agent_tools.call_mcp_tool", fake_call)
    mcp = await client.post(
        f"/agents/{agent['id']}/tools/test",
        json={"tool": ref, "arguments": {"query": "p11"}},
        headers=headers,
    )
    assert mcp.status_code == 200, mcp.text
    assert mcp.json()["ok"] is True
    assert mcp.json()["output"] == "mcp result"

    other = await api.headers("p11s4-tools-other@example.com")
    denied = await client.post(
        f"/agents/{agent['id']}/tools/test",
        json={"tool": "calculator", "arguments": {"expression": "1+1"}},
        headers=other,
    )
    assert denied.status_code in {403, 404}


async def test_agent_conversation_runs_mcp_tool_with_agent_settings(
    client, api, registry, monkeypatch
):
    headers = await api.headers("p11s4-runtime@example.com")
    admin = await api.headers("p11s4-runtime-admin@example.com")
    await _make_admin("p11s4-runtime-admin@example.com")
    server = await _create_mcp_server(client, admin, monkeypatch)

    async def fake_tools(*_args, **_kwargs):
        return [
            {
                "name": "search_docs",
                "description": "Search documentation",
                "input_schema": {"type": "object"},
            }
        ]

    async def fake_call(_server, tool, arguments, **_kwargs):
        assert tool == "search_docs"
        assert arguments == {"query": "hello"}
        return "mcp result"

    monkeypatch.setattr("app.services.agent_tools.list_mcp_tools", fake_tools)
    monkeypatch.setattr("app.services.agent_tools.call_mcp_tool", fake_call)
    ref = f"mcp:{server['id']}:search_docs"

    created = await client.post(
        "/agents",
        json={
            "name": "Runtime MCP agent",
            "instructions": "Use MCP when needed.",
            "tools": [ref],
            "generation_settings": {"temperature": 0.3},
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    agent = created.json()

    conversation = await client.post(
        "/conversations",
        json={
            "custom_agent_id": agent["id"],
            "provider_id": "fake",
            "model": "fake-model",
        },
        headers=headers,
    )
    assert conversation.status_code == 201, conversation.text
    assert conversation.json()["agent"] is True
    assert conversation.json()["custom_agent_id"] == agent["id"]
    conversation_id = conversation.json()["id"]

    from app.providers.base import ChatChunk, Usage

    class ScriptedProvider:
        id = "fake"

        def __init__(self) -> None:
            self.outputs = [
                json.dumps(
                    {
                        "action": "tool",
                        "tool": ref,
                        "arguments": {"query": "hello"},
                    }
                ),
                json.dumps({"action": "final", "answer": "done"}),
            ]
            self.opts_calls: list[dict[str, object]] = []

        async def list_models(self):
            return []

        async def stream_chat(self, messages, model, **opts):
            self.opts_calls.append(dict(opts))
            output = self.outputs.pop(0) if self.outputs else "{}"
            yield ChatChunk(delta=output)
            yield ChatChunk(usage=Usage(prompt_tokens=1, completion_tokens=1))
            yield ChatChunk(finish_reason="stop")

    scripted = ScriptedProvider()
    registry._providers["fake"] = scripted
    response = await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "Search the docs"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert "mcp result" in response.text
    assert scripted.opts_calls
    assert scripted.opts_calls[0]["temperature"] == 0.3


async def test_agent_from_template_and_workflow_catalog(client, api):
    headers = await api.headers("p11s4-template@example.com")
    await _seed_model_catalog()

    catalog = await client.get("/workflows/catalog?kind=agent", headers=headers)
    assert catalog.status_code == 200
    templates = catalog.json()["templates"]
    assert {"assistant", "research", "reviewed"} <= {item["id"] for item in templates}

    created = await client.post(
        "/agents/from-template",
        json={
            "template": "assistant",
            "name": "Template assistant",
            "description": "Started from a template",
            "category": "general",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    assert agent["workflow_id"]
    assert agent["mode"] == "hybrid"
    assert agent["default_provider_id"] == "fake"
    assert agent["default_model"] == "fake-model"

    workflow = await client.get(f"/workflows/{agent['workflow_id']}", headers=headers)
    assert workflow.status_code == 200
    definition = workflow.json()["versions"][0]["definition"]
    assert [node["type"] for node in definition["nodes"]] == [
        "start",
        "agent",
        "output",
    ]
    agent_node = next(node for node in definition["nodes"] if node["type"] == "agent")
    assert agent_node["config"]["provider_id"] == "fake"
    assert agent_node["config"]["model"] == "fake-model"

    duplicate = await client.post(
        "/agents/from-template",
        json={"template": "research", "name": "Template assistant"},
        headers=headers,
    )
    assert duplicate.status_code == 422

    unknown = await client.post(
        "/agents/from-template",
        json={"template": "nope", "name": "Unknown template"},
        headers=headers,
    )
    assert unknown.status_code == 422


async def test_market_cover_publisher_official_and_facets(client, api):
    headers = await api.headers("p11s4-market@example.com")
    created = await client.post(
        "/agents",
        json={
            "name": "Market cover agent",
            "instructions": "Be useful.",
            "category": "research",
            "cover_url": "https://cdn.example.com/cover.png",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    assert agent["cover_url"] == "https://cdn.example.com/cover.png"

    invalid = await client.post(
        "/agents",
        json={
            "name": "Bad cover",
            "instructions": "x",
            "cover_url": "javascript:alert(1)",
        },
        headers=headers,
    )
    assert invalid.status_code == 422

    published = await client.post(
        f"/agents/{agent['id']}/publish",
        json={"slug": "market-cover", "allow_copy": True, "show_structure": True},
        headers=headers,
    )
    assert published.status_code == 200, published.text

    detail = await client.get("/market/agents/market-cover")
    assert detail.status_code == 200
    assert detail.json()["cover_url"] == "https://cdn.example.com/cover.png"
    assert detail.json()["publisher"] == "p***@example.com"
    assert detail.json()["official"] is False

    facets = await client.get("/market/agents/facets")
    assert facets.status_code == 200
    data = facets.json()
    assert data["total"] == 1
    assert data["official"] == 0
    assert data["categories"] == [{"value": "research", "count": 1}]
    assert data["publishers"] == [{"value": "p***@example.com", "count": 1}]

    by_publisher = await client.get(
        "/market/agents?publisher=p***%40example.com"
    )
    assert [item["slug"] for item in by_publisher.json()] == ["market-cover"]
    assert (await client.get("/market/agents?official=true")).json() == []

    admin = await api.headers("p11s4-market-admin@example.com")
    await _make_admin("p11s4-market-admin@example.com")
    admin_agent = await client.post(
        "/agents",
        json={
            "name": "Official agent",
            "instructions": "Official.",
            "category": "general",
        },
        headers=admin,
    )
    assert admin_agent.status_code == 201
    admin_id = admin_agent.json()["id"]
    assert (
        await client.post(
            f"/agents/{admin_id}/publish",
            json={"slug": "official-agent", "allow_copy": True, "show_structure": True},
            headers=admin,
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/admin/agents/{admin_id}/feature",
            json={"featured": True},
            headers=admin,
        )
    ).status_code == 200

    official = await client.get("/market/agents?official=true")
    assert [item["slug"] for item in official.json()] == ["official-agent"]
    assert official.json()[0]["official"] is True
    featured = await client.get("/market/agents?featured=true")
    assert [item["slug"] for item in featured.json()] == ["official-agent"]

    facets = (await client.get("/market/agents/facets")).json()
    assert facets["total"] == 2
    assert facets["official"] == 1
    assert facets["featured"] == 1
    assert json.dumps(facets, ensure_ascii=False).find("p11s4-market-admin") == -1