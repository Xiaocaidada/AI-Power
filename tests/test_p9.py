async def _create_kb(client, headers, name="P9 KB"):
    return await client.post("/knowledge-bases", json={"name": name}, headers=headers)


async def _upload(client, headers, kb_id, content=b"alpha beta gamma delta epsilon zeta eta theta"):
    return await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("note.txt", content, "text/plain")},
        headers=headers,
    )


def _pipeline_definition() -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "parse", "type": "parse_document", "config": {}},
            {"id": "clean", "type": "clean_text", "config": {}},
            {
                "id": "chunk",
                "type": "chunk_text",
                "config": {
                    "strategy": "fixed",
                    "chunk_size": 50,
                    "chunk_overlap": 10,
                    "min_chars": 0,
                },
            },
            {"id": "embed", "type": "embed_chunks", "config": {}},
            {"id": "index", "type": "index_knowledge", "config": {}},
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": "parse"},
            {"from": "parse", "to": "clean"},
            {"from": "clean", "to": "chunk"},
            {"from": "chunk", "to": "embed"},
            {"from": "embed", "to": "index"},
            {"from": "index", "to": "out"},
        ],
    }


async def test_knowledge_process_preview_apply_and_binding(
    client, api, fake_ingestion, fake_retrieval
):
    headers = await api.headers("p9-process@example.com")
    kb = await _create_kb(client, headers)
    assert kb.status_code == 201
    kb_id = kb.json()["id"]

    created = await client.post(
        "/workflows",
        json={
            "name": "Technical docs",
            "description": "P9 process",
            "kind": "knowledge_process",
            "definition": _pipeline_definition(),
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    workflow = created.json()
    assert workflow["kind"] == "knowledge_process"
    workflow_id = workflow["id"]
    version_id = workflow["versions"][0]["id"]

    catalog = await client.get("/workflows/catalog?kind=knowledge_process", headers=headers)
    assert catalog.status_code == 200
    types = {item["type"] for item in catalog.json()["nodes"]}
    assert (
        {"start", "parse_document", "chunk_text", "embed_chunks", "index_knowledge", "output"}
        <= types
    )
    assert catalog.json()["templates"]

    document = await _upload(client, headers, kb_id)
    assert document.status_code == 202
    document_id = document.json()["id"]

    started = await client.post(
        f"/workflows/{workflow_id}/runs",
        json={"document_id": document_id},
        headers=headers,
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]

    detail = await client.get(f"/workflows/runs/{run_id}", headers=headers)
    payload = detail.json()
    assert payload["status"] == "completed", payload
    assert payload["output_payload"]["draft_count"] >= 1
    assert payload["applied_at"] is None

    preview = await client.get(
        f"/knowledge-bases/{kb_id}/processing/runs/{run_id}/preview",
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["draft_count"] >= 1
    assert body["applied"] is False
    kinds = {artifact["kind"] for artifact in body["artifacts"]}
    assert {"parsed", "chunks", "index"} <= kinds
    chunks = next(
        artifact for artifact in body["artifacts"] if artifact["kind"] == "chunks"
    )
    assert chunks["payload"]["chunks"]
    assert body["drafts"][0]["embedded"] is True

    bound = await client.put(
        f"/knowledge-bases/{kb_id}/processing/binding",
        json={"workflow_version_id": version_id},
        headers=headers,
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["workflow_id"] == workflow_id
    binding = await client.get(
        f"/knowledge-bases/{kb_id}/processing/binding", headers=headers
    )
    assert binding.json()["workflow_version_id"] == version_id

    applied = await client.post(
        f"/knowledge-bases/{kb_id}/processing/runs/{run_id}/apply",
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["chunks"] >= 1
    final = await client.get(f"/workflows/runs/{run_id}", headers=headers)
    assert final.json()["applied_at"] is not None
    document_detail = await client.get(f"/documents/{document_id}", headers=headers)
    assert document_detail.json()["status"] == "ready"

    applied_preview = await client.get(
        f"/knowledge-bases/{kb_id}/processing/runs/{run_id}/preview",
        headers=headers,
    )
    assert applied_preview.json()["applied"] is True


async def test_knowledge_process_rejects_branches_and_missing_document(
    client, api, fake_ingestion
):
    headers = await api.headers("p9-invalid@example.com")
    kb = await _create_kb(client, headers, name="Invalid KB")
    kb_id = kb.json()["id"]

    branched = _pipeline_definition()
    branched["edges"].append({"from": "parse", "to": "embed"})
    rejected = await client.post(
        "/workflows",
        json={
            "name": "Branched",
            "kind": "knowledge_process",
            "definition": branched,
        },
        headers=headers,
    )
    assert rejected.status_code == 422

    created = await client.post(
        "/workflows",
        json={
            "name": "No document",
            "kind": "knowledge_process",
            "definition": _pipeline_definition(),
        },
        headers=headers,
    )
    assert created.status_code == 201
    workflow_id = created.json()["id"]
    missing = await client.post(
        f"/workflows/{workflow_id}/runs", json={}, headers=headers
    )
    assert missing.status_code == 422

    other_kb = await _create_kb(client, headers, name="Other KB")
    other_document = await _upload(client, headers, other_kb.json()["id"])
    mismatch = await client.post(
        f"/workflows/{workflow_id}/runs",
        json={"document_id": other_document.json()["id"], "kb_id": kb_id},
        headers=headers,
    )
    assert mismatch.status_code == 422


async def test_knowledge_process_cannot_run_agent_workflow_kind(client, api):
    headers = await api.headers("p9-agent@example.com")
    definition = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [{"from": "start", "to": "out"}],
    }
    created = await client.post(
        "/workflows",
        json={"name": "Agent only", "kind": "agent", "definition": definition},
        headers=headers,
    )
    assert created.status_code == 201
    listed = await client.get("/workflows?kind=knowledge_process", headers=headers)
    assert listed.status_code == 200
    assert all(item["kind"] == "knowledge_process" for item in listed.json())
