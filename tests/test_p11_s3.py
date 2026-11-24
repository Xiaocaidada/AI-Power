import json

VALID_DEFINITION = {
    "nodes": [
        {"id": "start", "type": "start", "config": {}},
        {"id": "out", "type": "output", "config": {}},
    ],
    "edges": [{"from": "start", "to": "out"}],
}


async def _session(client, headers) -> str:
    created = await client.post(
        "/agent-builder/sessions",
        json={
            "scope": "agent",
            "provider_id": "fake",
            "model": "fake-model",
            "draft_definition": VALID_DEFINITION,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_builder_clarification_and_history(client, api, registry, fake_provider):
    headers = await api.headers("p11s3-builder@example.com")
    session_id = await _session(client, headers)

    fake_provider.complete_content = json.dumps(
        {
            "message": "I need one detail before building.",
            "clarification": "Should the agent use web search or only a knowledge base?",
            "suggestions": [],
            "missing_resources": [],
        }
    )
    first = await client.post(
        f"/agent-builder/sessions/{session_id}/messages",
        json={
            "kind": "modify",
            "prompt": "Build a research assistant.",
            "current_definition": VALID_DEFINITION,
        },
        headers=headers,
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["definition"] is None
    assert body["clarification"].startswith("Should the agent use web search")

    fake_provider.complete_content = json.dumps(
        {
            "message": "Built the flow.",
            "summary": "Minimal research flow",
            "definition": VALID_DEFINITION,
            "missing_resources": [],
            "suggestions": ["Add a retrieval node later"],
        }
    )
    second = await client.post(
        f"/agent-builder/sessions/{session_id}/messages",
        json={
            "kind": "modify",
            "prompt": "Use a knowledge base only.",
            "current_definition": VALID_DEFINITION,
        },
        headers=headers,
    )
    assert second.status_code == 200, second.text
    definition = second.json()["definition"]
    assert [node["id"] for node in definition["nodes"]] == ["start", "out"]
    assert definition["edges"][0]["from"] == "start"
    assert second.json()["clarification"] is None

    messages = fake_provider.complete_calls[-1][0]
    assert any(
        "Should the agent use web search" in getattr(message, "content", "")
        for message in messages
    )

    session = await client.get(
        f"/agent-builder/sessions/{session_id}", headers=headers
    )
    assert session.status_code == 200
    assistant = [
        item
        for item in session.json()["messages"]
        if item["role"] == "assistant"
    ]
    assert any(item.get("clarification") for item in assistant)
    assert any(item.get("definition") for item in assistant)