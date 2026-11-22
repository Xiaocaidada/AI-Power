import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import UsageEvent


@pytest.fixture(autouse=True)
def _registry(registry):
    """Every project test uses the fake provider registry override."""
    yield registry


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
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


async def _project(client, headers, **overrides):
    payload = {"name": "Demo project"}
    payload.update(overrides)
    return await client.post("/projects", json=payload, headers=headers)


async def _conversation(client, headers, **payload):
    return await client.post("/conversations", json=payload, headers=headers)


async def _send(client, headers, conversation_id, content):
    return await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": content},
        headers=headers,
    )


def _team_headers(headers: dict[str, str], workspace_id: str) -> dict[str, str]:
    return {**headers, "X-Workspace-Id": workspace_id}


async def test_project_crud_and_isolation(client, api):
    alice = await api.headers("project-alice@example.com")
    bob = await api.headers("project-bob@example.com")

    created = await _project(
        client,
        alice,
        name="Research",
        description="Deep dives",
        instructions="Be concise",
        default_provider_id="fake",
        default_model="fake-model",
    )
    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Research"
    assert body["owned"] is True
    project_id = body["id"]

    listed = await client.get("/projects", headers=alice)
    assert [item["id"] for item in listed.json()] == [project_id]
    detail = await client.get(f"/projects/{project_id}", headers=alice)
    assert detail.status_code == 200
    assert detail.json()["instructions"] == "Be concise"

    assert (await client.get(f"/projects/{project_id}", headers=bob)).status_code == 404
    assert (await client.get("/projects", headers=bob)).json() == []


async def test_team_members_can_read_but_not_edit_projects(client, api):
    alice = await api.headers("project-team-alice@example.com")
    bob = await api.headers("project-team-bob@example.com")
    team = await client.post("/workspaces", json={"name": "Project team"}, headers=alice)
    team_id = team.json()["id"]
    invited = await client.post(
        f"/workspaces/{team_id}/members",
        json={"email": "project-team-bob@example.com"},
        headers=alice,
    )
    assert invited.status_code == 201
    alice_team = _team_headers(alice, team_id)
    bob_team = _team_headers(bob, team_id)

    created = await _project(client, alice_team, name="Shared")
    project_id = created.json()["id"]

    bob_list = await client.get("/projects", headers=bob_team)
    assert [item["id"] for item in bob_list.json()] == [project_id]
    assert bob_list.json()[0]["owned"] is False
    assert (
        await client.patch(
            f"/projects/{project_id}", json={"name": "Hijack"}, headers=bob_team
        )
    ).status_code == 403
    assert (
        await client.delete(f"/projects/{project_id}", headers=bob_team)
    ).status_code == 403

    inherited = await _conversation(client, bob_team, project_id=project_id)
    assert inherited.status_code == 201


async def test_project_defaults_and_instruction_snapshot(client, api, fake_provider):
    headers = await api.headers("project-inherit@example.com")
    created = await _project(
        client,
        headers,
        instructions="Always answer in Chinese.",
        default_provider_id="fake",
        default_model="fake-model",
    )
    project_id = created.json()["id"]

    conversation = await _conversation(client, headers, project_id=project_id)
    assert conversation.status_code == 201
    body = conversation.json()
    assert body["provider_id"] == "fake"
    assert body["model"] == "fake-model"
    assert body["project_id"] == project_id

    conversation_id = body["id"]
    assert (await _send(client, headers, conversation_id, "Hello")).status_code == 200
    first_system = fake_provider.calls[-1][0][0]
    assert first_system.role == "system"
    assert "Always answer in Chinese." in first_system.content

    assert (
        await client.patch(
            f"/projects/{project_id}",
            json={"instructions": "NEW INSTRUCTIONS"},
            headers=headers,
        )
    ).status_code == 200
    assert (await _send(client, headers, conversation_id, "Again")).status_code == 200
    second_system = fake_provider.calls[-1][0][0]
    assert "Always answer in Chinese." in second_system.content
    assert "NEW INSTRUCTIONS" not in second_system.content


