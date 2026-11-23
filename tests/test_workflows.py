import json

import pytest

from app.providers.base import ChatChunk, ModelInfo, ProviderError, Usage


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        event = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data = json.loads(
            next(line[len("data: ") :] for line in lines if line.startswith("data: "))
        )
        events.append((event, data))
    return events


def _llm(node_id: str, prompt: str) -> dict[str, object]:
    return {
        "id": node_id,
        "type": "llm",
        "config": {"provider_id": "fake", "model": "fake-model", "prompt": prompt},
    }


def _linear_definition() -> dict[str, object]:
    return {
        "nodes": [_llm("first", "Say hi"), _llm("second", "Repeat: {{first}}")],
        "edges": [{"from": "first", "to": "second"}],
    }


async def _create_workflow(client, headers, definition=None):
    return await client.post(
        "/workflows",
        json={
            "name": "Demo",
            "description": "two llm nodes",
            "definition": definition or _linear_definition(),
        },
        headers=headers,
    )


async def _run(client, headers, workflow_id, payload=None):
    created = await client.post(
        f"/workflows/{workflow_id}/runs",
        json=payload or {"input": "hello"},
        headers=headers,
    )
    if created.status_code != 202:
        return created
    run_id = created.json()["run_id"]
    return await client.get(f"/workflows/runs/{run_id}/events", headers=headers)


