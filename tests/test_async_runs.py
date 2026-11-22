import asyncio
import json
from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.models import WorkflowRun, WorkflowRunEvent
from app.providers.base import ChatChunk, ModelInfo, Usage


def _parse_events(text: str) -> list[tuple[str, dict, int | None]]:
    events: list[tuple[str, dict, int | None]] = []
    for block in text.strip().split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        lines = block.splitlines()
        event = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data = json.loads(
            next(line[len("data: ") :] for line in lines if line.startswith("data: "))
        )
        seq = next(
            (int(line[len("id: ") :]) for line in lines if line.startswith("id: ")),
            None,
        )
        events.append((event, data, seq))
    return events


def _llm(node_id: str = "only", prompt: str = "Say hi") -> dict[str, object]:
    return {
        "id": node_id,
        "type": "llm",
        "config": {"provider_id": "fake", "model": "fake-model", "prompt": prompt},
    }


async def _create_workflow(client, headers, nodes=None):
    response = await client.post(
        "/workflows",
        json={
            "name": "Async demo",
            "definition": {"nodes": nodes or [_llm()], "edges": []},
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _post_run(client, headers, workflow_id):
    return await client.post(
        f"/workflows/{workflow_id}/runs", json={"input": "hello"}, headers=headers
    )


async def test_create_run_returns_202_and_replays_events(client, api, registry, fake_provider):
    headers = await api.headers("async-replay@example.com")
    workflow_id = await _create_workflow(client, headers)

    created = await _post_run(client, headers, workflow_id)

    assert created.status_code == 202
    assert created.json()["status"] == "queued"
    run_id = created.json()["run_id"]
    assert (await client.get(f"/workflows/runs/{run_id}", headers=headers)).json()[
        "status"
    ] == "completed"

    replay = await client.get(f"/workflows/runs/{run_id}/events", headers=headers)
    events = _parse_events(replay.text)
    assert [event for event, _, _ in events] == [
        "workflow_start",
        "node_start",
        "node_end",
        "workflow_end",
    ]
    assert [seq for _, _, seq in events] == [1, 2, 3, 4]
    assert events[-1][1]["status"] == "completed"

    tail = await client.get(f"/workflows/runs/{run_id}/events?after=2", headers=headers)
    tail_events = _parse_events(tail.text)
    assert [seq for _, _, seq in tail_events] == [3, 4]
    assert [event for event, _, _ in tail_events] == ["node_end", "workflow_end"]

    resumed = await client.get(
        f"/workflows/runs/{run_id}/events", headers={**headers, "Last-Event-ID": "2"}
    )
    assert [seq for _, _, seq in _parse_events(resumed.text)] == [3, 4]


async def test_run_events_and_cancel_are_workspace_scoped(client, api, registry, fake_provider):
    alice = await api.headers("async-alice@example.com")
    bob = await api.headers("async-bob@example.com")
    workflow_id = await _create_workflow(client, alice)
    created = await _post_run(client, alice, workflow_id)
    run_id = created.json()["run_id"]

    assert (await client.get(f"/workflows/runs/{run_id}/events", headers=bob)).status_code == 404
    assert (await client.post(f"/workflows/runs/{run_id}/cancel", headers=bob)).status_code == 404


async def test_cancel_queued_workflow_run_is_idempotent(client, api):
    from app.main import app
    from app.services.queue import get_queue

    class RecordingQueue:
        def __init__(self) -> None:
            self.calls = []

        async def enqueue_ingestion(self, document_id, *, unique=False) -> None:
            raise AssertionError("unexpected ingestion")

        async def enqueue_evaluation(self, run_id) -> None:
            raise AssertionError("unexpected evaluation")

        async def enqueue_workflow_run(self, run_id) -> None:
            self.calls.append(run_id)

        async def enqueue_collaboration_run(self, run_id) -> None:
            raise AssertionError("unexpected collaboration")

    queue = RecordingQueue()
    previous = app.dependency_overrides[get_queue]
    app.dependency_overrides[get_queue] = lambda: queue
    try:
        headers = await api.headers("async-cancel-queued@example.com")
        workflow_id = await _create_workflow(client, headers)
        created = await _post_run(client, headers, workflow_id)
        run_id = created.json()["run_id"]
        assert (await client.get(f"/workflows/runs/{run_id}", headers=headers)).json()[
            "status"
        ] == "queued"

        first = await client.post(f"/workflows/runs/{run_id}/cancel", headers=headers)
        second = await client.post(f"/workflows/runs/{run_id}/cancel", headers=headers)
    finally:
        app.dependency_overrides[get_queue] = previous

    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"
    assert second.status_code == 200
    assert second.json()["status"] == "cancelled"

    events = _parse_events(
        (await client.get(f"/workflows/runs/{run_id}/events", headers=headers)).text
    )
    assert [event for event, _, _ in events] == ["workflow_end"]
    assert events[0][1]["status"] == "cancelled"

    async with SessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(WorkflowRunEvent).where(WorkflowRunEvent.run_id == UUID(run_id))
                )
            ).scalars()
        )
    assert len(rows) == 1


