from uuid import UUID


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


async def test_bound_workflow_runs_on_upload_and_reprocess(
    client, api, fake_retrieval
):
    headers = await api.headers("p9-auto@example.com")
    kb = await _create_kb(client, headers, name="Auto KB")
    kb_id = kb.json()["id"]

    created = await client.post(
        "/workflows",
        json={
            "name": "Auto process",
            "kind": "knowledge_process",
            "definition": _pipeline_definition(),
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    workflow = created.json()
    version_id = workflow["versions"][0]["id"]
    bound = await client.put(
        f"/knowledge-bases/{kb_id}/processing/binding",
        json={"workflow_version_id": version_id},
        headers=headers,
    )
    assert bound.status_code == 200, bound.text

    uploaded = await _upload(
        client,
        headers,
        kb_id,
        content=b"one two three four five six seven eight nine ten eleven twelve",
    )
    assert uploaded.status_code == 202, uploaded.text
    document_id = uploaded.json()["id"]
    detail = await client.get(f"/documents/{document_id}", headers=headers)
    assert detail.json()["status"] == "ready", detail.text

    runs = await client.get(
        f"/knowledge-bases/{kb_id}/processing/runs?document_id={document_id}",
        headers=headers,
    )
    assert runs.status_code == 200, runs.text
    assert runs.json()
    run = runs.json()[0]
    assert run["status"] == "completed"
    assert run["applied_at"] is not None
    assert run["input_payload"]["document_id"] == document_id

    from app.db import SessionLocal
    from app.models import Document

    async with SessionLocal() as session:
        stored = await session.get(Document, UUID(document_id))
        assert stored is not None
        assert stored.process_version_id is not None

    reprocessed = await client.post(
        f"/documents/{document_id}/reprocess", headers=headers
    )
    assert reprocessed.status_code == 202, reprocessed.text
    again = await client.get(f"/documents/{document_id}", headers=headers)
    assert again.json()["status"] == "ready"
    runs_after = await client.get(
        f"/knowledge-bases/{kb_id}/processing/runs?document_id={document_id}",
        headers=headers,
    )
    assert len(runs_after.json()) >= 2


def _retrieval_definition() -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "hybrid",
                "type": "hybrid_search",
                "config": {"top_k": 10, "candidate_k": 20},
            },
            {"id": "top", "type": "top_k", "config": {"top_k": 5}},
            {"id": "context", "type": "context", "config": {"max_chars": 4000}},
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": "hybrid"},
            {"from": "hybrid", "to": "top"},
            {"from": "top", "to": "context"},
            {"from": "context", "to": "out"},
        ],
    }


