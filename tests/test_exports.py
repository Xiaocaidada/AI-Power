async def _conversation(client, api, registry, fake_provider, email="export@example.com"):
    headers = await api.headers(email)
    created = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )
    conversation_id = created.json()["id"]
    sent = await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "Hi"},
        headers=headers,
    )
    assert sent.status_code == 200
    return headers, conversation_id


async def test_export_conversation_markdown(client, api, registry, fake_provider):
    headers, conversation_id = await _conversation(client, api, registry, fake_provider)

    response = await client.get(
        f"/conversations/{conversation_id}/export?format=markdown", headers=headers
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"]
    assert f"conversation-{conversation_id}.md" in response.headers["content-disposition"]
    assert response.text.startswith("# Hi")
    assert "## 用户" in response.text
    assert "## 助手" in response.text
    assert "Hello" in response.text


async def test_export_conversation_json(client, api, registry, fake_provider):
    headers, conversation_id = await _conversation(
        client, api, registry, fake_provider, "export-json@example.com"
    )

    response = await client.get(
        f"/conversations/{conversation_id}/export?format=json", headers=headers
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert f"conversation-{conversation_id}.json" in response.headers["content-disposition"]
    body = response.json()
    assert body["id"] == conversation_id
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["content"] == "Hi"
    assert body["messages"][1]["content"] == "Hello"


async def test_export_conversation_supports_read_api_key(client, api, registry, fake_provider):
    headers, conversation_id = await _conversation(
        client, api, registry, fake_provider, "export-key@example.com"
    )
    created_key = await client.post(
        "/api-keys",
        json={"name": "reader", "scopes": ["kb:read"]},
        headers=headers,
    )

    response = await client.get(
        f"/conversations/{conversation_id}/export",
        headers={"X-API-Key": created_key.json()["key"]},
    )

    assert response.status_code == 200
    assert "Hello" in response.text


async def test_export_conversation_is_workspace_scoped(client, api, registry, fake_provider):
    _alice_headers, conversation_id = await _conversation(
        client, api, registry, fake_provider, "export-alice@example.com"
    )
    bob_headers = await api.headers("export-bob@example.com")

    response = await client.get(f"/conversations/{conversation_id}/export", headers=bob_headers)

    assert response.status_code == 404


async def test_export_rejects_unknown_format(client, api, registry, fake_provider):
    headers, conversation_id = await _conversation(
        client, api, registry, fake_provider, "export-invalid@example.com"
    )

    response = await client.get(
        f"/conversations/{conversation_id}/export?format=pdf", headers=headers
    )

    assert response.status_code == 422
