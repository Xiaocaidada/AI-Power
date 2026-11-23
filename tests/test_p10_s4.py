from uuid import UUID

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AgentMemory, CustomAgent, ModelCatalog, Workspace, WorkspaceMember
from app.services.custom_agents import build_agent_spec
from app.services.memories import create_memory, get_memory_settings, select_memories
from app.services.memory_permissions import agent_memory_access
from app.tools.base import ToolContext, ToolError
from app.tools.memory import MemorySaveArgs, MemorySearchArgs, memory_save, memory_search


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
        workspace_id = (
            await session.execute(
                select(Workspace.id)
                .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                .where(
                    WorkspaceMember.user_id == user_id,
                    Workspace.is_personal.is_(True),
                )
            )
        ).scalar_one()
    return user_id, workspace_id


async def _seed_model_catalog() -> None:
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


async def test_project_permissions_filter_global_memory(client, api, registry):
    headers = await api.headers("p10s4-project@example.com")
    await _enable_memory(client, headers)
    allowed = await client.post(
        "/projects",
        json={"name": "Allowed project", "allow_global_memory": True},
        headers=headers,
    )
    assert allowed.status_code == 201, allowed.text
    blocked = await client.post(
        "/projects",
        json={"name": "Blocked project", "allow_global_memory": False},
        headers=headers,
    )
    assert blocked.status_code == 201, blocked.text
    assert blocked.json()["allow_global_memory"] is False

    global_memory = await client.post(
        "/memories",
        json={
            "content": "Prefers concise answers.",
            "title": "Style",
            "category": "preference",
            "scope_type": "global",
        },
        headers=headers,
    )
    assert global_memory.status_code == 201, global_memory.text
    project_memory = await client.post(
        "/memories",
        json={
            "content": "This project keeps concise release notes.",
            "title": "Release notes",
            "category": "project",
            "scope_type": "project",
            "project_id": blocked.json()["id"],
        },
        headers=headers,
    )
    assert project_memory.status_code == 201, project_memory.text

    conversation = await client.post(
        "/conversations",
        json={
            "provider_id": "fake",
            "model": "fake-model",
            "project_id": blocked.json()["id"],
        },
        headers=headers,
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]
    sent = await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "Please keep concise answers."},
        headers=headers,
    )
    assert sent.status_code == 200, sent.text
    detail = await client.get(f"/conversations/{conversation_id}", headers=headers)
    assistant = [
        item for item in detail.json()["messages"] if item["role"] == "assistant"
    ][-1]
    ids = {item["id"] for item in assistant["memory_refs"]}
    assert project_memory.json()["id"] in ids
    assert global_memory.json()["id"] not in ids


async def test_agent_permissions_roundtrip_and_scope_selection(client, api):
    headers = await api.headers("p10s4-agent-perm@example.com")
    created = await client.post(
        "/agents",
        json={
            "name": "Scoped memory agent",
            "instructions": "Use memory carefully.",
            "memory_enabled": True,
            "memory_read_global": False,
            "memory_read_project": True,
            "memory_read_agent": True,
            "memory_write": True,
            "memory_write_scope": "agent",
            "memory_write_mode": "candidate",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["memory_read_global"] is False
    assert body["memory_write"] is True
    assert body["memory_write_scope"] == "agent"
    assert "memory_search" in build_agent_spec(
        await _agent_row(UUID(body["id"]))
    ).tools
    assert "memory_save" in build_agent_spec(
        await _agent_row(UUID(body["id"]))
    ).tools

    project = await client.post(
        "/projects", json={"name": "Scoped project"}, headers=headers
    )
    user_id, workspace_id = await _ids(client, headers)
    access = agent_memory_access(await _agent_row(UUID(body["id"])))
    async with SessionLocal() as session:
        settings = await get_memory_settings(session, workspace_id, user_id)
        settings.enabled = True
        global_memory = await create_memory(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            content="Global concise preference.",
            category="preference",
            scope_type="global",
        )
        project_memory = await create_memory(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            content="Project concise decision.",
            category="project",
            scope_type="project",
            project_id=UUID(project.json()["id"]),
        )
        agent_memory = await create_memory(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            content="Agent concise experience.",
            category="experience",
            scope_type="agent",
            agent_id=UUID(body["id"]),
        )
        await session.commit()
        selection = await select_memories(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            agent_id=UUID(body["id"]),
            project_id=UUID(project.json()["id"]),
            query="concise",
            limit=10,
            max_chars=4000,
            allowed_scopes=access.read_scopes,
        )
        ids = {item.memory.id for item in selection.items}
        assert global_memory.id not in ids
        assert project_memory.id in ids
        assert agent_memory.id in ids


async def test_agent_memory_tools_respect_write_permissions(client, api):
    headers = await api.headers("p10s4-tools@example.com")
    await _enable_memory(client, headers)
    user_id, workspace_id = await _ids(client, headers)
    project = await client.post(
        "/projects",
        json={
            "name": "Agent write project",
            "allow_agent_writes": True,
            "allow_global_memory": True,
        },
        headers=headers,
    )
    assert project.status_code == 201, project.text
    project_id = UUID(project.json()["id"])
    agent = await _create_agent_row(
        client,
        headers,
        "Tool agent",
        {
            "memory_enabled": True,
            "memory_write": True,
            "memory_write_scope": "agent",
            "memory_write_mode": "candidate",
        },
    )
    context = ToolContext(
        workspace_id=workspace_id,
        user_id=user_id,
        conversation_id=None,
        agent_id=agent.id,
        project_id=project_id,
        memory_access=agent_memory_access(agent),
    )
    saved = await memory_save(
        context,
        MemorySaveArgs(
            title="Candidate lesson",
            content="Agent learned to confirm before release.",
            category="experience",
        ),
    )
    assert "candidate" in saved
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(AgentMemory).where(AgentMemory.title == "Candidate lesson")
            )
        ).scalar_one()
        assert row.status == "candidate"
        assert row.scope_type == "agent"
        assert row.agent_id == agent.id
        row.status = "active"
        await session.commit()

        search = await memory_search(
            context, MemorySearchArgs(query="confirm release", limit=5)
        )
        assert "confirm before release" in search
        await session.refresh(row)
        assert row.use_count == 1

    read_only = await _create_agent_row(
        client,
        headers,
        "Read-only agent",
        {"memory_enabled": True, "memory_write": False},
    )
    denied_context = ToolContext(
        workspace_id=workspace_id,
        user_id=user_id,
        agent_id=read_only.id,
        memory_access=agent_memory_access(read_only),
    )
    with pytest.raises(ToolError) as denied:
        await memory_save(
            denied_context,
            MemorySaveArgs(title="Denied", content="Should not be saved."),
        )
    assert denied.value.code == "memory_write_denied"

    blocked_project = await client.post(
        "/projects",
        json={"name": "Writes blocked", "allow_agent_writes": False},
        headers=headers,
    )
    project_agent = await _create_agent_row(
        client,
        headers,
        "Project writer",
        {
            "memory_enabled": True,
            "memory_write": True,
            "memory_write_scope": "project",
            "memory_write_mode": "create",
        },
    )
    blocked_context = ToolContext(
        workspace_id=workspace_id,
        user_id=user_id,
        agent_id=project_agent.id,
        project_id=UUID(blocked_project.json()["id"]),
        memory_access=agent_memory_access(project_agent),
    )
    with pytest.raises(ToolError) as blocked:
        await memory_save(
            blocked_context,
            MemorySaveArgs(title="Blocked", content="Project blocks writes."),
        )
    assert blocked.value.code == "memory_write_denied"


