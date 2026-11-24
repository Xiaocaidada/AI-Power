async def _create_kb(client, headers, name):
    response = await client.post(
        "/knowledge-bases", json={"name": name}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _upload(client, headers, kb_id, content: bytes, filename: str):
    response = await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": (filename, content, "text/plain")},
        headers=headers,
    )
    assert response.status_code in {201, 202}, response.text
    return response.json()["id"]


def _pipeline(nodes: list[tuple[str, str, dict]], kind: str):
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


async def _create_workflow(client, headers, nodes, kind, name):
    definition = _pipeline(nodes, kind)
    response = await client.post(
        "/workflows",
        json={
            "name": name,
            "kind": kind,
            "definition": definition,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _retrieval_test(client, headers, kb_id, version_id, query="query"):
    response = await client.post(
        f"/knowledge-bases/{kb_id}/retrieval/test",
        json={"query": query, "workflow_version_id": version_id},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_metadata_filter_multi_kb_and_dedupe(
    client, api, fake_ingestion, fake_retrieval
):
    headers = await api.headers("p11s6-retrieval@example.com")
    kb1 = await _create_kb(client, headers, "S6 KB one")
    kb2 = await _create_kb(client, headers, "S6 KB two")
    doc1 = await _upload(client, headers, kb1, b"alpha one", "a.txt")
    await _upload(client, headers, kb1, b"beta two", "b.txt")
    doc3 = await _upload(client, headers, kb2, b"gamma three", "c.txt")
    patched = await client.patch(
        f"/documents/{doc1}",
        json={"doc_metadata": {"team": "a"}},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text

    filtered = await _create_workflow(
        client,
        headers,
        [
            ("start", "start", {}),
            (
                "vector",
                "vector_search",
                {"top_k": 10, "metadata_filter": {"team": "a"}},
            ),
            ("filter", "filter_results", {"dedupe_documents": True}),
            ("out", "output", {}),
        ],
        "knowledge_retrieval",
        "Metadata filtered retrieval",
    )
    filtered_result = await _retrieval_test(
        client, headers, kb1, filtered["versions"][0]["id"]
    )
    assert filtered_result["results"]
    assert {hit["document_id"] for hit in filtered_result["results"]} == {doc1}

    multi_kb = await _create_workflow(
        client,
        headers,
        [
            ("start", "start", {}),
            ("vector", "vector_search", {"top_k": 10, "kb_ids": [kb2]}),
            ("out", "output", {}),
        ],
        "knowledge_retrieval",
        "Multi KB retrieval",
    )
    multi_result = await _retrieval_test(
        client, headers, kb1, multi_kb["versions"][0]["id"]
    )
    assert {hit["document_id"] for hit in multi_result["results"]} == {doc3}

    deduped = await _create_workflow(
        client,
        headers,
        [
            ("start", "start", {}),
            ("vector", "vector_search", {"top_k": 10}),
            ("filter", "filter_results", {"dedupe_documents": True}),
            ("out", "output", {}),
        ],
        "knowledge_retrieval",
        "Document dedupe retrieval",
    )
    deduped_result = await _retrieval_test(
        client, headers, kb1, deduped["versions"][0]["id"]
    )
    document_ids = [hit["document_id"] for hit in deduped_result["results"]]
    assert len(document_ids) == len(set(document_ids))


async def test_multi_query_and_empty_fallback(
    client, api, registry, fake_ingestion, fake_retrieval
):
    headers = await api.headers("p11s6-multiquery@example.com")
    kb_id = await _create_kb(client, headers, "S6 multi query")
    await _upload(client, headers, kb_id, b"alpha beta gamma", "multi.txt")
    registry.get("fake").complete_content = "alpha query\nbeta query"

    multi = await _create_workflow(
        client,
        headers,
        [
            ("start", "start", {}),
            (
                "multi",
                "multi_query",
                {
                    "provider_id": "fake",
                    "model": "fake-model",
                    "variants": 2,
                    "top_k": 8,
                    "candidate_k": 10,
                },
            ),
            ("out", "output", {}),
        ],
        "knowledge_retrieval",
        "Multi query retrieval",
    )
    multi_result = await _retrieval_test(
        client, headers, kb_id, multi["versions"][0]["id"], "alpha"
    )
    assert multi_result["results"]

    fallback = await _create_workflow(
        client,
        headers,
        [
            ("start", "start", {}),
            (
                "vector",
                "vector_search",
                {"top_k": 5, "metadata_filter": {"team": "missing"}},
            ),
            ("fallback", "fallback_search", {"top_k": 5, "candidate_k": 10}),
            ("out", "output", {}),
        ],
        "knowledge_retrieval",
        "Fallback retrieval",
    )
    fallback_result = await _retrieval_test(
        client, headers, kb_id, fallback["versions"][0]["id"], "alpha"
    )
    assert fallback_result["results"]


async def test_processing_analytics(client, api, fake_retrieval):
    headers = await api.headers("p11s6-analytics@example.com")
    kb_id = await _create_kb(client, headers, "S6 analytics")
    document_id = await _upload(
        client, headers, kb_id, b"alpha beta gamma delta", "analytics.txt"
    )
    workflow = await _create_workflow(
        client,
        headers,
        [
            ("start", "start", {}),
            ("parse", "parse_document", {}),
            ("clean", "clean_text", {}),
            (
                "chunk",
                "chunk_text",
                {
                    "strategy": "fixed",
                    "chunk_size": 50,
                    "chunk_overlap": 10,
                    "min_chars": 0,
                },
            ),
            ("embed", "embed_chunks", {}),
            ("index", "index_knowledge", {}),
            ("out", "output", {}),
        ],
        "knowledge_process",
        "S6 analytics processing",
    )
    started = await client.post(
        f"/workflows/{workflow['id']}/runs",
        json={"document_id": document_id},
        headers=headers,
    )
    assert started.status_code == 202, started.text

    analytics = await client.get(
        f"/knowledge-bases/{kb_id}/processing/analytics?days=30",
        headers=headers,
    )
    assert analytics.status_code == 200, analytics.text
    payload = analytics.json()
    assert payload["total"] >= 1
    assert payload["completed"] >= 1
    assert payload["success_rate"] > 0
    assert payload["recent"]
    assert payload["recent"][0]["document_id"] == document_id
    assert payload["recent"][0]["filename"] == "analytics.txt"


async def test_retrieval_catalog_lists_new_nodes(client, api):
    headers = await api.headers("p11s6-catalog@example.com")
    catalog = await client.get(
        "/workflows/catalog?kind=knowledge_retrieval", headers=headers
    )
    assert catalog.status_code == 200
    body = catalog.json()
    types = {item["type"] for item in body["nodes"]}
    assert {
        "multi_query",
        "filter_results",
        "fallback_search",
        "vector_search",
        "lexical_search",
        "hybrid_search",
    } <= types
    names = {template["name"] for template in body["templates"]}
    assert "多查询 + 过滤" in names

    invalid = await client.post(
        "/workflows",
        json={
            "name": "Invalid metadata key",
            "kind": "knowledge_retrieval",
            "definition": _pipeline(
                [
                    ("start", "start", {}),
                    (
                        "vector",
                        "vector_search",
                        {"metadata_filter": {"$bad": "x"}},
                    ),
                    ("out", "output", {}),
                ],
                "knowledge_retrieval",
            ),
        },
        headers=headers,
    )
    assert invalid.status_code == 422