from app.services.parsing import ParsedPage


async def _create_kb(client, headers, name="KB"):
    response = await client.post("/knowledge-bases", json={"name": name}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


async def _upload(client, headers, kb_id, content: bytes = b"x" * 250):
    response = await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("note.txt", content, "text/plain")},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


async def test_knowledge_base_settings_defaults_and_partial_update(client, api):
    headers = await api.headers("kb-settings@example.com")
    kb_id = await _create_kb(client, headers)

    defaults = await client.get(f"/knowledge-bases/{kb_id}/settings", headers=headers)
    assert defaults.status_code == 200
    assert defaults.json() == {
        "chunking": {"chunk_size": 100, "chunk_overlap": 20},
        "retrieval": {
            "top_k": 5,
            "candidate_k": 20,
            "hybrid_enabled": True,
            "rerank_enabled": False,
            "metadata_filter": {},
        },
        "embedding": {
            "provider_config_id": None,
            "model": "bge-m3",
            "dimensions": 1024,
        },
        "rerank": {"provider_config_id": None, "model": "bge-reranker-v2-m3"},
    }

    updated = await client.patch(
        f"/knowledge-bases/{kb_id}/settings",
        json={"retrieval": {"top_k": 3, "candidate_k": 8, "rerank_enabled": True}},
        headers=headers,
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["chunking"] == {"chunk_size": 100, "chunk_overlap": 20}
    assert body["retrieval"]["top_k"] == 3
    assert body["retrieval"]["candidate_k"] == 8
    assert body["retrieval"]["rerank_enabled"] is True
    assert body["retrieval"]["hybrid_enabled"] is True


async def test_knowledge_base_settings_reject_invalid_combinations(client, api):
    headers = await api.headers("kb-settings-invalid@example.com")
    kb_id = await _create_kb(client, headers)

    overlap = await client.patch(
        f"/knowledge-bases/{kb_id}/settings",
        json={"chunking": {"chunk_size": 100, "chunk_overlap": 100}},
        headers=headers,
    )
    assert overlap.status_code == 422

    candidates = await client.patch(
        f"/knowledge-bases/{kb_id}/settings",
        json={"retrieval": {"top_k": 10, "candidate_k": 5}},
        headers=headers,
    )
    assert candidates.status_code == 422


async def test_knowledge_base_settings_are_workspace_scoped(client, api):
    alice = await api.headers("kb-settings-alice@example.com")
    bob = await api.headers("kb-settings-bob@example.com")
    kb_id = await _create_kb(client, alice)

    read = await client.get(f"/knowledge-bases/{kb_id}/settings", headers=bob)
    write = await client.patch(
        f"/knowledge-bases/{kb_id}/settings",
        json={"retrieval": {"top_k": 2}},
        headers=bob,
    )

    assert read.status_code == 404
    assert write.status_code == 404


async def test_chunking_settings_apply_to_new_ingestion(client, api, fake_ingestion):
    fake_ingestion.parser.pages = [ParsedPage(page_no=1, text="a" * 250)]
    headers = await api.headers("kb-chunking@example.com")
    kb_id = await _create_kb(client, headers)

    await client.patch(
        f"/knowledge-bases/{kb_id}/settings",
        json={"chunking": {"chunk_size": 50, "chunk_overlap": 0}},
        headers=headers,
    )
    await _upload(client, headers, kb_id)

    chunks = await client.get(f"/knowledge-bases/{kb_id}/chunks?limit=20", headers=headers)
    assert chunks.status_code == 200
    body = chunks.json()
    assert body["total"] == 5
    assert [len(item["text"]) for item in body["items"]] == [50, 50, 50, 50, 50]


async def test_chunk_browser_filters_paginates_and_hides_other_workspaces(
    client, api, fake_ingestion
):
    fake_ingestion.parser.pages = [ParsedPage(page_no=1, text="a" * 250)]
    alice = await api.headers("kb-chunks-alice@example.com")
    bob = await api.headers("kb-chunks-bob@example.com")
    kb_id = await _create_kb(client, alice)
    document_id = await _upload(client, alice, kb_id)

    first_page = await client.get(
        f"/knowledge-bases/{kb_id}/chunks?limit=2&offset=0", headers=alice
    )
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 3
    assert len(first_page.json()["items"]) == 2
    assert first_page.json()["items"][0]["filename"] == "note.txt"
    assert first_page.json()["items"][0]["char_count"] == 100

    last_page = await client.get(f"/knowledge-bases/{kb_id}/chunks?limit=2&offset=2", headers=alice)
    assert len(last_page.json()["items"]) == 1

    filtered = await client.get(
        f"/knowledge-bases/{kb_id}/chunks?document_id={document_id}&q=aaa", headers=alice
    )
    assert filtered.json()["total"] == 3

    missing = await client.get(f"/knowledge-bases/{kb_id}/chunks?q=not-present", headers=alice)
    assert missing.json()["total"] == 0

    foreign = await client.get(f"/knowledge-bases/{kb_id}/chunks", headers=bob)
    assert foreign.status_code == 404


async def test_knowledge_base_stats_count_documents_and_chunks(client, api, fake_ingestion):
    fake_ingestion.parser.pages = [ParsedPage(page_no=1, text="a" * 250)]
    headers = await api.headers("kb-stats@example.com")
    kb_id = await _create_kb(client, headers)
    await _upload(client, headers, kb_id)

    response = await client.get(f"/knowledge-bases/{kb_id}/stats", headers=headers)

    assert response.status_code == 200
    assert response.json() == {
        "document_count": 1,
        "ready_count": 1,
        "processing_count": 0,
        "failed_count": 0,
        "chunk_count": 3,
        "char_count": 290,
    }


async def test_reprocess_rechunks_document_with_current_settings(
    client, api, fake_ingestion, fake_queue
):
    fake_ingestion.parser.pages = [ParsedPage(page_no=1, text="a" * 250)]
    headers = await api.headers("kb-reprocess@example.com")
    kb_id = await _create_kb(client, headers)

    await client.patch(
        f"/knowledge-bases/{kb_id}/settings",
        json={"chunking": {"chunk_size": 50, "chunk_overlap": 0}},
        headers=headers,
    )
    document_id = await _upload(client, headers, kb_id)

    await client.patch(
        f"/knowledge-bases/{kb_id}/settings",
        json={"chunking": {"chunk_size": 100, "chunk_overlap": 0}},
        headers=headers,
    )
    response = await client.post(f"/documents/{document_id}/reprocess", headers=headers)

    assert response.status_code == 202
    assert response.json()["id"] == document_id
    assert [str(call) for call in fake_queue.calls] == [document_id, document_id]
    assert fake_queue.unique_flags == [False, True]
    detail = await client.get(f"/documents/{document_id}", headers=headers)
    assert detail.json()["status"] == "ready"
    chunks = await client.get(f"/knowledge-bases/{kb_id}/chunks?limit=20", headers=headers)
    assert [len(item["text"]) for item in chunks.json()["items"]] == [100, 100, 50]


async def test_reprocess_rejects_other_workspace(client, api, fake_ingestion):
    alice = await api.headers("kb-reprocess-alice@example.com")
    bob = await api.headers("kb-reprocess-bob@example.com")
    kb_id = await _create_kb(client, alice)
    document_id = await _upload(client, alice, kb_id)

    response = await client.post(f"/documents/{document_id}/reprocess", headers=bob)

    assert response.status_code == 404
