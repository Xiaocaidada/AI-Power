import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.models import ChatTask, ChatTaskEvent
from app.providers.base import ProviderError
from app.services.chat_tasks import execute_chat_task, requeue_stale_tasks


def _events(text: str) -> list[tuple[int, str, dict]]:
    rows: list[tuple[int, str, dict]] = []
    for block in text.strip().split("\n\n"):
        if not block.strip() or block.startswith(":"):
            continue
        seq = None
        event = None
        data = None
        for line in block.splitlines():
            if line.startswith("id: "):
                seq = int(line[4:])
            elif line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if seq is not None and event is not None:
            rows.append((seq, event, data or {}))
    return rows


async def _create(client, headers, steps=None, fake_provider=None):
    if fake_provider is not None and steps is not None:
        fake_provider.complete_contents = list(steps)
    return await client.post(
        "/chat-tasks",
        json={
            "kind": "llm_steps",
            "title": "Test task",
            "provider_id": "fake",
            "model": "fake-model",
            "steps": steps or ["step one", "step two"],
        },
        headers=headers,
    )


async def test_task_completes_and_events_replay(client, api, registry, fake_provider):
    headers = await api.headers("p12-s5-complete@example.com")

    created = await _create(client, headers, ["one", "two"], fake_provider)
    task_id = created.json()["id"]

    assert created.status_code == 202
    detail = await client.get(f"/chat-tasks/{task_id}", headers=headers)
    body = detail.json()
    assert body["status"] == "completed"
    assert body["checkpoint"]["completed_steps"] == 2
    assert body["result"]["text"] == "one\n\ntwo"
    assert body["attempts"] == 1
    assert body["plan"]["steps"][0]["status"] == "done"

    stream = await client.get(f"/chat-tasks/{task_id}/events?after=0", headers=headers)
    events = _events(stream.text)
    names = [event for _, event, _ in events]
    assert names[0] == "task_created"
    assert names[-1] == "task_completed"
    assert names.count("step_completed") == 2
    assert [seq for seq, _, _ in events] == list(range(1, len(events) + 1))

    replay = await client.get(f"/chat-tasks/{task_id}/events?after=2", headers=headers)
    assert all(seq > 2 for seq, _, _ in _events(replay.text))


async def test_pause_and_resume(client, api, registry, fake_provider, fake_queue):
    headers = await api.headers("p12-s5-pause@example.com")
    fake_queue.defer_chat_tasks = True
    created = await _create(client, headers, ["one"], fake_provider)
    task_id = created.json()["id"]

    paused = await client.post(f"/chat-tasks/{task_id}/pause", headers=headers)
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    fake_queue.defer_chat_tasks = False
    resumed = await client.post(f"/chat-tasks/{task_id}/resume", headers=headers)
    detail = await client.get(f"/chat-tasks/{task_id}", headers=headers)

    assert resumed.status_code == 200
    assert detail.json()["status"] == "completed"
    assert detail.json()["checkpoint"]["completed_steps"] == 1


async def test_running_task_pauses_at_boundary(client, api, registry, fake_provider, fake_queue):
    headers = await api.headers("p12-s5-boundary@example.com")
    fake_queue.defer_chat_tasks = True
    created = await _create(client, headers, ["one", "two"], fake_provider)
    task_id = created.json()["id"]
    async with SessionLocal() as session:
        task = await session.get(ChatTask, UUID(task_id))
        task.pause_requested_at = datetime.now(UTC)
        task.status = "queued"
        await session.commit()

    await execute_chat_task(UUID(task_id), registry)

    detail = await client.get(f"/chat-tasks/{task_id}", headers=headers)
    assert detail.json()["status"] == "paused"
    assert detail.json()["checkpoint"]["completed_steps"] == 0


async def test_cancel_is_idempotent(client, api, registry, fake_provider, fake_queue):
    headers = await api.headers("p12-s5-cancel@example.com")
    fake_queue.defer_chat_tasks = True
    created = await _create(client, headers, ["one"], fake_provider)
    task_id = created.json()["id"]

    first = await client.post(f"/chat-tasks/{task_id}/cancel", headers=headers)
    second = await client.post(f"/chat-tasks/{task_id}/cancel", headers=headers)

    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"
    assert second.status_code == 200
    assert second.json()["status"] == "cancelled"


async def test_retry_resumes_from_checkpoint(client, api, registry, fake_provider, fake_queue):
    headers = await api.headers("p12-s5-retry@example.com")
    fake_provider.complete_contents = ["one", "two"]
    original = fake_provider.complete
    calls = {"count": 0}

    async def flaky_complete(messages, model, **opts):
        calls["count"] += 1
        if calls["count"] == 2:
            raise ProviderError("provider_http_error", "boom")
        return await original(messages, model, **opts)

    fake_provider.complete = flaky_complete
    created = await _create(client, headers, ["one", "two"], None)
    task_id = created.json()["id"]
    failed = await client.get(f"/chat-tasks/{task_id}", headers=headers)
    assert failed.json()["status"] == "failed"
    assert failed.json()["checkpoint"]["completed_steps"] == 1

    fake_provider.complete = original
    fake_provider.complete_contents = ["two again"]
    retried = await client.post(f"/chat-tasks/{task_id}/retry", headers=headers)
    detail = await client.get(f"/chat-tasks/{task_id}", headers=headers)

    assert retried.status_code == 200
    assert detail.json()["status"] == "completed"
    assert detail.json()["checkpoint"]["completed_steps"] == 2
    assert detail.json()["result"]["outputs"] == ["one", "two again"]
    assert len(fake_provider.complete_calls) == 2


async def test_cross_user_isolation(client, api, registry, fake_provider, fake_queue):
    alice = await api.headers("p12-s5-alice@example.com")
    bob = await api.headers("p12-s5-bob@example.com")
    fake_queue.defer_chat_tasks = True
    created = await _create(client, alice, ["one"], fake_provider)

    response = await client.get(f"/chat-tasks/{created.json()['id']}", headers=bob)
    listed = await client.get("/chat-tasks", headers=bob)

    assert response.status_code == 404
    assert listed.json() == []


async def test_stale_task_is_requeued(client, api, registry, fake_provider, fake_queue):
    headers = await api.headers("p12-s5-stale@example.com")
    fake_queue.defer_chat_tasks = True
    created = await _create(client, headers, ["one"], fake_provider)
    task_id = created.json()["id"]
    async with SessionLocal() as session:
        task = await session.get(ChatTask, UUID(task_id))
        task.status = "running"
        task.lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()
    async with SessionLocal() as session:
        requeued = await requeue_stale_tasks(session)
        events = list(
            (
                await session.execute(
                    select(ChatTaskEvent).where(ChatTaskEvent.task_id == UUID(task_id))
                )
            ).scalars()
        )
    detail = await client.get(f"/chat-tasks/{task_id}", headers=headers)

    assert requeued == [UUID(task_id)]
    assert detail.json()["status"] == "queued"
    assert any(event.event == "task_requeued" for event in events)
