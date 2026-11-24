import json

VALID_DEFINITION = {
    "nodes": [
        {"id": "start", "type": "start", "config": {}},
        {"id": "out", "type": "output", "config": {}},
    ],
    "edges": [{"from": "start", "to": "out"}],
}


async def _memory(client, headers, title: str, content: str) -> dict:
    response = await client.post(
        "/memories",
        json={
            "title": title,
            "content": content,
            "category": "technical",
            "scope_type": "global",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_relation_type_and_basis_can_be_edited(client, api):
    headers = await api.headers("p11s13-relations@example.com")
    first = await _memory(client, headers, "Relation A", "alpha relation")
    second = await _memory(client, headers, "Relation B", "beta relation")
    created = await client.post(
        f"/memories/{first['id']}/relations",
        json={"to_id": second["id"], "relation_type": "related", "basis": "old"},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    relation_id = created.json()["id"]

    updated = await client.patch(
        f"/memories/relations/{relation_id}",
        json={"relation_type": "supports", "basis": "verified by test"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["relation_type"] == "supports"
    assert updated.json()["basis"] == "verified by test"

    invalid = await client.patch(
        f"/memories/relations/{relation_id}",
        json={"relation_type": "unknown"},
        headers=headers,
    )
    assert invalid.status_code == 422

    foreign = await api.headers("p11s13-relations-other@example.com")
    assert (
        await client.patch(
            f"/memories/relations/{relation_id}",
            json={"basis": "nope"},
            headers=foreign,
        )
    ).status_code == 404


async def test_builder_stream_emits_stages_and_result(
    client, api, registry, fake_provider
):
    headers = await api.headers("p11s13-builder@example.com")
    session = await client.post(
        "/agent-builder/sessions",
        json={
            "scope": "agent",
            "provider_id": "fake",
            "model": "fake-model",
            "draft_definition": VALID_DEFINITION,
        },
        headers=headers,
    )
    assert session.status_code == 201, session.text
    session_id = session.json()["id"]
    fake_provider.complete_content = json.dumps(
        {
            "message": "Streamed result",
            "summary": "Minimal flow",
            "definition": VALID_DEFINITION,
            "missing_resources": [],
            "suggestions": [],
        }
    )
    response = await client.post(
        f"/agent-builder/sessions/{session_id}/messages/stream",
        json={
            "kind": "modify",
            "prompt": "Build it",
            "current_definition": VALID_DEFINITION,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.text
    assert "event: stage" in body
    assert '"preparing"' in body
    assert '"generating"' in body
    assert '"finalizing"' in body
    assert "event: result" in body
    assert "Streamed result" in body


async def _create_kb(client, headers, name: str) -> str:
    response = await client.post(
        "/knowledge-bases", json={"name": name}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _upload(client, headers, kb_id: str, content: bytes) -> str:
    response = await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("doc.txt", content, "text/plain")},
        headers=headers,
    )
    assert response.status_code in {201, 202}, response.text
    return response.json()["id"]


async def _create_retrieval_workflow(client, headers, kb_id: str, name: str):
    nodes = [
        ("start", "start", {}),
        (
            "intent",
            "intent_classify",
            {
                "provider_id": "fake",
                "model": "fake-model",
                "categories": ["technical", "general"],
                "routes": {"technical": [kb_id]},
            },
        ),
        (
            "synonyms",
            "synonym_expand",
            {"provider_id": "fake", "model": "fake-model", "max_terms": 3},
        ),
        ("lexical", "lexical_search", {"top_k": 5}),
        ("context", "context", {"max_chars": 2000}),
        ("out", "output", {}),
    ]
    built = [
        {"id": node_id, "type": node_type, "config": config}
        for node_id, node_type, config in nodes
    ]
    edges = [
        {"from": nodes[index - 1][0], "to": nodes[index][0]}
        for index in range(1, len(nodes))
    ]
    response = await client.post(
        "/workflows",
        json={
            "name": name,
            "kind": "knowledge_retrieval",
            "definition": {"nodes": built, "edges": edges},
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_intent_and_synonym_nodes_route_and_expand(
    client, api, registry, fake_ingestion, fake_retrieval, fake_provider
):
    headers = await api.headers("p11s13-retrieval@example.com")
    kb_id = await _create_kb(client, headers, "P1 retrieval nodes")
    await _upload(client, headers, kb_id, b"database deployment guide")
    workflow = await _create_retrieval_workflow(
        client, headers, kb_id, "Intent and synonyms"
    )
    version_id = workflow["versions"][0]["id"]
    fake_provider.complete_contents = [
        "technical",
        "database\npostgres",
    ]
    response = await client.post(
        f"/knowledge-bases/{kb_id}/retrieval/test",
        json={
            "query": "where to deploy?",
            "workflow_version_id": version_id,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    node_types = [node["node_type"] for node in body["nodes"]]
    assert "intent_classify" in node_types
    assert "synonym_expand" in node_types
    assert "database" in body["rewritten_query"]
    assert body["results"]