@pytest.mark.parametrize(
    "definition",
    [
        {"nodes": [], "edges": []},
        {"nodes": [_llm("a", "x"), _llm("a", "y")], "edges": []},
        {"nodes": [_llm("a", "x"), {"id": "b", "type": "nope", "config": {}}], "edges": []},
        {
            "nodes": [_llm("a", "x"), _llm("b", "y")],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
        },
        {"nodes": [_llm("a", "x"), _llm("b", "y")], "edges": []},
        {
            "nodes": [_llm("a", "x"), _llm("b", "y")],
            "edges": [{"from": "a", "to": "missing"}],
        },
        {
            "nodes": [{"id": "a", "type": "llm", "config": {"provider_id": "fake"}}],
            "edges": [],
        },
        {
            "nodes": [
                _llm("a", "x"),
                {"id": "c", "type": "condition", "config": {"left": "x", "operator": "contains"}},
                _llm("yes", "y"),
                _llm("no", "z"),
            ],
            "edges": [
                {"from": "a", "to": "c"},
                {"from": "c", "to": "yes", "when": "true"},
            ],
        },
        {
            "nodes": [
                {"id": "p", "type": "parallel", "config": {}},
                _llm("a", "x"),
                _llm("j", "y"),
            ],
            "edges": [{"from": "p", "to": "a"}, {"from": "a", "to": "j"}],
        },
        {
            "nodes": [
                {"id": "p", "type": "parallel", "config": {}},
                _llm("a", "x"),
                _llm("b", "y"),
                {"id": "j", "type": "join", "config": {}},
            ],
            "edges": [
                {"from": "p", "to": "a"},
                {"from": "p", "to": "b"},
                {"from": "a", "to": "j"},
            ],
        },
        {
            "nodes": [_llm("a", "x"), _llm("b", "y")],
            "edges": [{"from": "a", "to": "b", "when": "true"}],
        },
    ],
)
async def test_invalid_workflow_definitions_are_rejected(client, api, definition):
    headers = await api.headers(f"wf-invalid-{abs(hash(str(definition)))}@example.com")

    response = await client.post(
        "/workflows",
        json={"name": "Bad", "definition": definition},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_workflow"


async def test_workflow_runs_linear_nodes_and_persists_state(client, api, registry, fake_provider):
    headers = await api.headers("wf-linear@example.com")
    workflow = await _create_workflow(client, headers)
    assert workflow.status_code == 201
    workflow_id = workflow.json()["id"]

    response = await _run(client, headers, workflow_id)

    assert response.status_code == 200
    events = _parse_sse(response.text)
    kinds = [event for event, _ in events]
    assert kinds == [
        "workflow_start",
        "node_start",
        "node_end",
        "node_start",
        "node_end",
        "workflow_end",
    ]
    first_end, second_end = [data for event, data in events if event == "node_end"]
    assert first_end["status"] == "completed"
    assert first_end["output"] == "Hello"
    assert second_end["output"] == "Hello"
    end = events[-1][1]
    assert end["status"] == "completed"
    assert end["prompt_tokens"] == 2
    assert end["completion_tokens"] == 4
    assert len(fake_provider.calls) == 2
    assert fake_provider.calls[1][0][-1].content == "Repeat: Hello"

    run = await client.get(f"/workflows/runs/{end['run_id']}", headers=headers)
    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "completed"
    assert body["prompt_tokens"] == 2
    assert [node["node_id"] for node in body["nodes"]] == ["first", "second"]
    assert all(node["status"] == "completed" for node in body["nodes"])

    listed = await client.get(f"/workflows/{workflow_id}/runs", headers=headers)
    assert [item["id"] for item in listed.json()] == [end["run_id"]]


async def test_workflow_retries_provider_failure_before_failing(client, api):
    from app.deps import get_registry
    from app.main import app
    from app.providers.registry import ProviderRegistry

    class FlakyProvider:
        id = "fake"

        def __init__(self) -> None:
            self.calls = 0

        async def list_models(self):
            return [ModelInfo(id="fake-model", provider_id="fake")]

        async def stream_chat(self, messages, model, **_opts):
            self.calls += 1
            if self.calls == 1:
                raise ProviderError("provider_http_error", "boom")
            yield ChatChunk(delta="recovered")
            yield ChatChunk(usage=Usage(prompt_tokens=1, completion_tokens=1))
            yield ChatChunk(finish_reason="stop")

    provider = FlakyProvider()
    app.dependency_overrides[get_registry] = lambda: ProviderRegistry({"fake": provider})
    try:
        headers = await api.headers("wf-retry@example.com")
        created = await _create_workflow(
            client, headers, {"nodes": [_llm("only", "Say hi")], "edges": []}
        )
        response = await _run(client, headers, created.json()["id"], {"input": "hi"})
    finally:
        app.dependency_overrides.pop(get_registry, None)

    events = _parse_sse(response.text)
    node_end = next(data for event, data in events if event == "node_end")
    assert node_end["status"] == "completed"
    assert node_end["attempts"] == 2
    assert provider.calls == 2
    end = events[-1][1]
    assert end["status"] == "completed"
    run = await client.get(f"/workflows/runs/{end['run_id']}", headers=headers)
    assert run.json()["nodes"][0]["attempts"] == 2


async def test_workflow_node_failure_marks_run_failed(client, api, registry, fake_provider):
    fake_provider.error = ProviderError("provider_http_error", "down")
    headers = await api.headers("wf-fail@example.com")
    created = await _create_workflow(
        client, headers, {"nodes": [_llm("only", "Say hi")], "edges": []}
    )

    response = await _run(client, headers, created.json()["id"])

    events = _parse_sse(response.text)
    node_end = next(data for event, data in events if event == "node_end")
    assert node_end["status"] == "failed"
    assert node_end["error_code"] == "provider_http_error"
    end = events[-1][1]
    assert end["status"] == "failed"
    run = await client.get(f"/workflows/runs/{end['run_id']}", headers=headers)
    assert run.json()["status"] == "failed"
    assert run.json()["nodes"][0]["attempts"] == 2


async def test_workflow_kb_search_node(
    client, api, registry, fake_provider, fake_ingestion, fake_retrieval
):
    headers = await api.headers("wf-kb@example.com")
    kb = await client.post("/knowledge-bases", json={"name": "WF KB"}, headers=headers)
    kb_id = kb.json()["id"]
    await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("note.txt", b"hello world", "text/plain")},
        headers=headers,
    )
    definition = {
        "nodes": [
            {
                "id": "search",
                "type": "kb_search",
                "config": {"query": "hello {{input}}"},
            }
        ],
        "edges": [],
    }
    created = await _create_workflow(client, headers, definition)

    response = await _run(client, headers, created.json()["id"], {"input": "world", "kb_id": kb_id})

    events = _parse_sse(response.text)
    node_end = next(data for event, data in events if event == "node_end")
    assert node_end["status"] == "completed"
    assert "hello world" in node_end["output"]

    missing = await _run(client, headers, created.json()["id"], {"input": "world"})
    missing_events = _parse_sse(missing.text)
    missing_node = next(data for event, data in missing_events if event == "node_end")
    assert missing_node["error_code"] == "no_knowledge_base"


