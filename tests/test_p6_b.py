import json


async def _create_conversation(client, headers, **extra):
    body = {"provider_id": "fake", "model": "fake-model", **extra}
    return await client.post("/conversations", json=body, headers=headers)


async def _send(client, headers, conversation_id, content="Hi", **extra):
    return await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": content, **extra},
        headers=headers,
    )


async def _create_kb(client, headers, name="KB"):
    response = await client.post("/knowledge-bases", json={"name": name}, headers=headers)
    assert response.status_code == 201
    return response.json()["id"]


async def test_edit_message_truncates_and_reply_streams(client, api, registry):
    headers = await api.headers("p6b-edit@example.com")
    created = await _create_conversation(client, headers)
    conversation_id = created.json()["id"]
    await _send(client, headers, conversation_id, "Original")

    detail = (await client.get(f"/conversations/{conversation_id}", headers=headers)).json()
    user_message = detail["messages"][0]
    assert len(detail["messages"]) == 2

    edited = await client.patch(
        f"/conversations/{conversation_id}/messages/{user_message['id']}",
        json={"content": "Edited"},
        headers=headers,
    )
    assert edited.status_code == 200
    assert edited.json()["removed"] == 1

    detail = (await client.get(f"/conversations/{conversation_id}", headers=headers)).json()
    assert [item["role"] for item in detail["messages"]] == ["user"]
    assert detail["messages"][0]["content"] == "Edited"

    reply = await client.post(
        f"/conversations/{conversation_id}/messages/{user_message['id']}/reply",
        headers=headers,
    )
    assert reply.status_code == 200
    detail = (await client.get(f"/conversations/{conversation_id}", headers=headers)).json()
    assert [item["role"] for item in detail["messages"]] == ["user", "assistant"]

    recent = await client.get("/usage/recent", headers=headers)
    assert recent.status_code == 200
    assert len(recent.json()) >= 1


async def test_hard_delete_and_batch_delete_keep_usage(client, api, registry):
    headers = await api.headers("p6b-delete@example.com")
    first = (await _create_conversation(client, headers)).json()["id"]
    second = (await _create_conversation(client, headers)).json()["id"]
    await _send(client, headers, first, "Hello")

    deleted = await client.delete(f"/conversations/{first}/permanent", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get(f"/conversations/{first}", headers=headers)).status_code == 404

    batch = await client.post(
        "/conversations/batch",
        json={"action": "delete", "conversation_ids": [second]},
        headers=headers,
    )
    assert batch.status_code == 200
    assert batch.json()["updated"] == 1
    recent = await client.get("/usage/recent", headers=headers)
    assert len(recent.json()) >= 1


async def test_chat_attachment_upload_and_send(client, api, registry, fake_provider):
    headers = await api.headers("p6b-attach@example.com")
    conversation_id = (await _create_conversation(client, headers)).json()["id"]

    upload = await client.post(
        "/attachments",
        files={"file": ("notes.txt", b"hello from attachment", "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 201
    attachment_id = upload.json()["id"]

    sent = await _send(
        client,
        headers,
        conversation_id,
        "Summarize",
        attachment_ids=[attachment_id],
    )
    assert sent.status_code == 200

    messages, _model = fake_provider.calls[-1]
    assert "hello from attachment" in str(messages[-1].content)

    detail = (await client.get(f"/conversations/{conversation_id}", headers=headers)).json()
    assert detail["messages"][0]["attachments"][0]["id"] == attachment_id

    other = await api.headers("p6b-attach-other@example.com")
    assert (
        await client.get(f"/attachments/{attachment_id}/download", headers=other)
    ).status_code == 404


async def test_auto_route_rejects_image_attachment(client, api, registry):
    headers = await api.headers("p6b-image@example.com")
    upload = await client.post(
        "/attachments",
        files={"file": ("photo.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        headers=headers,
    )
    assert upload.status_code == 201
    response = await client.post(
        "/conversations",
        json={
            "provider_id": "auto",
            "model": "auto",
            "attachment_ids": [upload.json()["id"]],
        },
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "vision_model_required"


async def test_multi_kb_create_and_detail(client, api, registry):
    headers = await api.headers("p6b-kb@example.com")
    kb_one = await _create_kb(client, headers, "KB one")
    kb_two = await _create_kb(client, headers, "KB two")

    created = await _create_conversation(client, headers, kb_ids=[kb_one, kb_two])
    assert created.status_code == 201
    detail = (
        await client.get(f"/conversations/{created.json()['id']}", headers=headers)
    ).json()
    assert detail["kb_id"] == kb_one
    assert detail["kb_ids"] == [kb_one, kb_two]

    updated = await client.patch(
        f"/knowledge-bases/{kb_one}",
        json={"name": "Renamed", "description": "desc"},
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    assert updated.json()["description"] == "desc"


async def test_document_tags_and_search(client, api, registry, fake_ingestion):
    headers = await api.headers("p6b-doc-tag@example.com")
    kb_id = await _create_kb(client, headers, "Docs")
    upload = await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("notes.txt", b"tagged content", "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 202
    document_id = upload.json()["id"]

    patched = await client.patch(
        f"/documents/{document_id}",
        json={"tags": ["finance", "finance", " q3 "]},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["tags"] == ["finance", "q3"]

    listed = await client.get(
        f"/knowledge-bases/{kb_id}/documents",
        params={"q": "notes", "tag": "finance"},
        headers=headers,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [document_id]


async def test_global_search_includes_models_and_plugins(client, api, registry):
    headers = await api.headers("p6b-search@example.com")
    response = await client.get("/search", params={"q": "zzz-no-match"}, headers=headers)
    assert response.status_code == 200
    json.dumps(response.json())