from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Conversation, Message, UsageEvent, Workspace, WorkspaceMember

DAY_ONE = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
DAY_TWO = datetime(2026, 11, 21, 12, 0, tzinfo=UTC)
RANGE = "from=2026-11-20T00:00:00Z&to=2026-11-22T00:00:00Z"


async def _setup(client, api, email="usage@example.com"):
    headers = await api.headers(email)
    me = await client.get("/auth/me", headers=headers)
    user_id = UUID(me.json()["id"])
    async with SessionLocal() as session:
        workspace = (
            await session.execute(
                select(Workspace)
                .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
                .where(WorkspaceMember.user_id == user_id, Workspace.is_personal.is_(True))
            )
        ).scalar_one()
        conversation = Conversation(
            workspace_id=workspace.id,
            user_id=user_id,
            title="Usage",
            provider_id="fake",
            model="fake-model",
        )
        session.add(conversation)
        await session.commit()
        await session.refresh(conversation)
    return headers, user_id, conversation.id


async def _seed_event(
    *,
    user_id,
    conversation_id,
    provider="fake",
    model="fake-model",
    prompt=1,
    completion=2,
    created_at=DAY_ONE,
):
    async with SessionLocal() as session:
        conversation = await session.get(Conversation, conversation_id)
        assert conversation is not None
        message = Message(
            conversation_id=conversation_id,
            user_id=user_id,
            role="assistant",
            content="",
            status="completed",
            provider_id=provider,
            model=model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            created_at=created_at,
        )
        session.add(message)
        await session.flush()
        session.add(
            UsageEvent(
                workspace_id=conversation.workspace_id,
                user_id=user_id,
                conversation_id=conversation_id,
                message_id=message.id,
                provider_id=provider,
                model=model,
                prompt_tokens=prompt,
                completion_tokens=completion,
                created_at=created_at,
            )
        )
        await session.commit()


async def test_usage_summary_requires_auth(client):
    response = await client.get("/usage/summary")

    assert response.status_code == 401


async def test_usage_summary_groups_by_day(client, api):
    headers, user_id, conversation_id = await _setup(client, api)
    await _seed_event(
        user_id=user_id,
        conversation_id=conversation_id,
        prompt=10,
        completion=5,
        created_at=DAY_ONE,
    )
    await _seed_event(
        user_id=user_id,
        conversation_id=conversation_id,
        prompt=20,
        completion=0,
        created_at=DAY_ONE,
    )
    await _seed_event(
        user_id=user_id, conversation_id=conversation_id, prompt=0, completion=7, created_at=DAY_TWO
    )

    response = await client.get(f"/usage/summary?{RANGE}&group_by=day", headers=headers)

    assert response.status_code == 200
    buckets = response.json()["buckets"]
    assert [bucket["key"] for bucket in buckets] == ["2026-11-20", "2026-11-21"]
    assert buckets[0] == {
        "key": "2026-11-20",
        "requests": 2,
        "prompt_tokens": 30,
        "completion_tokens": 5,
        "total_tokens": 35,
    }
    assert buckets[1]["requests"] == 1
    assert buckets[1]["total_tokens"] == 7


async def test_usage_summary_groups_by_provider_and_model(client, api):
    headers, user_id, conversation_id = await _setup(client, api, "usage-group@example.com")
    await _seed_event(
        user_id=user_id, conversation_id=conversation_id, provider="fake", model="m1", prompt=1
    )
    await _seed_event(
        user_id=user_id,
        conversation_id=conversation_id,
        provider="deepseek",
        model="chat",
        prompt=2,
    )
    await _seed_event(
        user_id=user_id, conversation_id=conversation_id, provider="fake", model="m1", prompt=3
    )

    by_provider = await client.get(f"/usage/summary?{RANGE}&group_by=provider", headers=headers)
    by_model = await client.get(f"/usage/summary?{RANGE}&group_by=model", headers=headers)

    provider_buckets = {bucket["key"]: bucket for bucket in by_provider.json()["buckets"]}
    model_buckets = {bucket["key"]: bucket for bucket in by_model.json()["buckets"]}
    assert provider_buckets["fake"]["requests"] == 2
    assert provider_buckets["fake"]["prompt_tokens"] == 4
    assert provider_buckets["deepseek"]["requests"] == 1
    assert model_buckets["m1"]["requests"] == 2
    assert model_buckets["chat"]["requests"] == 1


async def test_usage_summary_is_isolated_by_user(client, api):
    alice_headers, alice_id, alice_conversation = await _setup(
        client, api, "usage-alice@example.com"
    )
    bob_headers, bob_id, bob_conversation = await _setup(client, api, "usage-bob@example.com")
    await _seed_event(user_id=alice_id, conversation_id=alice_conversation, prompt=10)
    await _seed_event(user_id=bob_id, conversation_id=bob_conversation, prompt=99)

    alice = await client.get(f"/usage/summary?{RANGE}", headers=alice_headers)
    bob = await client.get(f"/usage/summary?{RANGE}", headers=bob_headers)

    assert sum(bucket["prompt_tokens"] for bucket in alice.json()["buckets"]) == 10
    assert sum(bucket["prompt_tokens"] for bucket in bob.json()["buckets"]) == 99


async def test_usage_summary_rejects_invalid_query(client, api):
    headers, _user_id, _conversation_id = await _setup(client, api, "usage-invalid@example.com")

    invalid_group = await client.get(f"/usage/summary?{RANGE}&group_by=week", headers=headers)
    invalid_range = await client.get(
        "/usage/summary?from=2026-11-22T00:00:00Z&to=2026-11-20T00:00:00Z",
        headers=headers,
    )

    assert invalid_group.status_code == 422
    assert invalid_range.status_code == 400


async def test_chat_writes_usage_event(client, api, registry, fake_provider):
    headers, user_id, _conversation_id = await _setup(client, api, "usage-chat@example.com")
    created = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )
    conversation_id = created.json()["id"]

    await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "Hi"},
        headers=headers,
    )

    async with SessionLocal() as session:
        events = (await session.execute(select(UsageEvent))).scalars().all()
    assert len(events) == 1
    event = events[0]
    assert event.user_id == user_id
    assert str(event.conversation_id) == conversation_id
    assert event.provider_id == "fake"
    assert event.model == "fake-model"
    assert event.prompt_tokens == 1
    assert event.completion_tokens == 2


async def test_chat_records_null_usage_event(client, api, registry, fake_provider):
    from app.providers.base import ChatChunk

    fake_provider.chunks = [ChatChunk(delta="Hi"), ChatChunk(finish_reason="stop")]
    headers, _user_id, _conversation_id = await _setup(client, api, "usage-null@example.com")
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
    assert event.prompt_tokens is None
    assert event.completion_tokens is None

    summary = await client.get(f"/usage/summary?{RANGE}", headers=headers)
    assert summary.json()["buckets"][0]["requests"] == 1
