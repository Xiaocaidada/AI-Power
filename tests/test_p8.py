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


async def _create_workflow(client, headers: dict[str, str]) -> str:
    definition = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}, "ui": {"x": 80, "y": 80}},
            {
                "id": "retrieve",
                "type": "kb_search",
                "config": {"query": "{{input}}", "kb_ids": []},
                "ui": {"x": 300, "y": 80},
            },
            {"id": "out", "type": "output", "config": {}, "ui": {"x": 520, "y": 80}},
        ],
        "edges": [
            {"from": "start", "to": "retrieve"},
            {"from": "retrieve", "to": "out"},
        ],
    }
    response = await client.post(
        "/workflows",
        json={"name": "P8 workflow", "description": "canvas", "definition": definition},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_workflow_catalog_and_start_output_run(client, api):
    headers = await api.headers("p8-workflow@example.com")
    catalog = await client.get("/workflows/catalog", headers=headers)
    assert catalog.status_code == 200
    types = {item["type"] for item in catalog.json()["nodes"]}
    assert {"start", "llm", "agent", "kb_search", "tool", "condition", "output"} <= types

    definition = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [{"from": "start", "to": "out"}],
    }
    created = await client.post(
        "/workflows",
        json={"name": "Echo", "definition": definition},
        headers=headers,
    )
    assert created.status_code == 201
    workflow_id = created.json()["id"]
    run = await client.post(
        f"/workflows/{workflow_id}/runs",
        json={"input": "hello canvas"},
        headers=headers,
    )
    assert run.status_code == 202
    detail = await client.get(f"/workflows/runs/{run.json()['run_id']}", headers=headers)
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["status"] == "completed"
    assert {node["node_type"] for node in payload["nodes"]} == {"start", "output"}


