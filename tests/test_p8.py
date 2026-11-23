import json

from sqlalchemy import select


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