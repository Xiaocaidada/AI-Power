from uuid import UUID


async def _create_memory(client, headers, **overrides):
    body = {
        "content": "alpha preference for concise answers",
        "title": "Alpha preference",
        "category": "preference",
        "scope_type": "global",
        "tags": ["alpha"],
    }
    body.update(overrides)
    response = await client.post("/memories", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_memory_model_and_agent_allowlists(client, api):
    headers = await api.headers("p11s8-allowlist@example.com")
    memory = await _create_memory(client, headers)
    settings = await client.patch(
        "/memories/settings",
        json={
            "enabled": True,
            "allowed_provider_ids": ["allowed-provider"],
            "allowed_models": ["allowed-model"],
            "allowed_agent_ids": ["00000000-0000-0000-0000-000000000123"],
        },
        headers=headers,
    )
    assert settings.status_code == 200, settings.text

    from app.db import SessionLocal
    from app.models import AgentMemory
    from app.services.memories import select_memories

    async with SessionLocal() as session:
        row = await session.get(AgentMemory, UUID(memory["id"]))
        assert row is not None
        allowed = await select_memories(
            session,
            workspace_id=row.workspace_id,
            user_id=row.user_id,
            agent_id=None,
            query="alpha",
            limit=5,
            max_chars=2000,
            provider_id="allowed-provider",
            model="allowed-model",
            allowed_provider_ids=["allowed-provider"],
            allowed_models=["allowed-model"],
            allowed_agent_ids=["00000000-0000-0000-0000-000000000123"],
        )
        assert allowed.items
        denied_provider = await select_memories(
            session,
            workspace_id=row.workspace_id,
            user_id=row.user_id,
            agent_id=None,
            query="alpha",
            limit=5,
            max_chars=2000,
            provider_id="other-provider",
            model="allowed-model",
            allowed_provider_ids=["allowed-provider"],
            allowed_models=["allowed-model"],
            allowed_agent_ids=[],
        )
        assert denied_provider.items == []
        denied_agent = await select_memories(
            session,
            workspace_id=row.workspace_id,
            user_id=row.user_id,
            agent_id=UUID("00000000-0000-0000-0000-000000000999"),
            query="alpha",
            limit=5,
            max_chars=2000,
            provider_id="allowed-provider",
            model="allowed-model",
            allowed_provider_ids=["allowed-provider"],
            allowed_models=["allowed-model"],
            allowed_agent_ids=["00000000-0000-0000-0000-000000000123"],
        )
        assert denied_agent.items == []


async def test_quality_breadth_and_changes(client, api):
    headers = await api.headers("p11s8-quality@example.com")
    project_memory = await _create_memory(
        client,
        headers,
        title="Project notes",
        content="project context without a project binding",
        category="project",
        tags=[],
    )
    await _create_memory(
        client,
        headers,
        title="Orphan note",
        content="orphan beta content",
        category="fact",
        tags=[],
    )

    from app.db import SessionLocal
    from app.models import AgentMemory, MemoryRelation
    from app.services.memory_quality import analyze_memories, generate_suggestions

    async with SessionLocal() as session:
        row = await session.get(AgentMemory, UUID(project_memory["id"]))
        assert row is not None
        session.add(
            MemoryRelation(
                workspace_id=row.workspace_id,
                user_id=row.user_id,
                from_type="memory",
                from_id=row.id,
                to_type="memory",
                to_id=row.id,
                relation_type="contradicts",
                confidence=1.0,
                basis="test anomaly",
                source="manual",
            )
        )
        await session.commit()
        analysis = await analyze_memories(session, row.workspace_id, row.user_id)
        assert analysis["orphans"] >= 1
        assert analysis["relation_anomalies"] >= 1
        assert analysis["project_gaps"] >= 1
        result = await generate_suggestions(session, row.workspace_id, row.user_id)
        kinds = {suggestion.kind for suggestion in result["suggestions"]}
        assert {"link_orphans", "review_relations", "supplement_project"} <= kinds

    updated = await client.patch(
        f"/memories/{project_memory['id']}",
        json={"content": "project context changed and expanded"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    changes = await client.get("/memories/changes?days=30", headers=headers)
    assert changes.status_code == 200, changes.text
    assert changes.json()["total"] >= 1
    assert changes.json()["items"]


async def test_project_activity_extraction_source(client, api):
    headers = await api.headers("p11s8-project@example.com")
    settings = await client.patch(
        "/memories/settings",
        json={
            "enabled": True,
            "auto_extract": True,
            "allow_project_extract": True,
            "require_confirmation": True,
        },
        headers=headers,
    )
    assert settings.status_code == 200, settings.text
    project = await client.post(
        "/projects",
        json={
            "name": "P11 S8 Project",
            "description": "Project activity for memory extraction.",
            "instructions": "Always use the shared technical glossary for this project.",
        },
        headers=headers,
    )
    assert project.status_code == 201, project.text

    candidates = await client.get(
        "/memories/candidates?status=pending", headers=headers
    )
    assert candidates.status_code == 200, candidates.text
    rows = candidates.json()
    assert any(
        item["source_type"] == "project"
        and item["source_id"] == project.json()["id"]
        for item in rows
    )


async def test_memory_changes_endpoint_validates_workspace(client, api):
    headers = await api.headers("p11s8-changes@example.com")
    memory = await _create_memory(client, headers)
    updated = await client.patch(
        f"/memories/{memory['id']}",
        json={"content": "alpha preference updated with beta"},
        headers=headers,
    )
    assert updated.status_code == 200
    changes = await client.get("/memories/changes?days=30", headers=headers)
    assert changes.status_code == 200
    assert changes.json()["total"] >= 1

    other = await api.headers("p11s8-changes-other@example.com")
    foreign = await client.get(
        f"/memories/{memory['id']}/versions/diff", headers=other
    )
    assert foreign.status_code == 404