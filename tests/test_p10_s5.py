from uuid import UUID


async def _memory(client, headers, **values):
    response = await client.post(
        "/memories",
        json={"content": values.pop("content"), **values},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _project(client, headers, name: str):
    response = await client.post("/projects", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_auto_relations_and_external_nodes(client, api):
    headers = await api.headers("p10s5-auto@example.com")
    first = await _memory(
        client,
        headers,
        title="Release note style",
        content="Prefers concise release notes for weekly updates.",
        category="preference",
    )
    second = await _memory(
        client,
        headers,
        title="Weekly note style",
        content="Prefers concise release notes for monthly reviews.",
        category="preference",
    )
    relations = await client.get(
        f"/memories/{second['id']}/relations", headers=headers
    )
    assert relations.status_code == 200
    rows = relations.json()
    related = [
        row
        for row in rows
        if row["to_type"] == "memory"
        and row["to_id"] in {first["id"], second["id"]}
        and row["source"] == "auto"
    ]
    assert related
    assert related[0]["relation_type"] == "related"
    assert related[0]["confidence"] >= 0.35
    assert "similarity" in related[0]["basis"]

    project = await _project(client, headers, "Graph project")
    project_memory = await _memory(
        client,
        headers,
        title="Project decision",
        content="This project uses PostgreSQL for storage.",
        category="project",
        scope_type="project",
        project_id=project["id"],
    )
    external = await client.get(
        f"/memories/{project_memory['id']}/relations", headers=headers
    )
    assert any(
        row["to_type"] == "project"
        and row["to_id"] == project["id"]
        and row["source"] == "auto"
        for row in external.json()
    )

    graph = await client.get("/memories/graph", headers=headers)
    assert graph.status_code == 200, graph.text
    payload = graph.json()
    node_ids = {node["id"] for node in payload["nodes"]}
    assert f"memory:{first['id']}" in node_ids
    assert f"memory:{second['id']}" in node_ids
    assert f"project:{project['id']}" in node_ids
    assert any(
        edge["source"] == f"memory:{project_memory['id']}"
        and edge["target"] == f"project:{project['id']}"
        for edge in payload["edges"]
    )
    assert payload["stats"]["memories"] == 3
    assert payload["stats"]["external"] == 1
    assert payload["stats"]["relations"] >= 2


async def test_graph_filters_and_focus(client, api):
    headers = await api.headers("p10s5-focus@example.com")
    global_memory = await _memory(
        client,
        headers,
        title="Global style",
        content="Prefers concise answers.",
        category="preference",
    )
    project = await _project(client, headers, "Filtered project")
    project_memory = await _memory(
        client,
        headers,
        title="Project fact",
        content="The project uses FastAPI.",
        category="project",
        scope_type="project",
        project_id=project["id"],
    )
    filtered = await client.get(
        "/memories/graph",
        params={"scope_type": "project", "project_id": project["id"]},
        headers=headers,
    )
    assert filtered.status_code == 200
    node_ids = {node["id"] for node in filtered.json()["nodes"]}
    assert f"memory:{project_memory['id']}" in node_ids
    assert f"memory:{global_memory['id']}" not in node_ids

    focused = await client.get(
        "/memories/graph",
        params={"focus_id": global_memory["id"]},
        headers=headers,
    )
    assert focused.status_code == 200
    focused_nodes = {node["id"] for node in focused.json()["nodes"]}
    assert f"memory:{global_memory['id']}" in focused_nodes
    assert f"memory:{project_memory['id']}" not in focused_nodes
    for edge in focused.json()["edges"]:
        assert edge["source"] in focused_nodes
        assert edge["target"] in focused_nodes


async def test_manual_relation_validation_and_delete(client, api):
    headers = await api.headers("p10s5-manual@example.com")
    other = await api.headers("p10s5-other@example.com")
    first = await _memory(client, headers, title="One", content="First unrelated note.")
    second = await _memory(client, headers, title="Two", content="Second unrelated note.")
    foreign_project = await _project(client, other, "Foreign project")

    self_link = await client.post(
        f"/memories/{first['id']}/relations",
        json={"to_type": "memory", "to_id": first["id"], "relation_type": "related"},
        headers=headers,
    )
    assert self_link.status_code == 422, self_link.text

    foreign = await client.post(
        f"/memories/{first['id']}/relations",
        json={
            "to_type": "project",
            "to_id": foreign_project["id"],
            "relation_type": "related",
        },
        headers=headers,
    )
    assert foreign.status_code == 404, foreign.text

    created = await client.post(
        f"/memories/{first['id']}/relations",
        json={
            "to_type": "memory",
            "to_id": second["id"],
            "relation_type": "supports",
            "basis": "manual link",
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    relation_id = created.json()["id"]
    listed = await client.get(f"/memories/{first['id']}/relations", headers=headers)
    assert relation_id in {row["id"] for row in listed.json()}

    deleted = await client.delete(
        f"/memories/relations/{relation_id}", headers=headers
    )
    assert deleted.status_code == 204
    after = await client.get(f"/memories/{first['id']}/relations", headers=headers)
    assert relation_id not in {row["id"] for row in after.json()}


async def test_graph_rebuild_backfills_relations(client, api):
    headers = await api.headers("p10s5-rebuild@example.com")
    first = await _memory(
        client,
        headers,
        title="Deploy checklist",
        content="Deploy checklist includes database migration.",
        category="technical",
        tags=["deploy"],
    )
    second = await _memory(
        client,
        headers,
        title="Release checklist",
        content="Deploy checklist includes database migration and smoke tests.",
        category="technical",
        tags=["deploy"],
    )
    all_relations = []
    for memory in (first, second):
        rows = await client.get(
            f"/memories/{memory['id']}/relations", headers=headers
        )
        all_relations.extend(rows.json())
    for relation in all_relations:
        await client.delete(f"/memories/relations/{relation['id']}", headers=headers)
    cleaned = await client.get(f"/memories/{second['id']}/relations", headers=headers)
    assert cleaned.json() == []

    rebuilt = await client.post("/memories/graph/rebuild", headers=headers)
    assert rebuilt.status_code == 200, rebuilt.text
    assert rebuilt.json()["created"] >= 1
    graph = await client.get("/memories/graph", headers=headers)
    endpoints = {
        (edge["source"], edge["target"]) for edge in graph.json()["edges"]
    }
    assert (
        (f"memory:{first['id']}", f"memory:{second['id']}") in endpoints
        or (f"memory:{second['id']}", f"memory:{first['id']}") in endpoints
    )
    assert f"memory:{first['id']}" == f"memory:{UUID(first['id'])}"