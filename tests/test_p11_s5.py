from app.services.knowledge.chunkers import (
    chunk_custom,
    chunk_parent_child,
    parse_separators,
    split_sentences,
)
from app.services.parsing import ParsedPage


async def _create_kb(client, headers, name="P11 S5 KB"):
    response = await client.post(
        "/knowledge-bases", json={"name": name}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _upload(client, headers, kb_id, content: bytes, filename="s5.txt"):
    response = await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": (filename, content, "text/plain")},
        headers=headers,
    )
    assert response.status_code in {201, 202}, response.text
    return response.json()["id"]


def _definition(nodes: list[tuple[str, str, dict]], kind: str = "knowledge_process"):
    built = []
    edges = []
    previous = None
    for index, (node_id, node_type, config) in enumerate(nodes):
        built.append(
            {
                "id": node_id,
                "type": node_type,
                "config": config,
                "ui": {"x": 80 + index * 180, "y": 120},
            }
        )
        if previous is not None:
            edges.append({"from": previous, "to": node_id})
        previous = node_id
    return {"nodes": built, "edges": edges, "kind": kind}


async def _create_workflow(client, headers, definition, name="P11 S5 workflow"):
    response = await client.post(
        "/workflows",
        json={
            "name": name,
            "description": "P11 S5",
            "kind": "knowledge_process",
            "definition": definition,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _run(client, headers, workflow_id, document_id):
    started = await client.post(
        f"/workflows/{workflow_id}/runs",
        json={"document_id": document_id},
        headers=headers,
    )
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]
    detail = await client.get(f"/workflows/runs/{run_id}", headers=headers)
    assert detail.json()["status"] == "completed", detail.json()
    return run_id


def test_custom_and_parent_child_chunkers():
    pages = [
        ParsedPage(page_no=1, text="Alpha beta。Gamma delta。Epsilon zeta。"),
        ParsedPage(page_no=2, text="Eta theta。Iota kappa。"),
    ]
    custom = chunk_custom(
        pages,
        chunk_size=20,
        min_chars=0,
        separators=parse_separators("。| "),
    )
    assert custom
    assert len({chunk["text"] for chunk in custom}) == len(custom)

    parent_child = chunk_parent_child(
        pages, parent_size=60, child_size=18, min_chars=0
    )
    assert parent_child
    first = parent_child[0]
    assert first["meta"]["parent_id"].startswith("p1-")
    assert first["meta"]["parent_text"]
    assert len(first["text"]) <= len(first["meta"]["parent_text"])
    assert {page for page, _text in split_sentences(pages)} == {1, 2}


async def test_enhanced_parent_child_pipeline_and_metadata(
    client, api, fake_retrieval
):
    headers = await api.headers("p11s5-enhance@example.com")
    kb_id = await _create_kb(client, headers)
    document_id = await _upload(
        client,
        headers,
        kb_id,
        (
            b"Page Header\n"
            b"alpha beta gamma. Alpha beta delta.\n"
            b"alpha beta gamma. Alpha beta delta.\n"
            b"Page Header\n"
            b"unique omega content for retrieval.\n"
        ),
    )
    workflow = await _create_workflow(
        client,
        headers,
        _definition(
            [
                ("start", "start", {}),
                ("parse", "parse_document", {}),
                ("clean", "clean_text", {}),
                (
                    "filter",
                    "filter_text",
                    {"drop_patterns": "^Page Header$", "dedupe_lines": True},
                ),
                (
                    "chunk",
                    "chunk_text",
                    {
                        "strategy": "parent_child",
                        "parent_size": 200,
                        "child_size": 50,
                        "chunk_overlap": 0,
                        "min_chars": 0,
                    },
                ),
                (
                    "meta",
                    "enrich_metadata",
                    {"prepend_title": True},
                ),
                ("keywords", "extract_keywords", {"count": 5}),
                ("summary", "summarize_chunks", {"max_chars": 80}),
                ("dedupe", "dedupe_chunks", {"threshold": 0.99}),
                ("embed", "embed_chunks", {}),
                ("index", "index_knowledge", {}),
                ("out", "output", {}),
            ]
        ),
    )
    run_id = await _run(client, headers, workflow["id"], document_id)

    preview = await client.get(
        f"/knowledge-bases/{kb_id}/processing/runs/{run_id}/preview",
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    kinds = {artifact["kind"] for artifact in body["artifacts"]}
    assert {"filtered", "chunks", "embeddings", "index"} <= kinds
    chunk_payloads = [
        artifact["payload"]
        for artifact in body["artifacts"]
        if artifact["kind"] == "chunks"
    ]
    enriched = next(
        payload
        for payload in chunk_payloads
        if payload["chunks"]
        and "keywords" in (payload["chunks"][0].get("meta") or {})
        and "summary" in (payload["chunks"][0].get("meta") or {})
    )
    meta = enriched["chunks"][0]["meta"]
    assert meta["document_title"] == "s5"
    assert meta["keywords"]
    assert meta["summary"]
    assert meta["parent_id"]
    assert meta["parent_text"]
    assert "Page Header" not in enriched["chunks"][0]["text"]

    applied = await client.post(
        f"/knowledge-bases/{kb_id}/processing/runs/{run_id}/apply",
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    chunks = await client.get(
        f"/knowledge-bases/{kb_id}/chunks?document_id={document_id}",
        headers=headers,
    )
    assert chunks.status_code == 200, chunks.text
    items = chunks.json()["items"]
    assert items
    assert items[0]["chunk_meta"]["parent_text"]
    assert items[0]["chunk_meta"]["keywords"]

    search = await client.post(
        f"/knowledge-bases/{kb_id}/retrieval/search",
        json={"query": "omega", "top_k": 5, "hybrid_enabled": False},
        headers=headers,
    )
    assert search.status_code == 200, search.text
    hits = search.json()["results"]
    assert hits
    assert any("unique omega content" in hit["text"] for hit in hits)

    retrieval_definition = _definition(
        [
            ("start", "start", {}),
            ("vector", "vector_search", {"top_k": 5}),
            ("context", "context", {"max_chars": 4000}),
            ("out", "output", {}),
        ],
        kind="knowledge_retrieval",
    )
    retrieval = await client.post(
        "/workflows",
        json={
            "name": "Parent context retrieval",
            "kind": "knowledge_retrieval",
            "definition": retrieval_definition,
        },
        headers=headers,
    )
    assert retrieval.status_code == 201, retrieval.text
    version_id = retrieval.json()["versions"][0]["id"]
    tested = await client.post(
        f"/knowledge-bases/{kb_id}/retrieval/test",
        json={"query": "omega", "workflow_version_id": version_id},
        headers=headers,
    )
    assert tested.status_code == 200, tested.text
    assert any(
        "unique omega content" in hit["text"] for hit in tested.json()["results"]
    )


async def test_custom_and_semantic_chunk_pipelines(client, api, fake_retrieval):
    headers = await api.headers("p11s5-semantic@example.com")
    kb_id = await _create_kb(client, headers)
    document_id = await _upload(
        client,
        headers,
        kb_id,
        (
            b"Alpha beta gamma. Delta epsilon zeta.\n\n"
            b"Theta iota kappa. Lambda mu nu.\n\n"
            b"Xi omicron pi. Rho sigma tau.\n"
        ),
    )

    for strategy, extra in (
        ("custom", {"separators": "\\n\\n|。|. | "}),
        ("semantic", {"chunk_size": 80, "semantic_threshold": 0.2}),
    ):
        workflow = await _create_workflow(
            client,
            headers,
            _definition(
                [
                    ("start", "start", {}),
                    ("parse", "parse_document", {}),
                    ("clean", "clean_text", {}),
                    (
                        "chunk",
                        "chunk_text",
                        {
                            "strategy": strategy,
                            "chunk_size": 60,
                            "chunk_overlap": 0,
                            "min_chars": 0,
                            **extra,
                        },
                    ),
                    ("embed", "embed_chunks", {}),
                    ("index", "index_knowledge", {}),
                    ("out", "output", {}),
                ]
            ),
            name=f"P11 S5 {strategy}",
        )
        run_id = await _run(client, headers, workflow["id"], document_id)
        preview = await client.get(
            f"/knowledge-bases/{kb_id}/processing/runs/{run_id}/preview",
            headers=headers,
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["draft_count"] >= 1


async def test_catalog_and_invalid_parent_child_config(client, api):
    headers = await api.headers("p11s5-catalog@example.com")
    catalog = await client.get(
        "/workflows/catalog?kind=knowledge_process", headers=headers
    )
    assert catalog.status_code == 200
    body = catalog.json()
    types = {item["type"] for item in body["nodes"]}
    assert {
        "filter_text",
        "enrich_metadata",
        "extract_keywords",
        "summarize_chunks",
        "dedupe_chunks",
    } <= types
    names = {template["name"] for template in body["templates"]}
    assert {"增强文档处理", "父子切片处理"} <= names

    invalid = await client.post(
        "/workflows",
        json={
            "name": "Invalid parent child",
            "kind": "knowledge_process",
            "definition": _definition(
                [
                    ("start", "start", {}),
                    (
                        "chunk",
                        "chunk_text",
                        {
                            "strategy": "parent_child",
                            "parent_size": 200,
                            "child_size": 400,
                        },
                    ),
                    ("out", "output", {}),
                ]
            ),
        },
        headers=headers,
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["code"] == "invalid_workflow"