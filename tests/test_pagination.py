async def test_conversation_pagination(client, api, registry):
    headers = await api.headers("page-conv@example.com")
    created = []
    for _ in range(3):
        response = await client.post(
            "/conversations",
            json={"provider_id": "fake", "model": "fake-model", "kb_id": None},
            headers=headers,
        )
        created.append(response.json()["id"])

    first = await client.get("/conversations?limit=2", headers=headers)
    second = await client.get(
        f"/conversations?limit=2&before={first.json()[1]['id']}", headers=headers
    )

    assert first.status_code == 200
    assert len(first.json()) == 2
    assert len(second.json()) == 1
    assert second.json()[0]["id"] == created[0]


async def test_trace_list_pagination(client, api, registry):
    headers = await api.headers("page-trace@example.com")
    conversation = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model", "kb_id": None},
        headers=headers,
    )
    for request_id in ("page-trace-1", "page-trace-2"):
        await client.post(
            f"/conversations/{conversation.json()['id']}/messages",
            json={"content": "hello"},
            headers={**headers, "X-Request-ID": request_id},
        )

    first = await client.get("/traces?limit=1", headers=headers)
    second = await client.get(f"/traces?limit=1&before={first.json()[0]['id']}", headers=headers)

    assert first.status_code == 200
    assert len(first.json()) == 1
    assert len(second.json()) == 1
    assert first.json()[0]["request_id"] != second.json()[0]["request_id"]


async def test_document_pagination(client, api, fake_ingestion):
    headers = await api.headers("page-docs@example.com")
    kb = await client.post("/knowledge-bases", json={"name": "Pages"}, headers=headers)
    for name, content in (("one.txt", b"first"), ("two.txt", b"second")):
        response = await client.post(
            f"/knowledge-bases/{kb.json()['id']}/documents",
            files={"file": (name, content, "text/plain")},
            headers=headers,
        )
        assert response.status_code == 202

    first = await client.get(
        f"/knowledge-bases/{kb.json()['id']}/documents?limit=1", headers=headers
    )
    second = await client.get(
        f"/knowledge-bases/{kb.json()['id']}/documents?limit=1&before={first.json()[0]['id']}",
        headers=headers,
    )

    assert len(first.json()) == 1
    assert len(second.json()) == 1
    assert first.json()[0]["id"] != second.json()[0]["id"]