async def test_invalid_project_defaults_are_rejected(client, api):
    headers = await api.headers("project-invalid@example.com")

    missing_model = await _project(client, headers, default_provider_id="fake")
    assert missing_model.status_code == 422

    unknown_provider = await _project(
        client, headers, default_provider_id="missing", default_model="m"
    )
    assert unknown_provider.status_code == 404


async def test_conversation_search_pin_archive_and_project_filter(client, api):
    headers = await api.headers("conversation-manage@example.com")
    project = await _project(client, headers, name="Manage")
    project_id = project.json()["id"]

    first = await _conversation(client, headers, provider_id="fake", model="fake-model")
    second = await _conversation(client, headers, provider_id="fake", model="fake-model")
    first_id = first.json()["id"]
    second_id = second.json()["id"]
    await _send(client, headers, first_id, "alpha topic")
    await _send(client, headers, second_id, "beta topic")
    await _send(client, headers, second_id, "contains-needle")

    by_title = (await client.get("/conversations?q=alpha", headers=headers)).json()
    assert [item["id"] for item in by_title] == [first_id]
    by_message = (await client.get("/conversations?q=needle", headers=headers)).json()
    assert [item["id"] for item in by_message] == [second_id]

    pinned = await client.patch(
        f"/conversations/{second_id}", json={"pinned": True}, headers=headers
    )
    assert pinned.status_code == 200
    assert pinned.json()["pinned"] is True
    pinned_list = (await client.get("/conversations?pinned=true", headers=headers)).json()
    assert [item["id"] for item in pinned_list] == [second_id]

    archived = await client.patch(
        f"/conversations/{first_id}", json={"archived": True}, headers=headers
    )
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    active_ids = {
        item["id"] for item in (await client.get("/conversations", headers=headers)).json()
    }
    assert first_id not in active_ids
    archived_ids = {
        item["id"]
        for item in (
            await client.get("/conversations?archived=true", headers=headers)
        ).json()
    }
    assert first_id in archived_ids

    moved = await client.patch(
        f"/conversations/{second_id}", json={"project_id": project_id}, headers=headers
    )
    assert moved.status_code == 200
    assert moved.json()["project_id"] == project_id
    scoped = (
        await client.get(f"/conversations?project_id={project_id}", headers=headers)
    ).json()
    assert [item["id"] for item in scoped] == [second_id]


async def test_conversation_batch_operations(client, api):
    alice = await api.headers("batch-alice@example.com")
    bob = await api.headers("batch-bob@example.com")
    project = await _project(client, alice, name="Batch")
    project_id = project.json()["id"]

    ids = []
    for _ in range(3):
        created = await _conversation(
            client, alice, provider_id="fake", model="fake-model"
        )
        ids.append(created.json()["id"])

    archived = await client.post(
        "/conversations/batch",
        json={"action": "archive", "conversation_ids": ids[:2]},
        headers=alice,
    )
    assert archived.status_code == 200
    assert archived.json() == {"updated": 2}
    archived_ids = {
        item["id"]
        for item in (
            await client.get("/conversations?archived=true", headers=alice)
        ).json()
    }
    assert set(ids[:2]) <= archived_ids

    restored = await client.post(
        "/conversations/batch",
        json={"action": "unarchive", "conversation_ids": [ids[0]]},
        headers=alice,
    )
    assert restored.status_code == 200
    active_ids = {
        item["id"] for item in (await client.get("/conversations", headers=alice)).json()
    }
    assert ids[0] in active_ids

    moved = await client.post(
        "/conversations/batch",
        json={
            "action": "move",
            "conversation_ids": [ids[1]],
            "project_id": project_id,
        },
        headers=alice,
    )
    assert moved.status_code == 200

    foreign = await client.post(
        "/conversations/batch",
        json={"action": "archive", "conversation_ids": [ids[0]]},
        headers=bob,
    )
    assert foreign.status_code == 404

    missing = await client.post(
        "/conversations/batch",
        json={"action": "archive", "conversation_ids": [str(uuid4())]},
        headers=alice,
    )
    assert missing.status_code == 404