async def test_workflows_are_workspace_scoped(client, api):
    alice = await api.headers("wf-alice@example.com")
    bob = await api.headers("wf-bob@example.com")
    created = await _create_workflow(client, alice)
    workflow_id = created.json()["id"]

    for response in (
        await client.get(f"/workflows/{workflow_id}", headers=bob),
        await client.get(f"/workflows/{workflow_id}/runs", headers=bob),
        await _run(client, bob, workflow_id),
    ):
        assert response.status_code == 404
    assert (await client.get("/workflows", headers=bob)).json() == []


async def test_condition_skips_the_other_branch(client, api, registry, fake_provider):
    headers = await api.headers("wf-condition@example.com")
    definition = {
        "nodes": [
            _llm("first", "Say hi"),
            {
                "id": "check",
                "type": "condition",
                "config": {"left": "{{first}}", "operator": "contains", "right": "Hello"},
            },
            _llm("yes", "YES"),
            _llm("no", "NO"),
        ],
        "edges": [
            {"from": "first", "to": "check"},
            {"from": "check", "to": "yes", "when": "true"},
            {"from": "check", "to": "no", "when": "false"},
        ],
    }
    created = await _create_workflow(client, headers, definition)

    response = await _run(client, headers, created.json()["id"])

    events = _parse_sse(response.text)
    statuses = {data["node_id"]: data["status"] for event, data in events if event == "node_end"}
    assert statuses == {
        "first": "completed",
        "check": "completed",
        "yes": "completed",
        "no": "skipped",
    }
    end = events[-1][1]
    assert end["status"] == "completed"
    assert end["output"] == "Hello"
    assert len(fake_provider.calls) == 2
    run = await client.get(f"/workflows/runs/{end['run_id']}", headers=headers)
    assert run.json()["nodes"][-1]["status"] in {"completed", "skipped"}


async def test_parallel_branches_run_concurrently_and_join(client, api):
    import asyncio

    from app.deps import get_registry
    from app.main import app
    from app.providers.registry import ProviderRegistry

    class ConcurrentProvider:
        id = "fake"

        def __init__(self) -> None:
            self.active = 0
            self.peak = 0
            self.both_started = asyncio.Event()

        async def list_models(self):
            return [ModelInfo(id="fake-model", provider_id="fake")]

        async def stream_chat(self, messages, model, **_opts):
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active >= 2:
                self.both_started.set()
            try:
                # Deterministic concurrency check: both branches must reach the
                # provider before either can finish.
                await asyncio.wait_for(self.both_started.wait(), timeout=5)
            finally:
                self.active -= 1
            text = messages[-1].content
            output = "left-out" if text.startswith("L") else "right-out"
            yield ChatChunk(delta=output)
            yield ChatChunk(usage=Usage(prompt_tokens=1, completion_tokens=1))
            yield ChatChunk(finish_reason="stop")

    provider = ConcurrentProvider()
    app.dependency_overrides[get_registry] = lambda: ProviderRegistry({"fake": provider})
    definition = {
        "nodes": [
            {"id": "fan", "type": "parallel", "config": {}},
            _llm("left", "L {{input}}"),
            _llm("right", "R {{input}}"),
            {"id": "join", "type": "join", "config": {}},
        ],
        "edges": [
            {"from": "fan", "to": "left"},
            {"from": "fan", "to": "right"},
            {"from": "left", "to": "join"},
            {"from": "right", "to": "join"},
        ],
    }
    try:
        headers = await api.headers("wf-parallel@example.com")
        created = await _create_workflow(client, headers, definition)
        response = await _run(client, headers, created.json()["id"], {"input": "x"})
    finally:
        app.dependency_overrides.pop(get_registry, None)

    events = _parse_sse(response.text)
    join_end = next(
        data for event, data in events if event == "node_end" and data["node_id"] == "join"
    )
    assert join_end["status"] == "completed"
    assert join_end["output"] == "left-out\nright-out"
    assert provider.peak >= 2
    assert events[-1][1]["status"] == "completed"


