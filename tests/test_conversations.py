import json


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        event = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data = json.loads(next(line[len("data: ") :] for line in lines if line.startswith("data: ")))
        events.append((event, data))
    return events


async def _create_conversation(client, headers, provider_id="fake", model="fake-model"):
    return await client.post(
        "/conversations",
        json={"provider_id": provider_id, "model": model},
        headers=headers,
    )


async def _send(client, headers, conversation_id, content="Hi"):
    return await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": content},
        headers=headers,
    )


async def test_providers_endpoint_requires_auth(client, registry):
    response = await client.get("/providers")

    assert response.status_code == 401


async def test_providers_endpoint_returns_metadata_without_secrets(client, api, registry):
    headers = await api.headers("providers@example.com")

    response = await client.get("/providers", headers=headers)

    assert response.status_code == 200
    assert response.json() == [{"id": "fake", "available": True, "models": ["fake-model"]}]
    assert "api_key" not in response.text


async def test_create_conversation_requires_auth(client, registry):
    response = await client.post(
        "/conversations", json={"provider_id": "fake", "model": "fake-model"}
    )

    assert response.status_code == 401


async def test_create_conversation_rejects_unknown_provider(client, api, registry):
    headers = await api.headers("unknown-provider@example.com")

    response = await _create_conversation(client, headers, provider_id="missing")

    assert response.status_code == 404


async def test_create_conversation_rejects_blank_model(client, api, registry):
    headers = await api.headers("blank-model@example.com")

    response = await _create_conversation(client, headers, model="   ")

    assert response.status_code == 422


async def test_conversations_are_isolated(client, api, registry):
    alice = await api.headers("conv-alice@example.com")
    bob = await api.headers("conv-bob@example.com")
    created = await _create_conversation(client, alice)
    conversation_id = created.json()["id"]

    bob_list = await client.get("/conversations", headers=bob)
    bob_get = await client.get(f"/conversations/{conversation_id}", headers=bob)

    assert bob_list.json() == []
    assert bob_get.status_code == 404


async def test_send_message_streams_and_persists(client, api, registry):
    headers = await api.headers("stream@example.com")
    created = await _create_conversation(client, headers)
    conversation_id = created.json()["id"]

    response = await _send(client, headers, conversation_id, "Hi there")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    assert [event for event, _ in events] == ["meta", "delta", "delta", "usage", "done"]
    assert "".join(data["text"] for event, data in events if event == "delta") == "Hello"
    assert events[3][1] == {"prompt_tokens": 1, "completion_tokens": 2}
    assert events[4][1]["finish_reason"] == "stop"

    detail = await client.get(f"/conversations/{conversation_id}", headers=headers)
    body = detail.json()
    assert body["title"] == "Hi there"
    assert [message["role"] for message in body["messages"]] == ["user", "assistant"]
    assistant = body["messages"][1]
    assert assistant["content"] == "Hello"
    assert assistant["status"] == "completed"
    assert assistant["prompt_tokens"] == 1
    assert assistant["completion_tokens"] == 2


async def test_send_message_requires_ownership(client, api, registry):
    alice = await api.headers("owner@example.com")
    bob = await api.headers("intruder@example.com")
    created = await _create_conversation(client, alice)

    response = await _send(client, bob, created.json()["id"])

    assert response.status_code == 404


async def test_send_message_rejects_blank_content(client, api, registry):
    headers = await api.headers("blank-message@example.com")
    created = await _create_conversation(client, headers)

    response = await _send(client, headers, created.json()["id"], "   ")

    assert response.status_code == 422


async def test_provider_error_emits_event_and_marks_message_failed(
    client, api, registry, fake_provider
):
    from app.providers.base import ProviderError

    fake_provider.error = ProviderError("provider_http_error", "upstream failed")
    headers = await api.headers("provider-error@example.com")
    created = await _create_conversation(client, headers)
    conversation_id = created.json()["id"]

    response = await _send(client, headers, conversation_id)

    events = _parse_sse(response.text)
    assert [event for event, _ in events] == ["meta", "error"]
    assert events[1][1] == {"code": "provider_http_error", "message": "upstream failed"}

    detail = await client.get(f"/conversations/{conversation_id}", headers=headers)
    assistant = detail.json()["messages"][1]
    assert assistant["status"] == "failed"
    assert assistant["prompt_tokens"] is None


async def test_missing_usage_is_reported_as_null(client, api, registry, fake_provider):
    from app.providers.base import ChatChunk

    fake_provider.chunks = [ChatChunk(delta="Hi"), ChatChunk(finish_reason="stop")]
    headers = await api.headers("null-usage@example.com")
    created = await _create_conversation(client, headers)
    conversation_id = created.json()["id"]

    response = await _send(client, headers, conversation_id)

    events = _parse_sse(response.text)
    usage_event = next(data for event, data in events if event == "usage")
    assert usage_event == {"prompt_tokens": None, "completion_tokens": None}

    detail = await client.get(f"/conversations/{conversation_id}", headers=headers)
    assistant = detail.json()["messages"][1]
    assert assistant["prompt_tokens"] is None
    assert assistant["completion_tokens"] is None


async def test_provider_receives_history_and_model(client, api, registry, fake_provider):
    headers = await api.headers("history@example.com")
    created = await _create_conversation(client, headers, model="fake-model")
    conversation_id = created.json()["id"]

    await _send(client, headers, conversation_id, "first")
    await _send(client, headers, conversation_id, "second")

    messages, model = fake_provider.calls[-1]
    assert model == "fake-model"
    assert [(message.role, message.content) for message in messages] == [
        ("user", "first"),
        ("assistant", "Hello"),
        ("user", "second"),
    ]


async def test_owner_can_archive_conversation(client, api, registry):
    headers = await api.headers("archive@example.com")
    created = await _create_conversation(client, headers)
    conversation_id = created.json()["id"]

    archived = await client.delete(f"/conversations/{conversation_id}", headers=headers)
    fetched = await client.get(f"/conversations/{conversation_id}", headers=headers)
    listed = await client.get("/conversations", headers=headers)

    assert archived.status_code == 204
    assert fetched.status_code == 404
    assert listed.json() == []


async def test_archiving_other_users_conversation_returns_404(client, api, registry):
    alice = await api.headers("archive-owner@example.com")
    bob = await api.headers("archive-intruder@example.com")
    created = await _create_conversation(client, alice)

    response = await client.delete(f"/conversations/{created.json()['id']}", headers=bob)

    assert response.status_code == 404


async def test_create_conversation_with_foreign_knowledge_base_returns_404(
    client, api, registry
):
    alice = await api.headers("kb-owner@example.com")
    bob = await api.headers("kb-intruder@example.com")
    kb = await client.post("/knowledge-bases", json={"name": "Alice KB"}, headers=alice)

    response = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model", "kb_id": kb.json()["id"]},
        headers=bob,
    )

    assert response.status_code == 404