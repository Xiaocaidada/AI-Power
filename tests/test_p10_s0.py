async def _memory(client, headers, **overrides):
    payload = {
        "content": "Prefers concise Chinese answers.",
        "title": "Style",
        "category": "preference",
        "scope_type": "global",
        "importance": 4,
        "tags": ["style"],
        **overrides,
    }
    response = await client.post("/memories", json=payload, headers=headers)
    return response


async def test_memory_settings_default_off_and_update(client, api):
    headers = await api.headers("p10-settings@example.com")
    defaults = await client.get("/memories/settings", headers=headers)
    assert defaults.status_code == 200, defaults.text
    body = defaults.json()
    assert body["enabled"] is False
    assert body["require_confirmation"] is True
    assert body["auto_save"] is False
    assert body["max_inject_items"] == 8

    updated = await client.patch(
        "/memories/settings",
        json={
            "enabled": True,
            "auto_save": True,
            "allowed_categories": ["preference", "project"],
            "max_inject_items": 5,
            "blocked_topics": ["password", "bank card"],
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    saved = updated.json()
    assert saved["enabled"] is True
    assert saved["auto_save"] is True
    assert saved["allowed_categories"] == ["preference", "project"]
    assert saved["max_inject_items"] == 5
    assert saved["blocked_topics"] == ["password", "bank card"]


async def test_memory_categories_scopes_filters_and_stats(client, api):
    headers = await api.headers("p10-filters@example.com")
    project = await client.post(
        "/projects",
        json={
            "name": "Memory project",
            "default_provider_id": "auto",
            "default_model": "auto",
        },
        headers=headers,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    global_memory = await _memory(client, headers)
    project_memory = await _memory(
        client,
        headers,
        title="Stack",
        content="Project uses FastAPI and PostgreSQL.",
        category="project",
        scope_type="project",
        project_id=project_id,
        tags=["stack"],
        favorite=True,
        pinned=True,
    )
    assert global_memory.status_code == 201, global_memory.text
    assert project_memory.status_code == 201, project_memory.text
    project_body = project_memory.json()
    assert project_body["metadata"] == {}
    assert project_body["scope_type"] == "project"
    assert project_body["project_id"] == project_id
    assert project_body["favorite"] is True
    assert project_body["tags"] == ["stack"]

    by_scope = await client.get("/memories?scope_type=project", headers=headers)
    assert [row["id"] for row in by_scope.json()] == [project_body["id"]]
    by_category = await client.get("/memories?category=preference", headers=headers)
    assert [row["id"] for row in by_category.json()] == [
        global_memory.json()["id"]
    ]
    by_tag = await client.get("/memories?tag=stack", headers=headers)
    assert [row["id"] for row in by_tag.json()] == [project_body["id"]]
    favorites = await client.get("/memories?favorite=true", headers=headers)
    assert [row["id"] for row in favorites.json()] == [project_body["id"]]
    pinned = await client.get("/memories?pinned=true", headers=headers)
    assert [row["id"] for row in pinned.json()] == [project_body["id"]]

    stats = await client.get("/memories/stats", headers=headers)
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert body["total"] == 2
    assert body["active"] == 2
    assert body["by_scope"]["global"] == 1
    assert body["by_scope"]["project"] == 1
    assert body["by_category"]["project"] == 1


async def test_project_memory_requires_project_and_secrets_are_blocked(client, api):
    headers = await api.headers("p10-validate@example.com")
    missing = await _memory(
        client, headers, content="Orphan project memory", scope_type="project"
    )
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "invalid_scope"

    secret = await _memory(
        client, headers, content="api_key = sk-abcdef123456"
    )
    assert secret.status_code == 422
    assert secret.json()["detail"]["code"] == "secret_blocked"


async def test_memory_versions_and_restore(client, api):
    headers = await api.headers("p10-versions@example.com")
    created = await _memory(client, headers, content="First version.")
    assert created.status_code == 201
    memory_id = created.json()["id"]

    updated = await client.patch(
        f"/memories/{memory_id}",
        json={"content": "Second version.", "change_reason": "refine"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2

    versions = await client.get(f"/memories/{memory_id}/versions", headers=headers)
    assert versions.status_code == 200
    assert [row["version"] for row in versions.json()] == [2, 1]
    assert versions.json()[1]["snapshot"]["content"] == "First version."

    restored = await client.post(
        f"/memories/{memory_id}/versions/1/restore", headers=headers
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["content"] == "First version."
    assert restored.json()["version"] == 3


async def test_memory_relations_and_batch_updates(client, api):
    headers = await api.headers("p10-relations@example.com")
    first = await _memory(client, headers, title="One", content="First memory.")
    second = await _memory(client, headers, title="Two", content="Second memory.")
    first_id = first.json()["id"]
    second_id = second.json()["id"]

    relation = await client.post(
        f"/memories/{first_id}/relations",
        json={
            "to_type": "memory",
            "to_id": second_id,
            "relation_type": "supports",
            "basis": "both describe style",
        },
        headers=headers,
    )
    assert relation.status_code == 200, relation.text
    relation_id = relation.json()["id"]
    listed = await client.get(f"/memories/{first_id}/relations", headers=headers)
    assert [row["id"] for row in listed.json()] == [relation_id]

    deleted = await client.delete(
        f"/memories/{first_id}/relations/{relation_id}", headers=headers
    )
    assert deleted.status_code == 204

    batch = await client.post(
        "/memories/batch",
        json={"ids": [first_id, second_id], "status": "archived"},
        headers=headers,
    )
    assert batch.status_code == 200, batch.text
    assert batch.json()["updated"] == 2
    archived = await client.get("/memories?status=archived", headers=headers)
    assert {row["id"] for row in archived.json()} == {first_id, second_id}


async def test_memory_isolation(client, api):
    owner = await api.headers("p10-owner@example.com")
    other = await api.headers("p10-other@example.com")
    created = await _memory(client, owner)
    memory_id = created.json()["id"]
    assert (await client.get(f"/memories/{memory_id}", headers=other)).status_code == 404
    assert (
        await client.patch(
            f"/memories/{memory_id}", json={"content": "hijack"}, headers=other
        )
    ).status_code == 404
    assert (
        await client.get(f"/memories/{memory_id}/versions", headers=other)
    ).status_code == 404