async def test_tool_node_runs_calculator(client, api, registry):
    headers = await api.headers("wf-tool@example.com")
    definition = {
        "nodes": [
            {
                "id": "calc",
                "type": "tool",
                "config": {"tool": "calculator", "arguments": {"expression": "2+2"}},
            }
        ],
        "edges": [],
    }
    created = await _create_workflow(client, headers, definition)

    response = await _run(client, headers, created.json()["id"])

    events = _parse_sse(response.text)
    node_end = next(data for event, data in events if event == "node_end")
    assert node_end["status"] == "completed"
    assert node_end["output"] == "4"


async def test_agent_node_runs_supervisor(client, api, registry):
    from app.deps import get_registry
    from app.main import app
    from app.providers.registry import ProviderRegistry

    class ScriptedProvider:
        id = "fake"

        def __init__(self) -> None:
            self.calls = 0

        async def list_models(self):
            return [ModelInfo(id="fake-model", provider_id="fake")]

        async def stream_chat(self, messages, model, **_opts):
            self.calls += 1
            yield ChatChunk(delta=json.dumps({"action": "final", "answer": "agent done"}))
            yield ChatChunk(usage=Usage(prompt_tokens=2, completion_tokens=3))
            yield ChatChunk(finish_reason="stop")

    provider = ScriptedProvider()
    app.dependency_overrides[get_registry] = lambda: ProviderRegistry({"fake": provider})
    definition = {
        "nodes": [
            {
                "id": "ask",
                "type": "agent",
                "config": {
                    "provider_id": "fake",
                    "model": "fake-model",
                    "task": "Summarize {{input}}",
                },
            }
        ],
        "edges": [],
    }
    try:
        headers = await api.headers("wf-agent@example.com")
        created = await _create_workflow(client, headers, definition)
        response = await _run(client, headers, created.json()["id"], {"input": "docs"})
    finally:
        app.dependency_overrides.pop(get_registry, None)

    events = _parse_sse(response.text)
    node_end = next(data for event, data in events if event == "node_end")
    assert node_end["status"] == "completed"
    assert node_end["output"] == "agent done"
    assert provider.calls == 1
    assert events[-1][1]["prompt_tokens"] == 2


async def test_workflow_run_requires_workflow_scope_for_api_keys(client, api, registry):
    headers = await api.headers("wf-scope@example.com")
    created = await _create_workflow(client, headers)
    workflow_id = created.json()["id"]
    valid_key = await client.post(
        "/api-keys",
        json={"name": "workflow", "scopes": ["workflow:run"]},
        headers=headers,
    )
    chat_key = await client.post(
        "/api-keys",
        json={"name": "chat", "scopes": ["chat:write"]},
        headers=headers,
    )

    key_headers = {"X-API-Key": valid_key.json()["key"]}
    allowed = await client.post(
        f"/workflows/{workflow_id}/runs",
        json={"input": "hello"},
        headers=key_headers,
    )
    denied = await client.post(
        f"/workflows/{workflow_id}/runs",
        json={"input": "hello"},
        headers={"X-API-Key": chat_key.json()["key"]},
    )

    assert allowed.status_code == 202
    events = await client.get(
        f"/workflows/runs/{allowed.json()['run_id']}/events", headers=key_headers
    )
    assert events.status_code == 200
    assert "workflow_start" in events.text
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "insufficient_scope"