async def test_agent_publish_copy_and_market(client, api, registry):
    headers = await api.headers("p8-publish@example.com")
    kb = await client.post("/knowledge-bases", json={"name": "P8 KB"}, headers=headers)
    assert kb.status_code == 201
    kb_id = kb.json()["id"]
    workflow_id = await _create_workflow(client, headers)

    created = await client.post(
        "/agents",
        json={
            "name": "Research studio",
            "description": "P8 studio agent",
            "instructions": "Research carefully.",
            "category": "research",
            "mode": "workflow",
            "icon": "🧪",
            "welcome_message": "What should we research?",
            "examples": ["Summarize the docs"],
            "usage_instructions": "Provide a topic.",
            "generation_settings": {"temperature": 0.3},
            "default_provider_id": "fake",
            "default_model": "fake-model",
            "kb_ids": [kb_id],
            "workflow_id": workflow_id,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    agent = created.json()
    assert agent["mode"] == "workflow"
    assert agent["kb_ids"] == [kb_id]
    assert agent["icon"] == "🧪"

    publish = await client.post(
        f"/agents/{agent['id']}/publish",
        json={"slug": "research-studio", "allow_copy": True, "show_structure": True},
        headers=headers,
    )
    assert publish.status_code == 200
    assert publish.json()["published"] is True

    public = await client.get("/market/agents/research-studio")
    assert public.status_code == 200
    detail = public.json()
    assert detail["name"] == "Research studio"
    assert detail["workflow"]["definition"]["nodes"]
    assert detail["kb_requirements"] == ["P8 KB"]
    assert kb_id not in json.dumps(detail)

    listing = await client.get("/market/agents?search=research")
    assert listing.status_code == 200
    assert [item["slug"] for item in listing.json()] == ["research-studio"]

    other = await api.headers("p8-copy@example.com")
    favorite = await client.put(f"/agents/{agent['id']}/favorite", headers=other)
    assert favorite.status_code == 200
    assert favorite.json()["favorite"] is True

    copied = await client.post(f"/agents/{agent['id']}/copy", headers=other)
    assert copied.status_code == 201
    copy = copied.json()
    assert copy["id"] != agent["id"]
    assert copy["kb_ids"] == []
    assert copy["workflow_id"] is not None
    cloned = await client.get(f"/workflows/{copy['workflow_id']}", headers=other)
    assert cloned.status_code == 200
    nodes = cloned.json()["versions"][0]["definition"]["nodes"]
    retrieve = next(node for node in nodes if node["type"] == "kb_search")
    assert retrieve["config"]["kb_ids"] == []


def _echo_definition(extra_node: bool = False) -> dict:
    nodes = [
        {"id": "start", "type": "start", "config": {}},
    ]
    edges = []
    if extra_node:
        nodes.append(
            {
                "id": "ask",
                "type": "llm",
                "config": {
                    "provider_id": "fake",
                    "model": "fake-model",
                    "prompt": "Answer: {{input}}",
                },
            }
        )
        edges.append({"from": "start", "to": "ask"})
        nodes.append({"id": "out", "type": "output", "config": {}})
        edges.append({"from": "ask", "to": "out"})
    else:
        nodes.append({"id": "out", "type": "output", "config": {}})
        edges.append({"from": "start", "to": "out"})
    return {"nodes": nodes, "edges": edges}


async def test_agent_builder_multiturn_diff_and_apply(client, api, registry):
    headers = await api.headers("p8-builder-session@example.com")
    await _seed_model_catalog()
    session = await client.post(
        "/agent-builder/sessions",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )
    assert session.status_code == 201
    session_id = session.json()["id"]

    registry.get("fake").complete_content = json.dumps(
        {
            "message": "Added an LLM step.",
            "summary": "Add LLM",
            "definition": _echo_definition(extra_node=True),
            "missing_resources": [],
            "suggestions": [],
        }
    )
    turn = await client.post(
        f"/agent-builder/sessions/{session_id}/messages",
        json={
            "kind": "modify",
            "prompt": "Add an LLM step",
            "current_definition": _echo_definition(),
        },
        headers=headers,
    )
    assert turn.status_code == 200, turn.text
    payload = turn.json()
    assert payload["definition"]["nodes"]
    assert [item["id"] for item in payload["diff"]["added_nodes"]] == ["ask"]
    assert payload["diff"]["added_edges"][0]["from"] == "start"

    stored = await client.get(
        f"/agent-builder/sessions/{session_id}", headers=headers
    )
    assert stored.status_code == 200
    assert len(stored.json()["messages"]) == 2

    applied = await client.post(
        f"/agent-builder/sessions/{session_id}/apply",
        json={"definition": payload["definition"]},
        headers=headers,
    )
    assert applied.status_code == 200
    assert [node["id"] for node in applied.json()["draft_definition"]["nodes"]] == [
        "start",
        "ask",
        "out",
    ]
    assert len(applied.json()["messages"]) == 3

    registry.get("fake").complete_content = json.dumps(
        {
            "message": "The flow starts, calls the LLM, then outputs.",
            "summary": "Explanation",
            "missing_resources": [],
            "suggestions": ["Add a KB search step for grounding."],
        }
    )
    explain = await client.post(
        f"/agent-builder/sessions/{session_id}/messages",
        json={
            "kind": "explain",
            "prompt": "Explain this workflow",
            "current_definition": payload["definition"],
        },
        headers=headers,
    )
    assert explain.status_code == 200
    assert explain.json()["definition"] is None
    assert explain.json()["suggestions"] == ["Add a KB search step for grounding."]

    other = await api.headers("p8-builder-other@example.com")
    assert (
        await client.get(f"/agent-builder/sessions/{session_id}", headers=other)
    ).status_code == 404


async def test_agent_builder_fix_uses_failed_run(client, api, registry):
    headers = await api.headers("p8-builder-fix@example.com")
    await _seed_model_catalog()
    workflow = await client.post(
        "/workflows",
        json={
            "name": "Needs KB",
            "definition": {
                "nodes": [
                    {"id": "start", "type": "start", "config": {}},
                    {
                        "id": "retrieve",
                        "type": "kb_search",
                        "config": {"query": "{{input}}"},
                    },
                    {"id": "out", "type": "output", "config": {}},
                ],
                "edges": [
                    {"from": "start", "to": "retrieve"},
                    {"from": "retrieve", "to": "out"},
                ],
            },
        },
        headers=headers,
    )
    workflow_id = workflow.json()["id"]
    accepted = await client.post(
        f"/workflows/{workflow_id}/runs",
        json={"input": "research"},
        headers=headers,
    )
    run_id = accepted.json()["run_id"]
    failed = await client.get(f"/workflows/runs/{run_id}", headers=headers)
    assert failed.json()["status"] == "failed"

    session = await client.post(
        "/agent-builder/sessions",
        json={
            "provider_id": "fake",
            "model": "fake-model",
            "workflow_id": workflow_id,
        },
        headers=headers,
    )
    session_id = session.json()["id"]
    registry.get("fake").complete_content = json.dumps(
        {
            "message": "Replaced the missing KB search with an LLM step.",
            "summary": "Fix missing KB",
            "definition": _echo_definition(extra_node=True),
            "missing_resources": [],
            "suggestions": ["Attach a knowledge base before using kb_search."],
        }
    )
    fixed = await client.post(
        f"/agent-builder/sessions/{session_id}/messages",
        json={
            "kind": "fix",
            "prompt": "Fix the failed run",
            "run_id": run_id,
            "current_definition": {
                "nodes": [
                    {"id": "start", "type": "start", "config": {}},
                    {
                        "id": "retrieve",
                        "type": "kb_search",
                        "config": {"query": "{{input}}"},
                    },
                    {"id": "out", "type": "output", "config": {}},
                ],
                "edges": [
                    {"from": "start", "to": "retrieve"},
                    {"from": "retrieve", "to": "out"},
                ],
            },
        },
        headers=headers,
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["diff"]["removed_nodes"][0]["id"] == "retrieve"
    assert fixed.json()["message"]


async def test_agent_scopes_featured_and_market_filter(client, api):
    headers = await api.headers("p8-scopes@example.com")

    async def create(name: str) -> dict:
        response = await client.post(
            "/agents",
            json={"name": name, "instructions": "Be helpful."},
            headers=headers,
        )
        assert response.status_code == 201, response.text
        return response.json()

    first = await create("Scope one")
    second = await create("Scope two")
    copied = await client.post(f"/agents/{first['id']}/copy", headers=headers)
    assert copied.status_code == 201

    created = await client.get("/agents?scope=created", headers=headers)
    assert {item["name"] for item in created.json()} == {"Scope one", "Scope two"}
    copied_scope = await client.get("/agents?scope=copied", headers=headers)
    assert [item["name"] for item in copied_scope.json()] == ["Scope one (copy)"]

    favorite = await client.put(f"/agents/{first['id']}/favorite", headers=headers)
    assert favorite.status_code == 200
    favorites = await client.get("/agents?scope=favorites", headers=headers)
    assert [item["id"] for item in favorites.json()] == [first["id"]]

    publish = await client.post(
        f"/agents/{second['id']}/publish",
        json={"slug": "scope-two", "allow_copy": True, "show_structure": True},
        headers=headers,
    )
    assert publish.status_code == 200
    published = await client.get("/agents?scope=published", headers=headers)
    assert [item["id"] for item in published.json()] == [second["id"]]

    admin = await api.headers("p8-agent-admin@example.com")
    await _make_admin("p8-agent-admin@example.com")
    assert (await client.get("/admin/agents", headers=headers)).status_code == 404
    admin_list = await client.get("/admin/agents", headers=admin)
    assert admin_list.status_code == 200
    featured = await client.post(
        f"/admin/agents/{second['id']}/feature",
        json={"featured": True},
        headers=admin,
    )
    assert featured.status_code == 200
    assert featured.json()["featured"] is True
    market = await client.get("/market/agents?featured=true")
    assert [item["slug"] for item in market.json()] == ["scope-two"]

    usage = await client.post(f"/agents/{first['id']}/use", headers=headers)
    assert usage.status_code == 200
    assert usage.json()["usage_count"] == 1


async def test_agent_runs_and_project_default_agent(client, api):
    headers = await api.headers("p8-runs@example.com")
    agent = await client.post(
        "/agents",
        json={"name": "Runs agent", "instructions": "Be helpful."},
        headers=headers,
    )
    assert agent.status_code == 201
    agent_id = agent.json()["id"]

    project = await client.post(
        "/projects",
        json={"name": "P8 project", "default_custom_agent_id": agent_id},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    assert project.json()["default_custom_agent_id"] == agent_id

    conversation = await client.post(
        "/conversations", json={"project_id": project.json()["id"]}, headers=headers
    )
    assert conversation.status_code == 201, conversation.text
    assert conversation.json()["custom_agent_id"] == agent_id
    refreshed = await client.get(f"/agents/{agent_id}", headers=headers)
    assert refreshed.json()["usage_count"] == 1

    runs = await client.get(f"/agents/{agent_id}/runs", headers=headers)
    assert runs.status_code == 200
    assert runs.json()[0]["kind"] == "chat"

    workflow = await client.post(
        "/workflows",
        json={
            "name": "Run history",
            "definition": {
                "nodes": [
                    {"id": "start", "type": "start", "config": {}},
                    {"id": "out", "type": "output", "config": {}},
                ],
                "edges": [{"from": "start", "to": "out"}],
            },
        },
        headers=headers,
    )
    workflow_agent = await client.post(
        "/agents",
        json={
            "name": "Workflow runs agent",
            "instructions": "Run the workflow.",
            "mode": "workflow",
            "workflow_id": workflow.json()["id"],
        },
        headers=headers,
    )
    assert workflow_agent.status_code == 201
    accepted = await client.post(
        f"/workflows/{workflow.json()['id']}/runs",
        json={"input": "hello"},
        headers=headers,
    )
    workflow_runs = await client.get(
        f"/agents/{workflow_agent.json()['id']}/runs", headers=headers
    )
    assert workflow_runs.status_code == 200
    assert workflow_runs.json()[0]["kind"] == "workflow"
    assert workflow_runs.json()[0]["id"] == accepted.json()["run_id"]


async def test_agent_builder_generates_valid_definition(client, api, registry):
    headers = await api.headers("p8-builder@example.com")
    await _seed_model_catalog()
    generated = {
        "summary": "A small research flow.",
        "definition": {
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                {
                    "id": "ask",
                    "type": "llm",
                    "config": {
                        "provider_id": "fake",
                        "model": "fake-model",
                        "prompt": "Answer: {{input}}",
                    },
                    "ui": {"x": 240, "y": 80},
                },
                {"id": "out", "type": "output", "config": {}},
            ],
            "edges": [
                {"from": "start", "to": "ask"},
                {"from": "ask", "to": "out"},
            ],
        },
        "missing_resources": [],
    }
    registry.get("fake").complete_content = json.dumps(generated)

    response = await client.post(
        "/agent-builder/generate",
        json={
            "prompt": "Create a small research assistant",
            "provider_id": "fake",
            "model": "fake-model",
        },
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"] == "A small research flow."
    assert {node["type"] for node in payload["definition"]["nodes"]} == {
        "start",
        "llm",
        "output",
    }
    assert len(payload["definition"]["edges"]) == 2

    usage = await client.get("/usage/recent", headers=headers)
    assert any(item["source"] == "agent_builder" for item in usage.json())