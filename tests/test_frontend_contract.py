from uuid import UUID


async def _create_kb(client, headers, name="Frontend KB"):
    return await client.post("/knowledge-bases", json={"name": name}, headers=headers)


async def _upload(client, headers, kb_id, filename="note.txt", content=b"hello world"):
    return await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": (filename, content, "text/plain")},
        headers=headers,
    )


PREFLIGHT_HEADERS = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "authorization,content-type",
}


async def test_cors_preflight_allows_configured_origin(client):
    response = await client.options(
        "/auth/login",
        headers={"Origin": "http://localhost:5173", **PREFLIGHT_HEADERS},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed
    assert "x-api-key" in allowed


async def test_cors_allows_lan_web_origin(client):
    response = await client.options(
        "/conversations",
        headers={"Origin": "http://192.168.29.100:8080", **PREFLIGHT_HEADERS},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://192.168.29.100:8080"


async def test_cors_ignores_unknown_origin(client):
    response = await client.get("/healthz", headers={"Origin": "http://evil.example"})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


async def test_cors_exposes_retry_after(client):
    response = await client.get("/healthz", headers={"Origin": "http://localhost:5173"})

    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "retry-after" in response.headers["access-control-expose-headers"].lower()


async def test_list_documents_returns_newest_first(client, api, fake_ingestion):
    headers = await api.headers("list-docs@example.com")
    kb = await _create_kb(client, headers)
    first = await _upload(client, headers, kb.json()["id"], filename="first.txt")
    second = await _upload(
        client, headers, kb.json()["id"], filename="second.txt", content=b"other"
    )

    response = await client.get(f"/knowledge-bases/{kb.json()['id']}/documents", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [second.json()["id"], first.json()["id"]]
    assert body[0]["filename"] == "second.txt"
    assert body[0]["status"] == "ready"
    assert "storage_path" not in body[0]
    assert "content_hash" not in body[0]


async def test_list_documents_excludes_deleted(client, api, fake_ingestion):
    headers = await api.headers("list-deleted@example.com")
    kb = await _create_kb(client, headers)
    kept = await _upload(client, headers, kb.json()["id"], filename="kept.txt")
    removed = await _upload(
        client, headers, kb.json()["id"], filename="removed.txt", content=b"gone"
    )
    await client.delete(f"/documents/{removed.json()['id']}", headers=headers)

    response = await client.get(f"/knowledge-bases/{kb.json()['id']}/documents", headers=headers)

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [kept.json()["id"]]


async def test_list_documents_for_empty_kb_returns_empty_list(client, api):
    headers = await api.headers("list-empty@example.com")
    kb = await _create_kb(client, headers)

    response = await client.get(f"/knowledge-bases/{kb.json()['id']}/documents", headers=headers)

    assert response.status_code == 200
    assert response.json() == []


async def test_list_documents_on_foreign_kb_returns_404(client, api, fake_ingestion):
    alice = await api.headers("list-alice@example.com")
    bob = await api.headers("list-bob@example.com")
    kb = await _create_kb(client, alice)
    await _upload(client, alice, kb.json()["id"])

    response = await client.get(f"/knowledge-bases/{kb.json()['id']}/documents", headers=bob)

    assert response.status_code == 404


async def test_list_documents_requires_auth(client):
    response = await client.get("/knowledge-bases/00000000-0000-0000-0000-000000000000/documents")

    assert response.status_code == 401


async def test_api_key_with_kb_scope_can_list_documents(client, api, fake_ingestion):
    headers = await api.headers("list-key@example.com")
    kb = await _create_kb(client, headers)
    await _upload(client, headers, kb.json()["id"])
    created = await client.post(
        "/api-keys",
        json={"name": "reader", "scopes": ["kb:read"]},
        headers=headers,
    )
    key = created.json()["key"]

    response = await client.get(
        f"/knowledge-bases/{kb.json()['id']}/documents",
        headers={"X-API-Key": key},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_api_key_without_kb_scope_cannot_list_documents(client, api, fake_ingestion):
    headers = await api.headers("list-chat-key@example.com")
    kb = await _create_kb(client, headers)
    created = await client.post(
        "/api-keys",
        json={"name": "writer", "scopes": ["chat:write"]},
        headers=headers,
    )

    response = await client.get(
        f"/knowledge-bases/{kb.json()['id']}/documents",
        headers={"X-API-Key": created.json()["key"]},
    )

    assert response.status_code == 403


async def test_list_documents_returns_uuid_ids(client, api, fake_ingestion):
    headers = await api.headers("list-uuid@example.com")
    kb = await _create_kb(client, headers)
    await _upload(client, headers, kb.json()["id"])

    body = (
        await client.get(f"/knowledge-bases/{kb.json()['id']}/documents", headers=headers)
    ).json()

    UUID(body[0]["id"])