async def test_regenerate_appends_message_and_usage(client, api, fake_provider):
    headers = await api.headers("regenerate@example.com")
    created = await _conversation(client, headers, provider_id="fake", model="fake-model")
    conversation_id = created.json()["id"]
    assert (await _send(client, headers, conversation_id, "Hello")).status_code == 200
    detail = (await client.get(f"/conversations/{conversation_id}", headers=headers)).json()
    original_id = detail["messages"][1]["id"]

    response = await client.post(
        f"/conversations/{conversation_id}/messages/{original_id}/regenerate",
        headers=headers,
    )
    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert "done" in [event for event, _ in events]

    regenerated = (
        await client.get(f"/conversations/{conversation_id}", headers=headers)
    ).json()
    assert [message["role"] for message in regenerated["messages"]] == [
        "user",
        "assistant",
        "assistant",
    ]
    assert regenerated["messages"][2]["reply_to_message_id"] == original_id
    assert regenerated["messages"][2]["content"] == "Hello"

    second_history = fake_provider.calls[-1][0]
    assert [message.role for message in second_history] == ["user"]
    assert second_history[0].content == "Hello"

    async with SessionLocal() as session:
        usage_count = (
            await session.execute(
                select(func.count())
                .select_from(UsageEvent)
                .where(UsageEvent.conversation_id == UUID(conversation_id))
            )
        ).scalar_one()
    assert usage_count == 2


async def test_generation_settings_are_clamped_and_passed(client, api, fake_provider):
    headers = await api.headers("generation@example.com")
    created = await _conversation(client, headers, provider_id="fake", model="fake-model")
    conversation_id = created.json()["id"]

    updated = await client.patch(
        f"/conversations/{conversation_id}",
        json={"generation_settings": {"temperature": 5, "max_tokens": 999999, "top_p": -1}},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["generation_settings"] == {
        "temperature": 2.0,
        "max_tokens": 32768,
        "top_p": 0.0,
    }

    assert (await _send(client, headers, conversation_id, "Hi")).status_code == 200
    assert fake_provider.opts_calls[-1] == {
        "temperature": 2.0,
        "max_tokens": 32768,
        "top_p": 0.0,
    }


async def test_message_feedback_is_per_user(client, api):
    alice = await api.headers("feedback-alice@example.com")
    bob = await api.headers("feedback-bob@example.com")
    team = await client.post("/workspaces", json={"name": "Feedback team"}, headers=alice)
    team_id = team.json()["id"]
    assert (
        await client.post(
            f"/workspaces/{team_id}/members",
            json={"email": "feedback-bob@example.com"},
            headers=alice,
        )
    ).status_code == 201
    alice_team = _team_headers(alice, team_id)
    bob_team = _team_headers(bob, team_id)

    created = await _conversation(
        client, alice_team, provider_id="fake", model="fake-model"
    )
    conversation_id = created.json()["id"]
    assert (await _send(client, alice_team, conversation_id, "Hi")).status_code == 200
    detail = (
        await client.get(f"/conversations/{conversation_id}", headers=alice_team)
    ).json()
    assistant_id = detail["messages"][1]["id"]

    up = await client.put(
        f"/messages/{assistant_id}/feedback",
        json={"rating": "up", "reason": "useful"},
        headers=alice_team,
    )
    assert up.status_code == 200
    down = await client.put(
        f"/messages/{assistant_id}/feedback", json={"rating": "down"}, headers=bob_team
    )
    assert down.status_code == 200

    alice_detail = (
        await client.get(f"/conversations/{conversation_id}", headers=alice_team)
    ).json()
    bob_detail = (
        await client.get(f"/conversations/{conversation_id}", headers=bob_team)
    ).json()
    assert alice_detail["messages"][1]["feedback"]["rating"] == "up"
    assert bob_detail["messages"][1]["feedback"]["rating"] == "down"

    changed = await client.put(
        f"/messages/{assistant_id}/feedback",
        json={"rating": "down", "reason": "changed"},
        headers=alice_team,
    )
    assert changed.json()["rating"] == "down"
    removed = await client.delete(f"/messages/{assistant_id}/feedback", headers=bob_team)
    assert removed.status_code == 204
    bob_after = (
        await client.get(f"/conversations/{conversation_id}", headers=bob_team)
    ).json()
    assert bob_after["messages"][1]["feedback"] is None