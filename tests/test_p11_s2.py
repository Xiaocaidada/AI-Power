import json


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        event = next(
            line[len("event: ") :] for line in lines if line.startswith("event: ")
        )
        data = json.loads(
            next(line[len("data: ") :] for line in lines if line.startswith("data: "))
        )
        events.append((event, data))
    return events


def _llm(node_id: str, prompt: str) -> dict:
    return {
        "id": node_id,
        "type": "llm",
        "config": {"provider_id": "fake", "model": "fake-model", "prompt": prompt},
    }


def _definition() -> dict:
    return {
        "nodes": [_llm("first", "Say hi"), _llm("second", "Repeat: {{first}}")],
        "edges": [{"from": "first", "to": "second"}],
    }


async def _workflow(client, headers) -> str:
    created = await client.post(
        "/workflows",
        json={"name": "P11 S2", "description": "", "definition": _definition()},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_debug_single_node_with_seed_outputs(client, api, registry):
    headers = await api.headers("p11s2-debug@example.com")
    workflow_id = await _workflow(client, headers)
    debugged = await client.post(
        f"/workflows/{workflow_id}/nodes/second/debug",
        json={"input": "hello", "node_outputs": {"first": "seed output"}},
        headers=headers,
    )
    assert debugged.status_code == 200, debugged.text
    payload = debugged.json()
    assert payload["node_id"] == "second"
    assert payload["node_type"] == "llm"
    assert payload["status"] == "completed"
    assert payload["output"] == "Hello"
    assert "seed output" in payload["input_summary"]
    assert payload["node_run_id"] is not None
    assert len(registry.get("fake").calls) == 1

    run = await client.get(
        f"/workflows/runs/{payload['run_id']}", headers=headers
    )
    assert run.status_code == 200
    assert run.json()["status"] == "completed"
    assert [node["node_id"] for node in run.json()["nodes"]] == ["second"]
    assert run.json()["nodes"][0]["status"] == "completed"


async def test_run_from_selected_node_skips_upstream(client, api, registry):
    headers = await api.headers("p11s2-start@example.com")
    workflow_id = await _workflow(client, headers)
    started = await client.post(
        f"/workflows/{workflow_id}/runs",
        json={
            "input": "hello",
            "start_node_id": "second",
            "node_outputs": {"first": "seeded"},
        },
        headers=headers,
    )
    assert started.status_code == 202, started.text
    events = await client.get(
        f"/workflows/runs/{started.json()['run_id']}/events", headers=headers
    )
    assert events.status_code == 200, events.text
    parsed = _parse_sse(events.text)
    starts = [data["node_id"] for event, data in parsed if event == "node_start"]
    assert starts == ["second"]
    end = next(data for event, data in parsed if event == "workflow_end")
    assert end["status"] == "completed"
    assert len(registry.get("fake").calls) == 1


async def test_debug_and_start_node_validation(client, api):
    headers = await api.headers("p11s2-invalid@example.com")
    workflow_id = await _workflow(client, headers)
    debug_missing = await client.post(
        f"/workflows/{workflow_id}/nodes/missing/debug",
        json={"input": "hello"},
        headers=headers,
    )
    assert debug_missing.status_code == 404
    start_missing = await client.post(
        f"/workflows/{workflow_id}/runs",
        json={"input": "hello", "start_node_id": "missing"},
        headers=headers,
    )
    assert start_missing.status_code == 404
    assert start_missing.json()["detail"]["code"] == "node_not_found"


async def test_debug_is_workspace_scoped(client, api):
    owner = await api.headers("p11s2-owner@example.com")
    other = await api.headers("p11s2-other@example.com")
    workflow_id = await _workflow(client, owner)
    denied = await client.post(
        f"/workflows/{workflow_id}/nodes/second/debug",
        json={"input": "hello"},
        headers=other,
    )
    assert denied.status_code == 404