from pathlib import Path
from uuid import UUID

import pytest

from app.config import get_settings
from app.db import SessionLocal
from app.models import Document, KnowledgeBase


@pytest.fixture(autouse=True)
def _registry(registry):
    yield registry


async def _team(client, alice, bob_email: str):
    team = await client.post("/workspaces", json={"name": "Assist team"}, headers=alice)
    team_id = team.json()["id"]
    assert (
        await client.post(
            f"/workspaces/{team_id}/members",
            json={"email": bob_email},
            headers=alice,
        )
    ).status_code == 201
    return {**alice, "X-Workspace-Id": team_id}


async def _kb(client, headers, name: str = "Docs"):
    response = await client.post("/knowledge-bases", json={"name": name}, headers=headers)
    assert response.status_code == 201
    return response.json()


async def test_prompt_category_and_per_user_favorites(client, api):
    alice = await api.headers("prompt-lib-alice@example.com")
    bob = await api.headers("prompt-lib-bob@example.com")
    alice_team = await _team(client, alice, "prompt-lib-bob@example.com")
    bob_team = {**bob, "X-Workspace-Id": alice_team["X-Workspace-Id"]}

    created = await client.post(
        "/prompt-templates",
        json={
            "name": "Support reply",
            "description": "Replies to customers",
            "category": "support",
            "system_prompt": "You are {{tone}}.",
        },
        headers=alice_team,
    )
    assert created.status_code == 201
    template = created.json()
    assert template["category"] == "support"
    assert template["favorite"] is False
    template_id = template["id"]

    filtered = await client.get(
        "/prompt-templates?category=support&q=support", headers=alice_team
    )
    assert [item["id"] for item in filtered.json()] == [template_id]
    assert (await client.get("/prompt-templates?category=other", headers=alice_team)).json() == []

    favorite = await client.post(
        f"/prompt-templates/{template_id}/favorite", headers=alice_team
    )
    assert favorite.status_code == 200
    assert favorite.json() == {"favorite": True}
    favorites = await client.get("/prompt-templates?favorite=true", headers=alice_team)
    assert [item["id"] for item in favorites.json()] == [template_id]

    bob_list = await client.get("/prompt-templates", headers=bob_team)
    assert bob_list.json()[0]["favorite"] is False
    assert (await client.get("/prompt-templates?favorite=true", headers=bob_team)).json() == []

    updated = await client.patch(
        f"/prompt-templates/{template_id}",
        json={"category": "sales", "name": "Sales reply"},
        headers=alice_team,
    )
    assert updated.status_code == 200
    assert updated.json()["category"] == "sales"
    assert updated.json()["name"] == "Sales reply"
    assert updated.json()["favorite"] is True

    unfavorite = await client.delete(
        f"/prompt-templates/{template_id}/favorite", headers=alice_team
    )
    assert unfavorite.json() == {"favorite": False}


async def test_dashboard_aggregates_workspace(client, api):
    headers = await api.headers("dashboard@example.com")
    await _kb(client, headers, "Dashboard KB")
    project = await client.post(
        "/projects", json={"name": "Dashboard project"}, headers=headers
    )
    assert project.status_code == 201
    agent = await client.post(
        "/agents", json={"name": "Dashboard agent", "instructions": "Help"}, headers=headers
    )
    assert agent.status_code == 201
    conversation = await client.post(
        "/conversations", json={"provider_id": "fake", "model": "fake-model"}, headers=headers
    )
    assert conversation.status_code == 201
    assert (
        await client.patch(
            f"/conversations/{conversation.json()['id']}",
            json={"title": "Dashboard chat"},
            headers=headers,
        )
    ).status_code == 200

    dashboard = await client.get("/dashboard", headers=headers)
    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["counts"]["conversations"] == 1
    assert body["counts"]["projects"] == 1
    assert body["counts"]["knowledge_bases"] == 1
    assert body["counts"]["agents"] == 1
    assert body["counts"]["requests_30d"] == 0
    assert [item["id"] for item in body["recent_conversations"]] == [
        conversation.json()["id"]
    ]
    assert [item["id"] for item in body["recent_projects"]] == [project.json()["id"]]


async def test_file_center_lists_and_downloads(client, api):
    alice = await api.headers("files-alice@example.com")
    bob = await api.headers("files-bob@example.com")
    kb = await _kb(client, alice, "Files KB")

    storage_name = "files-test.txt"
    upload_dir = Path(get_settings().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / storage_name).write_text("hello file center", encoding="utf-8")

    async with SessionLocal() as session:
        kb_row = await session.get(KnowledgeBase, UUID(kb["id"]))
        document = Document(
            workspace_id=kb_row.workspace_id,
            kb_id=kb_row.id,
            user_id=kb_row.user_id,
            filename="report.txt",
            mime="text/plain",
            size_bytes=17,
            content_hash="a" * 64,
            storage_path=storage_name,
            status="ready",
        )
        session.add(document)
        await session.commit()
        document_id = str(document.id)

    listed = await client.get("/files?q=report", headers=alice)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == document_id
    assert listed.json()[0]["kb_name"] == "Files KB"

    download = await client.get(f"/documents/{document_id}/download", headers=alice)
    assert download.status_code == 200
    assert download.content == b"hello file center"
    assert (await client.get(f"/documents/{document_id}/download", headers=bob)).status_code == 404


async def test_global_search_is_workspace_scoped(client, api):
    alice = await api.headers("search-alice@example.com")
    bob = await api.headers("search-bob@example.com")

    await _kb(client, alice, "needle kb")
    project = await client.post(
        "/projects", json={"name": "needle project"}, headers=alice
    )
    agent = await client.post(
        "/agents",
        json={"name": "needle agent", "instructions": "Find needles"},
        headers=alice,
    )
    prompt = await client.post(
        "/prompt-templates",
        json={"name": "needle prompt", "system_prompt": "Find {{thing}}."},
        headers=alice,
    )
    conversation = await client.post(
        "/conversations", json={"provider_id": "fake", "model": "fake-model"}, headers=alice
    )
    await client.patch(
        f"/conversations/{conversation.json()['id']}",
        json={"title": "needle chat"},
        headers=alice,
    )

    results = await client.get("/search?q=needle", headers=alice)
    assert results.status_code == 200
    found = results.json()["results"]
    assert {item["type"] for item in found} >= {
        "conversation",
        "project",
        "agent",
        "prompt",
        "knowledge_base",
    }
    assert str(project.json()["id"]) in {item["id"] for item in found}
    assert str(agent.json()["id"]) in {item["id"] for item in found}
    assert str(prompt.json()["id"]) in {item["id"] for item in found}

    bob_results = await client.get("/search?q=needle", headers=bob)
    assert bob_results.status_code == 200
    assert bob_results.json()["results"] == []