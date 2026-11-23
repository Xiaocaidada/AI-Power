from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Workspace, WorkspaceMember
from app.services.memories import create_memory, get_memory_settings, select_memories


async def _enable_memory(client, headers):
    response = await client.patch(
        "/memories/settings",
        json={"enabled": True, "require_confirmation": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text


async def _ids(client, headers):
    me = await client.get("/auth/me", headers=headers)
    user_id = UUID(me.json()["id"])
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(Workspace.id)
                .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                .where(
                    WorkspaceMember.user_id == user_id,
                    Workspace.is_personal.is_(True),
                )
            )
        ).scalar_one()
    return user_id, row


async def test_chat_injects_memory_and_records_usage(client, api, registry):
    headers = await api.headers("p10s3-chat@example.com")
    await _enable_memory(client, headers)
    created = await client.post(
        "/memories",
        json={
            "content": "Prefers concise answers.",
            "title": "Style",
            "category": "preference",
            "scope_type": "global",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    memory_id = created.json()["id"]

    conversation = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]

    sent = await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "Please be concise."},
        headers=headers,
    )
    assert sent.status_code == 200, sent.text

    detail = await client.get(f"/conversations/{conversation_id}", headers=headers)
    assistant = next(
        item for item in detail.json()["messages"] if item["role"] == "assistant"
    )
    refs = assistant["memory_refs"]
    assert len(refs) == 1
    assert refs[0]["id"] == memory_id
    assert refs[0]["injected_chars"] > 0

    usage = await client.get("/memories/usage", headers=headers)
    assert usage.status_code == 200
    events = usage.json()
    assert len(events) == 1
    assert events[0]["memory_id"] == memory_id
    assert events[0]["context_type"] == "chat"
    assert events[0]["context_id"] == assistant["id"]


async def test_conversation_memory_switch_and_exclusion(client, api, registry):
    headers = await api.headers("p10s3-toggle@example.com")
    await _enable_memory(client, headers)
    created = await client.post(
        "/memories",
        json={
            "content": "Prefers concise answers.",
            "title": "Style",
            "category": "preference",
        },
        headers=headers,
    )
    memory_id = created.json()["id"]
    conversation = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )
    conversation_id = conversation.json()["id"]

    disabled = await client.patch(
        f"/conversations/{conversation_id}",
        json={"memory_enabled": False},
        headers=headers,
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["memory_enabled"] is False
    await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "Please be concise."},
        headers=headers,
    )
    detail = await client.get(f"/conversations/{conversation_id}", headers=headers)
    assistant = next(
        item for item in detail.json()["messages"] if item["role"] == "assistant"
    )
    assert assistant["memory_refs"] == []

    enabled = await client.patch(
        f"/conversations/{conversation_id}",
        json={
            "memory_enabled": True,
            "excluded_memory_ids": [memory_id],
        },
        headers=headers,
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["excluded_memory_ids"] == [memory_id]
    await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "Please be concise."},
        headers=headers,
    )
    detail = await client.get(f"/conversations/{conversation_id}", headers=headers)
    assistant = [
        item for item in detail.json()["messages"] if item["role"] == "assistant"
    ][-1]
    assert assistant["memory_refs"] == []


async def test_select_memories_scope_and_cross_model(client, api):
    headers = await api.headers("p10s3-select@example.com")
    user_id, workspace_id = await _ids(client, headers)
    project = await client.post(
        "/projects",
        json={
            "name": "Memory project",
            "default_provider_id": "auto",
            "default_model": "auto",
        },
        headers=headers,
    )
    project_id = UUID(project.json()["id"])
    other_project = await client.post(
        "/projects",
        json={
            "name": "Other project",
            "default_provider_id": "auto",
            "default_model": "auto",
        },
        headers=headers,
    )
    other_project_id = UUID(other_project.json()["id"])

    async with SessionLocal() as session:
        settings = await get_memory_settings(session, workspace_id, user_id)
        settings.enabled = True
        settings.allow_cross_model = False
        global_memory = await create_memory(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            content="Global preference for concise answers.",
            category="preference",
            scope_type="global",
        )
        project_memory = await create_memory(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            content="Project uses concise API answers.",
            category="project",
            scope_type="project",
            project_id=project_id,
        )
        other_memory = await create_memory(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            content="Other project uses verbose answers.",
            category="project",
            scope_type="project",
            project_id=other_project_id,
        )
        other_model = await create_memory(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            content="Another model answers concisely.",
            category="preference",
            scope_type="global",
            metadata={"provider_id": "other", "model": "other-model"},
        )
        await session.commit()

        selection = await select_memories(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            agent_id=None,
            project_id=project_id,
            query="concise answers",
            limit=10,
            max_chars=4000,
            provider_id="fake",
            model="fake-model",
            allow_cross_model=False,
        )
        ids = {item.memory.id for item in selection.items}
        assert global_memory.id in ids
        assert project_memory.id in ids
        assert other_memory.id not in ids
        assert other_model.id not in ids

        excluded = await select_memories(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            agent_id=None,
            project_id=project_id,
            query="concise answers",
            limit=10,
            max_chars=4000,
            excluded_ids=[global_memory.id, project_memory.id],
            allow_cross_model=True,
        )
        assert {item.memory.id for item in excluded.items} == {other_model.id}


async def test_select_memories_respects_char_budget(client, api):
    headers = await api.headers("p10s3-budget@example.com")
    user_id, workspace_id = await _ids(client, headers)
    async with SessionLocal() as session:
        for index in range(3):
            await create_memory(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
                content=f"Budget fact {index}: " + "x" * 80,
                title=f"Budget {index}",
                category="fact",
                scope_type="global",
            )
        await session.commit()
        selection = await select_memories(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            agent_id=None,
            query="budget",
            limit=10,
            max_chars=250,
        )
        assert 0 < len(selection.items) < 3
        assert len(selection.block) <= 250