async def test_retrieval_canvas_binding_and_chat_path(
    client, api, fake_ingestion, fake_retrieval
):
    headers = await api.headers("p9-retrieval@example.com")
    kb = await _create_kb(client, headers, name="Retrieval KB")
    kb_id = kb.json()["id"]
    document = await _upload(client, headers, kb_id, content=b"hello retrieval world")
    assert document.status_code == 202

    created = await client.post(
        "/workflows",
        json={
            "name": "Hybrid retrieval",
            "kind": "knowledge_retrieval",
            "definition": _retrieval_definition(),
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    workflow = created.json()
    version_id = workflow["versions"][0]["id"]

    catalog = await client.get(
        "/workflows/catalog?kind=knowledge_retrieval", headers=headers
    )
    assert catalog.status_code == 200
    types = {item["type"] for item in catalog.json()["nodes"]}
    assert {"start", "hybrid_search", "rerank", "context", "output"} <= types
    assert catalog.json()["templates"]

    bound = await client.put(
        f"/knowledge-bases/{kb_id}/retrieval/binding",
        json={"workflow_version_id": version_id},
        headers=headers,
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["kind"] == "knowledge_retrieval"

    tested = await client.post(
        f"/knowledge-bases/{kb_id}/retrieval/test",
        json={"query": "hello", "workflow_version_id": version_id},
        headers=headers,
    )
    assert tested.status_code == 200, tested.text
    body = tested.json()
    assert body["results"]
    assert body["context"]
    assert body["nodes"]
    assert body["results"][0]["chunk_id"]

    searched = await client.post(
        f"/knowledge-bases/{kb_id}/retrieval/search",
        json={"query": "hello", "top_k": 5},
        headers=headers,
    )
    assert searched.status_code == 200, searched.text
    assert searched.json()["mode"] == "workflow"
    assert searched.json()["results"]


async def test_retrieval_workflow_rejects_branches(client, api):
    headers = await api.headers("p9-retrieval-invalid@example.com")
    definition = _retrieval_definition()
    definition["edges"].append({"from": "start", "to": "top"})
    rejected = await client.post(
        "/workflows",
        json={
            "name": "Bad retrieval",
            "kind": "knowledge_retrieval",
            "definition": definition,
        },
        headers=headers,
    )
    assert rejected.status_code == 422


async def test_broken_retrieval_workflow_falls_back_to_builtin(
    client, api, fake_ingestion, fake_retrieval
):
    headers = await api.headers("p9-retrieval-fallback@example.com")
    kb = await _create_kb(client, headers, name="Fallback KB")
    kb_id = kb.json()["id"]
    document = await _upload(client, headers, kb_id, content=b"fallback query content")
    assert document.status_code == 202

    definition = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "rewrite",
                "type": "rewrite_query",
                "config": {
                    "provider_id": "missing-provider",
                    "model": "missing-model",
                    "prompt": "{{query}}",
                },
            },
            {"id": "vector", "type": "vector_search", "config": {"top_k": 5}},
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": "rewrite"},
            {"from": "rewrite", "to": "vector"},
            {"from": "vector", "to": "out"},
        ],
    }
    created = await client.post(
        "/workflows",
        json={
            "name": "Broken rewrite",
            "kind": "knowledge_retrieval",
            "definition": definition,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    version_id = created.json()["versions"][0]["id"]
    await client.put(
        f"/knowledge-bases/{kb_id}/retrieval/binding",
        json={"workflow_version_id": version_id},
        headers=headers,
    )
    searched = await client.post(
        f"/knowledge-bases/{kb_id}/retrieval/search",
        json={"query": "fallback", "top_k": 5},
        headers=headers,
    )
    assert searched.status_code == 200, searched.text
    assert searched.json()["mode"] != "workflow"
    assert searched.json()["results"]


async def test_scoped_ai_builder_for_knowledge_canvases(client, api, registry):
    import json

    headers = await api.headers("p9-builder@example.com")
    workflow = await client.post(
        "/workflows",
        json={
            "name": "Builder process",
            "kind": "knowledge_process",
            "definition": _pipeline_definition(),
        },
        headers=headers,
    )
    assert workflow.status_code == 201
    process_flow_id = workflow.json()["id"]

    session = await client.post(
        "/agent-builder/sessions",
        json={
            "scope": "knowledge_process",
            "workflow_id": process_flow_id,
            "provider_id": "fake",
            "model": "fake-model",
        },
        headers=headers,
    )
    assert session.status_code == 201, session.text
    assert session.json()["scope"] == "knowledge_process"
    session_id = session.json()["id"]

    generated = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "parse", "type": "parse_document", "config": {}},
            {
                "id": "chunk",
                "type": "chunk_text",
                "config": {"strategy": "markdown", "chunk_size": 800},
            },
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": "parse"},
            {"from": "parse", "to": "chunk"},
            {"from": "chunk", "to": "out"},
        ],
    }
    registry.get("fake").complete_content = json.dumps(
        {
            "message": "Created a markdown pipeline.",
            "summary": "Markdown pipeline",
            "definition": generated,
            "missing_resources": [],
            "suggestions": [],
        }
    )
    turn = await client.post(
        f"/agent-builder/sessions/{session_id}/messages",
        json={"kind": "generate", "prompt": "Create a markdown pipeline"},
        headers=headers,
    )
    assert turn.status_code == 200, turn.text
    assert turn.json()["definition"]["nodes"][2]["type"] == "chunk_text"
    applied = await client.post(
        f"/agent-builder/sessions/{session_id}/apply",
        json={"definition": turn.json()["definition"]},
        headers=headers,
    )
    assert applied.status_code == 200, applied.text

    retrieval = await client.post(
        "/workflows",
        json={
            "name": "Builder retrieval",
            "kind": "knowledge_retrieval",
            "definition": _retrieval_definition(),
        },
        headers=headers,
    )
    assert retrieval.status_code == 201
    retrieval_id = retrieval.json()["id"]
    retrieval_session = await client.post(
        "/agent-builder/sessions",
        json={
            "scope": "knowledge_retrieval",
            "workflow_id": retrieval_id,
            "provider_id": "fake",
            "model": "fake-model",
        },
        headers=headers,
    )
    assert retrieval_session.status_code == 201, retrieval_session.text
    registry.get("fake").complete_content = json.dumps(
        {
            "message": "Explain",
            "summary": "Explain",
            "missing_resources": [],
            "suggestions": ["Add rerank."],
        }
    )
    explain = await client.post(
        f"/agent-builder/sessions/{retrieval_session.json()['id']}/messages",
        json={
            "kind": "explain",
            "prompt": "Explain",
            "current_definition": _retrieval_definition(),
        },
        headers=headers,
    )
    assert explain.status_code == 200, explain.text
    assert explain.json()["definition"] is None
    assert explain.json()["suggestions"] == ["Add rerank."]

    mismatch = await client.post(
        "/agent-builder/sessions",
        json={
            "scope": "knowledge_retrieval",
            "workflow_id": process_flow_id,
            "provider_id": "fake",
            "model": "fake-model",
        },
        headers=headers,
    )
    assert mismatch.status_code == 422