async def test_cancel_running_workflow_stops_at_node_boundary(client, api):
    from app.deps import get_registry
    from app.main import app
    from app.providers.registry import ProviderRegistry
    from app.services.queue import get_queue
    from app.services.run_execution import execute_workflow_run

    class BlockingProvider:
        id = "fake"

        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def list_models(self):
            return [ModelInfo(id="fake-model", provider_id="fake")]

        async def stream_chat(self, messages, model, **_opts):
            self.started.set()
            await self.release.wait()
            yield ChatChunk(delta="finished")
            yield ChatChunk(usage=Usage(prompt_tokens=1, completion_tokens=1))
            yield ChatChunk(finish_reason="stop")

    class BackgroundQueue:
        def __init__(self) -> None:
            self.tasks: list[asyncio.Task] = []

        async def enqueue_ingestion(self, document_id, *, unique=False) -> None:
            raise AssertionError("unexpected ingestion")

        async def enqueue_evaluation(self, run_id) -> None:
            raise AssertionError("unexpected evaluation")

        async def enqueue_workflow_run(self, run_id) -> None:
            registry = app.dependency_overrides[get_registry]()
            self.tasks.append(
                asyncio.create_task(execute_workflow_run(run_id, provider_registry=registry))
            )

        async def enqueue_collaboration_run(self, run_id) -> None:
            raise AssertionError("unexpected collaboration")

    provider = BlockingProvider()
    queue = BackgroundQueue()
    previous_registry = app.dependency_overrides.get(get_registry)
    previous_queue = app.dependency_overrides[get_queue]
    app.dependency_overrides[get_registry] = lambda: ProviderRegistry({"fake": provider})
    app.dependency_overrides[get_queue] = lambda: queue
    try:
        headers = await api.headers("async-cancel-running@example.com")
        workflow_id = await _create_workflow(client, headers)
        created = await _post_run(client, headers, workflow_id)
        run_id = created.json()["run_id"]
        await asyncio.wait_for(provider.started.wait(), timeout=5)

        cancelled = await client.post(f"/workflows/runs/{run_id}/cancel", headers=headers)
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "running"
        assert cancelled.json()["cancel_requested_at"] is not None
        provider.release.set()
        await asyncio.gather(*queue.tasks)
    finally:
        if previous_registry is None:
            app.dependency_overrides.pop(get_registry, None)
        else:
            app.dependency_overrides[get_registry] = previous_registry
        app.dependency_overrides[get_queue] = previous_queue

    run = await client.get(f"/workflows/runs/{run_id}", headers=headers)
    assert run.json()["status"] == "cancelled"
    events = _parse_events(
        (await client.get(f"/workflows/runs/{run_id}/events", headers=headers)).text
    )
    assert events[-1][0] == "workflow_end"
    assert events[-1][1]["status"] == "cancelled"


class _CollaborationProvider:
    id = "fake"

    def __init__(self) -> None:
        self.models = []

    async def list_models(self):
        return []

    async def stream_chat(self, messages, model, **_opts):
        system = messages[0].content if messages and messages[0].role == "system" else ""
        user = messages[-1].content if messages else ""
        if "You are the planner" in system:
            output = json.dumps(
                {
                    "tasks": [
                        {"id": "t1", "agent": "retrieval", "task": "task-one"},
                        {"id": "t2", "agent": "math", "task": "task-two"},
                    ]
                }
            )
        elif "You are the critic" in system:
            output = json.dumps({"verdict": "accept", "final_answer": "FINAL", "feedback": ""})
        else:
            output = json.dumps({"action": "final", "answer": "A" if "task-one" in user else "B"})
        yield ChatChunk(delta=output)
        yield ChatChunk(usage=Usage(prompt_tokens=1, completion_tokens=1))
        yield ChatChunk(finish_reason="stop")


async def test_collaboration_run_is_queued_and_replays_events(client, api):
    from app.deps import get_registry
    from app.main import app
    from app.providers.registry import ProviderRegistry

    previous = app.dependency_overrides.get(get_registry)
    app.dependency_overrides[get_registry] = lambda: ProviderRegistry(
        {"fake": _CollaborationProvider()}
    )
    try:
        headers = await api.headers("async-collab@example.com")
        created = await client.post(
            "/collaborations/runs",
            json={"input": "research this", "provider_id": "fake", "model": "fake-model"},
            headers=headers,
        )
        assert created.status_code == 202
        run_id = created.json()["run_id"]
        events = _parse_events(
            (await client.get(f"/collaborations/runs/{run_id}/events", headers=headers)).text
        )
        detail = await client.get(f"/collaborations/runs/{run_id}", headers=headers)
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_registry, None)
        else:
            app.dependency_overrides[get_registry] = previous

    assert events[0][0] == "collaboration_start"
    assert events[-1][0] == "collaboration_end"
    assert events[-1][1]["status"] == "completed"
    assert [seq for _, _, seq in events] == list(range(1, len(events) + 1))
    assert detail.json()["status"] == "completed"
    assert detail.json()["cancel_requested_at"] is None


async def test_unknown_workflow_run_events_return_404(client, api):
    headers = await api.headers("async-missing@example.com")
    response = await client.get(
        "/workflows/runs/00000000-0000-0000-0000-000000000000/events", headers=headers
    )
    assert response.status_code == 404


async def test_worker_execution_is_idempotent_for_terminal_runs(
    client, api, registry, fake_provider
):
    from app.services.run_execution import execute_workflow_run

    headers = await api.headers("async-idempotent@example.com")
    workflow_id = await _create_workflow(client, headers)
    created = await _post_run(client, headers, workflow_id)
    run_id = UUID(created.json()["run_id"])

    async with SessionLocal() as session:
        run = await session.get(WorkflowRun, run_id)
        assert run is not None and run.status == "completed"
        before = (
            (
                await session.execute(
                    select(WorkflowRunEvent.seq).where(WorkflowRunEvent.run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
    await execute_workflow_run(run_id, provider_registry=registry)
    async with SessionLocal() as session:
        after = (
            (
                await session.execute(
                    select(WorkflowRunEvent.seq).where(WorkflowRunEvent.run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
    assert list(after) == list(before)
