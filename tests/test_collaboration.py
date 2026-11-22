import json

from app.providers.base import ChatChunk, ModelInfo, Usage


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


class CollaborationProvider:
    id = "fake"

    def __init__(self, *, revise_once: bool = False, plan_output: str | None = None) -> None:
        self.revise_once = revise_once
        self.plan_output = plan_output
        self.critic_calls = 0
        self.calls: list[list[object]] = []
        self.models = [ModelInfo(id="fake-model", provider_id="fake")]

    async def list_models(self):
        return list(self.models)

    async def stream_chat(self, messages, model, **_opts):
        self.calls.append(list(messages))
        system = messages[0].content if messages and messages[0].role == "system" else ""
        user = messages[-1].content if messages else ""
        if "You are the planner" in system:
            output = self.plan_output or json.dumps(
                {
                    "tasks": [
                        {"id": "t1", "agent": "retrieval", "task": "task-one"},
                        {"id": "t2", "agent": "math", "task": "task-two"},
                    ]
                }
            )
        elif "You are the critic" in system:
            self.critic_calls += 1
            if self.revise_once and self.critic_calls == 1:
                output = json.dumps(
                    {"verdict": "revise", "final_answer": "", "feedback": "improve"}
                )
            else:
                suffix = "2" if self.critic_calls > 1 else ""
                output = json.dumps(
                    {"verdict": "accept", "final_answer": f"FINAL{suffix}", "feedback": ""}
                )
        elif "Critic feedback" in user:
            output = json.dumps({"action": "final", "answer": "A2" if "task-one" in user else "B2"})
        else:
            output = json.dumps({"action": "final", "answer": "A" if "task-one" in user else "B"})
        yield ChatChunk(delta=output)
        yield ChatChunk(usage=Usage(prompt_tokens=1, completion_tokens=1))
        yield ChatChunk(finish_reason="stop")


def _use_provider(provider: CollaborationProvider):
    from app.deps import get_registry
    from app.main import app
    from app.providers.registry import ProviderRegistry

    app.dependency_overrides[get_registry] = lambda: ProviderRegistry({"fake": provider})


def _clear_provider():
    from app.deps import get_registry
    from app.main import app

    app.dependency_overrides.pop(get_registry, None)


async def _run(client, headers, payload=None):
    created = await client.post(
        "/collaborations/runs",
        json=payload or {"input": "research this", "provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )
    if created.status_code != 202:
        return created
    run_id = created.json()["run_id"]
    return await client.get(f"/collaborations/runs/{run_id}/events", headers=headers)


async def test_collaboration_plans_workers_and_accepts(client, api, registry):
    provider = CollaborationProvider()
    _use_provider(provider)
    try:
        headers = await api.headers("collab-accept@example.com")
        response = await _run(client, headers)
    finally:
        _clear_provider()

    events = _parse_sse(response.text)
    kinds = [event for event, _ in events]
    assert kinds[0] == "collaboration_start"
    assert "planner_start" in kinds and "planner_end" in kinds
    assert kinds.count("worker_start") == 2
    assert kinds.count("worker_end") == 2
    assert "critic_start" in kinds and "critic_end" in kinds
    end = events[-1][1]
    assert end["status"] == "completed"
    assert end["rounds"] == 1
    assert end["output"] == "FINAL"
    assert len(provider.calls) == 4

    run = await client.get(f"/collaborations/runs/{end['run_id']}", headers=headers)
    body = run.json()
    assert body["status"] == "completed"
    assert body["final_output"] == "FINAL"
    assert [task["id"] for task in body["plan"]] == ["t1", "t2"]
    assert sorted(step["role"] for step in body["steps"]) == [
        "critic",
        "planner",
        "worker",
        "worker",
    ]


async def test_collaboration_revises_once(client, api, registry):
    provider = CollaborationProvider(revise_once=True)
    _use_provider(provider)
    try:
        headers = await api.headers("collab-revise@example.com")
        response = await _run(client, headers)
    finally:
        _clear_provider()

    events = _parse_sse(response.text)
    critic_ends = [data for event, data in events if event == "critic_end"]
    assert [item["verdict"] for item in critic_ends] == ["revise", "accept"]
    assert _count(events, "worker_start") == 4
    end = events[-1][1]
    assert end["rounds"] == 2
    assert end["output"] == "FINAL2"
    run = await client.get(f"/collaborations/runs/{end['run_id']}", headers=headers)
    assert run.json()["rounds"] == 2
    assert len([step for step in run.json()["steps"] if step["role"] == "worker"]) == 4


def _count(events, kind):
    return len([event for event, _ in events if event == kind])


async def test_collaboration_invalid_plan_fails(client, api, registry):
    provider = CollaborationProvider(plan_output="not json")
    _use_provider(provider)
    try:
        headers = await api.headers("collab-bad-plan@example.com")
        response = await _run(client, headers)
    finally:
        _clear_provider()

    events = _parse_sse(response.text)
    end = events[-1][1]
    assert end["status"] == "failed"
    assert end["error_code"] == "invalid_plan"
    run = await client.get(f"/collaborations/runs/{end['run_id']}", headers=headers)
    assert run.json()["status"] == "failed"


async def test_collaboration_runs_are_workspace_scoped(client, api, registry):
    provider = CollaborationProvider()
    _use_provider(provider)
    try:
        alice = await api.headers("collab-alice@example.com")
        bob = await api.headers("collab-bob@example.com")
        response = await _run(client, alice)
    finally:
        _clear_provider()

    run_id = _parse_sse(response.text)[-1][1]["run_id"]
    assert (await client.get(f"/collaborations/runs/{run_id}", headers=bob)).status_code == 404
    assert (await client.get("/collaborations/runs", headers=bob)).json() == []
