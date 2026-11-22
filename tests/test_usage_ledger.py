import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    ApiKey,
    AuditLog,
    CollaborationRun,
    Conversation,
    ModelCatalog,
    UsageEvent,
    WorkflowRun,
    Workspace,
    WorkspaceMember,
)


def _range() -> str:
    end = (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"from=2026-11-20T00:00:00Z&to={end}"


async def _setup(client, api, email="ledger@example.com"):
    headers = await api.headers(email)
    me = (await client.get("/auth/me", headers=headers)).json()
    user_id = UUID(me["id"])
    async with SessionLocal() as session:
        workspace = (
            await session.execute(
                select(Workspace)
                .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                .where(WorkspaceMember.user_id == user_id, Workspace.is_personal.is_(True))
            )
        ).scalar_one()
    return headers, user_id, workspace.id


async def _create_key(client, headers, name="script", scopes=None) -> tuple[UUID, str]:
    response = await client.post(
        "/api-keys",
        json={"name": name, "scopes": scopes or ["chat:write"]},
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    return UUID(body["id"]), body["key"]


async def _seed_event(
    *,
    workspace_id,
    user_id,
    source,
    prompt=1,
    completion=1,
    cost=0.0,
    provider="fake",
    model="fake-model",
    api_key_id=None,
    created_at=None,
) -> None:
    async with SessionLocal() as session:
        session.add(
            UsageEvent(
                workspace_id=workspace_id,
                user_id=user_id,
                message_id=None,
                workflow_node_run_id=uuid4() if source == "workflow" else None,
                collaboration_step_id=uuid4() if source == "collaboration" else None,
                api_key_id=api_key_id,
                source=source,
                provider_id=provider,
                model=model,
                prompt_tokens=prompt,
                completion_tokens=completion,
                cost=cost,
                created_at=created_at or datetime.now(UTC),
            )
        )
        await session.commit()


async def _seed_catalog(input_price=1.0, output_price=2.0) -> None:
    async with SessionLocal() as session:
        session.add(
            ModelCatalog(
                provider_id="fake",
                model_id="fake-model",
                display_name="Fake",
                input_price=input_price,
                output_price=output_price,
            )
        )
        await session.commit()


async def _create_workflow(client, headers, nodes=None):
    definition = {
        "nodes": nodes
        or [
            {
                "id": "first",
                "type": "llm",
                "config": {
                    "provider_id": "fake",
                    "model": "fake-model",
                    "prompt": "Say hi",
                },
            },
            {
                "id": "second",
                "type": "llm",
                "config": {
                    "provider_id": "fake",
                    "model": "fake-model",
                    "prompt": "Repeat: {{first}}",
                },
            },
        ],
        "edges": [{"from": "first", "to": "second"}],
    }
    response = await client.post(
        "/workflows",
        json={"name": "Ledger workflow", "description": "ledger", "definition": definition},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_usage_groups_by_source_and_filters_by_api_key(client, api):
    headers, user_id, workspace_id = await _setup(client, api)
    key_id, _key = await _create_key(client, headers)
    await _seed_event(
        workspace_id=workspace_id,
        user_id=user_id,
        source="chat",
        prompt=10,
        completion=5,
        cost=0.01,
        api_key_id=key_id,
    )
    await _seed_event(
        workspace_id=workspace_id,
        user_id=user_id,
        source="workflow",
        prompt=20,
        completion=0,
        cost=0.02,
    )
    await _seed_event(
        workspace_id=workspace_id,
        user_id=user_id,
        source="collaboration",
        prompt=0,
        completion=7,
        cost=0.03,
    )

    summary = await client.get(f"/usage/summary?{_range()}&group_by=source", headers=headers)
    assert summary.status_code == 200
    buckets = {bucket["key"]: bucket for bucket in summary.json()["buckets"]}
    assert buckets["chat"]["requests"] == 1
    assert buckets["chat"]["total_tokens"] == 15
    assert buckets["workflow"]["total_tokens"] == 20
    assert buckets["collaboration"]["total_tokens"] == 7

    cost = await client.get(f"/usage/cost?{_range()}&group_by=source", headers=headers)
    cost_buckets = {bucket["key"]: bucket for bucket in cost.json()["buckets"]}
    assert cost.json()["total_cost"] == pytest.approx(0.06)
    assert cost_buckets["workflow"]["cost"] == pytest.approx(0.02)

    key_only = await client.get(f"/usage/summary?{_range()}&api_key_id={key_id}", headers=headers)
    assert [bucket["requests"] for bucket in key_only.json()["buckets"]] == [1]


async def test_usage_by_key_attributes_requests_and_is_workspace_scoped(client, api):
    alice_headers, alice_id, alice_workspace = await _setup(client, api, "ledger-alice@example.com")
    bob_headers, bob_id, bob_workspace = await _setup(client, api, "ledger-bob@example.com")
    alice_key, _alice_secret = await _create_key(client, alice_headers, "alice-key")
    bob_key, _bob_secret = await _create_key(client, bob_headers, "bob-key")
    await _seed_event(
        workspace_id=alice_workspace,
        user_id=alice_id,
        source="chat",
        cost=0.001,
        api_key_id=alice_key,
    )
    await _seed_event(
        workspace_id=alice_workspace,
        user_id=alice_id,
        source="workflow",
        cost=0.002,
    )
    await _seed_event(
        workspace_id=bob_workspace,
        user_id=bob_id,
        source="chat",
        cost=99.0,
        api_key_id=bob_key,
    )

    response = await client.get(f"/usage/by-key?{_range()}", headers=alice_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["total_requests"] == 2
    assert body["total_cost"] == pytest.approx(0.003)
    by_key = {bucket["api_key_id"]: bucket for bucket in body["buckets"]}
    assert set(by_key) == {str(alice_key), None}
    assert by_key[str(alice_key)]["name"] == "alice-key"
    assert by_key[str(alice_key)]["requests"] == 1
    assert by_key[None]["requests"] == 1
    assert all(bucket["cost"] < 1 for bucket in body["buckets"])


async def test_chat_usage_event_records_api_key(client, api, registry, fake_provider):
    headers, _user_id, _workspace_id = await _setup(client, api, "ledger-chat-key@example.com")
    key_id, key = await _create_key(client, headers)
    created = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )
    response = await client.post(
        f"/conversations/{created.json()['id']}/messages",
        json={"content": "Hi"},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 200

    async with SessionLocal() as session:
        event = (await session.execute(select(UsageEvent))).scalar_one()
    assert event.source == "chat"
    assert event.api_key_id == key_id


async def test_chat_finalize_is_idempotent(client, api, registry, fake_provider):
    from app.providers.base import Usage
    from app.routers.conversations import _finalize

    headers, _user_id, workspace_id = await _setup(client, api, "ledger-idempotent@example.com")
    created = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )
    await client.post(
        f"/conversations/{created.json()['id']}/messages",
        json={"content": "Hi"},
        headers=headers,
    )
    async with SessionLocal() as session:
        event = (await session.execute(select(UsageEvent))).scalar_one()
        message_id = event.message_id

    await _finalize(message_id, "again", "completed", Usage(9, 9), workspace_id)

    async with SessionLocal() as session:
        events = list((await session.execute(select(UsageEvent))).scalars())
    assert len(events) == 1
    assert events[0].prompt_tokens == 1


async def test_workflow_writes_one_ledger_event_per_llm_node(client, api, registry, fake_provider):
    await _seed_catalog()
    headers, _user_id, _workspace_id = await _setup(client, api, "ledger-wf@example.com")
    workflow_id = await _create_workflow(client, headers)

    response = await client.post(
        f"/workflows/{workflow_id}/runs", json={"input": "hello"}, headers=headers
    )
    assert response.status_code == 202

    async with SessionLocal() as session:
        run = (await session.execute(select(WorkflowRun))).scalar_one()
        events = list(
            (
                await session.execute(select(UsageEvent).where(UsageEvent.source == "workflow"))
            ).scalars()
        )
    assert len(events) == 2
    assert all(event.workflow_node_run_id is not None for event in events)
    assert all(event.message_id is None for event in events)
    assert sum(event.cost for event in events) == pytest.approx(run.cost)
    assert run.cost > 0

    summary = await client.get(f"/usage/summary?{_range()}&group_by=source", headers=headers)
    workflow_bucket = {bucket["key"]: bucket for bucket in summary.json()["buckets"]}["workflow"]
    assert workflow_bucket["requests"] == 2
    assert workflow_bucket["prompt_tokens"] == 2
    assert workflow_bucket["completion_tokens"] == 4

    cost = await client.get(f"/usage/cost?{_range()}&group_by=source", headers=headers)
    cost_bucket = {bucket["key"]: bucket for bucket in cost.json()["buckets"]}["workflow"]
    assert cost_bucket["cost"] == pytest.approx(run.cost)

    metrics = await client.get("/metrics")
    assert 'source="workflow"' in metrics.text


async def test_workflow_usage_event_records_api_key(client, api, registry, fake_provider):
    headers, _user_id, _workspace_id = await _setup(client, api, "ledger-wf-key@example.com")
    workflow_id = await _create_workflow(client, headers)
    key_id, key = await _create_key(client, headers, "workflow-key", ["workflow:run"])

    response = await client.post(
        f"/workflows/{workflow_id}/runs",
        json={"input": "hello"},
        headers={"X-API-Key": key},
    )
    assert response.status_code == 202

    async with SessionLocal() as session:
        events = list(
            (
                await session.execute(select(UsageEvent).where(UsageEvent.source == "workflow"))
            ).scalars()
        )
    assert len(events) == 2
    assert {event.api_key_id for event in events} == {key_id}


async def test_workflow_cost_enters_workspace_budget(client, api, registry, fake_provider):
    await _seed_catalog(input_price=600_000.0, output_price=0.0)
    headers, _user_id, _workspace_id = await _setup(client, api, "ledger-budget@example.com")
    workflow_id = await _create_workflow(client, headers)

    await client.post(f"/workflows/{workflow_id}/runs", json={"input": "hello"}, headers=headers)

    async with SessionLocal() as session:
        audits = list(
            (
                await session.execute(select(AuditLog).where(AuditLog.action == "budget.exceeded"))
            ).scalars()
        )
    assert len(audits) == 1


class _CollaborationProvider:
    id = "fake"

    def __init__(self) -> None:
        self.models = []

    async def list_models(self):
        return []

    async def stream_chat(self, messages, model, **_opts):
        from app.providers.base import ChatChunk, Usage

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


async def test_collaboration_writes_one_ledger_event_per_step(client, api):
    from app.deps import get_registry
    from app.main import app
    from app.providers.registry import ProviderRegistry

    await _seed_catalog()
    provider = _CollaborationProvider()
    app.dependency_overrides[get_registry] = lambda: ProviderRegistry({"fake": provider})
    try:
        headers, _user_id, _workspace_id = await _setup(client, api, "ledger-collab@example.com")
        response = await client.post(
            "/collaborations/runs",
            json={"input": "research this", "provider_id": "fake", "model": "fake-model"},
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_registry, None)
    assert response.status_code == 202

    async with SessionLocal() as session:
        run = (await session.execute(select(CollaborationRun))).scalar_one()
        events = list(
            (
                await session.execute(
                    select(UsageEvent).where(UsageEvent.source == "collaboration")
                )
            ).scalars()
        )
    assert len(events) == 4
    assert all(event.collaboration_step_id is not None for event in events)
    assert len({event.collaboration_step_id for event in events}) == 4
    assert all(event.message_id is None for event in events)
    assert sum(event.cost for event in events) == pytest.approx(run.cost)

    summary = await client.get(f"/usage/summary?{_range()}&group_by=source", headers=headers)
    collab_bucket = {bucket["key"]: bucket for bucket in summary.json()["buckets"]}["collaboration"]
    assert collab_bucket["requests"] == 4


async def test_usage_events_keep_null_message_for_runs(client, api):
    headers, user_id, workspace_id = await _setup(client, api, "ledger-null-message@example.com")
    _key_id, _key = await _create_key(client, headers)

    async with SessionLocal() as session:
        keys = list((await session.execute(select(ApiKey))).scalars())
    assert keys

    await _seed_event(
        workspace_id=workspace_id,
        user_id=user_id,
        source="workflow",
        api_key_id=keys[0].id,
    )
    summary = await client.get(f"/usage/summary?{_range()}&group_by=source", headers=headers)
    assert summary.json()["buckets"][0]["key"] == "workflow"


async def test_chat_conversation_still_links_usage_event(client, api, registry, fake_provider):
    headers, user_id, _workspace_id = await _setup(client, api, "ledger-chat-link@example.com")
    created = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )
    await client.post(
        f"/conversations/{created.json()['id']}/messages",
        json={"content": "Hi"},
        headers=headers,
    )
    async with SessionLocal() as session:
        event = (await session.execute(select(UsageEvent))).scalar_one()
        conversation = await session.get(Conversation, UUID(created.json()["id"]))
    assert event.message_id is not None
    assert event.conversation_id == conversation.id
    assert event.user_id == user_id