async def test_workflow_project_memory_upsert_and_read(client, api):
    headers = await api.headers("p10s4-workflow@example.com")
    await _enable_memory(client, headers)
    await _seed_model_catalog()
    project = await client.post(
        "/projects", json={"name": "Workflow memory project"}, headers=headers
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    definition = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "remember",
                "type": "memory_write",
                "config": {
                    "title": "Release plan",
                    "content": "{{input}}",
                    "scope_type": "project",
                    "project_id": project_id,
                    "kind": "summary",
                    "upsert": True,
                },
            },
            {
                "id": "recall",
                "type": "memory_read",
                "config": {
                    "query": "release plan",
                    "scope_type": "project",
                    "project_id": project_id,
                },
            },
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": "remember"},
            {"from": "remember", "to": "recall"},
            {"from": "recall", "to": "out"},
        ],
    }
    workflow = await client.post(
        "/workflows",
        json={"name": "P10 S4 memory", "description": "scope", "definition": definition},
        headers=headers,
    )
    assert workflow.status_code == 201, workflow.text
    workflow_id = workflow.json()["id"]
    first = await client.post(
        f"/workflows/{workflow_id}/runs",
        json={"input": "Ship on Friday."},
        headers=headers,
    )
    assert first.status_code == 202, first.text
    detail = await client.get(
        f"/workflows/runs/{first.json()['run_id']}", headers=headers
    )
    assert detail.json()["status"] == "completed"

    memories = await client.get(
        "/memories",
        params={"scope_type": "project", "project_id": project_id},
        headers=headers,
    )
    assert memories.status_code == 200
    rows = memories.json()
    assert len(rows) == 1
    memory_id = rows[0]["id"]
    assert rows[0]["content"] == "Ship on Friday."

    second = await client.post(
        f"/workflows/{workflow_id}/runs",
        json={"input": "Ship on Monday."},
        headers=headers,
    )
    assert second.status_code == 202, second.text
    await client.get(f"/workflows/runs/{second.json()['run_id']}", headers=headers)
    refreshed = await client.get(f"/memories/{memory_id}", headers=headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["content"] == "Ship on Monday."
    assert refreshed.json()["version"] == 2


async def test_cross_workspace_project_memory_is_404(client, api):
    owner = await api.headers("p10s4-owner@example.com")
    intruder = await api.headers("p10s4-intruder@example.com")
    project = await client.post(
        "/projects", json={"name": "Private project"}, headers=owner
    )
    assert project.status_code == 201, project.text
    denied = await client.post(
        "/memories",
        json={
            "content": "Should not be visible.",
            "scope_type": "project",
            "project_id": project.json()["id"],
        },
        headers=intruder,
    )
    assert denied.status_code == 404, denied.text


async def _agent_row(agent_id: UUID) -> CustomAgent:
    async with SessionLocal() as session:
        return await session.get(CustomAgent, agent_id)


async def _create_agent_row(
    client, headers, name: str, permissions: dict
) -> CustomAgent:
    created = await client.post(
        "/agents",
        json={
            "name": name,
            "instructions": "Use tools when relevant.",
            **permissions,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return await _agent_row(UUID(created.json()["id"]))