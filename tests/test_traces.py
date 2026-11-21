async def _conversation(client, headers):
    return await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model", "kb_id": None},
        headers=headers,
    )


async def _send(client, headers, conversation_id, request_id):
    return await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "hello"},
        headers={**headers, "X-Request-ID": request_id},
    )


async def test_chat_creates_trace_with_stages(client, api, registry):
    headers = await api.headers("trace-ok@example.com")
    conversation = await _conversation(client, headers)

    response = await _send(client, headers, conversation.json()["id"], "trace-ok-1")
    trace = await client.get("/traces/trace-ok-1", headers=headers)

    assert response.status_code == 200
    assert trace.status_code == 200
    body = trace.json()
    assert body["status"] == "completed"
    assert body["provider_id"] == "fake"
    assert body["model"] == "fake-model"
    assert body["message_id"] is not None
    assert body["ttft_ms"] is not None
    assert body["total_ms"] is not None
    assert body["ttft_ms"] >= 0
    assert body["retrieval_ms"] is None
    assert body["attempts"] == 1

    detail = await client.get(f"/conversations/{conversation.json()['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["messages"][-1]["request_id"] == "trace-ok-1"


async def test_trace_is_workspace_scoped(client, api, registry):
    alice = await api.headers("trace-alice@example.com")
    bob = await api.headers("trace-bob@example.com")
    conversation = await _conversation(client, alice)
    await _send(client, alice, conversation.json()["id"], "trace-scope-1")

    response = await client.get("/traces/trace-scope-1", headers=bob)

    assert response.status_code == 404


async def test_failed_stream_records_error_code(client, api, registry, fake_provider):
    from app.providers.base import ProviderError

    fake_provider.error = ProviderError("provider_timeout", "down")
    headers = await api.headers("trace-fail@example.com")
    conversation = await _conversation(client, headers)

    response = await _send(client, headers, conversation.json()["id"], "trace-fail-1")
    trace = await client.get("/traces/trace-fail-1", headers=headers)

    assert response.status_code == 200
    assert '"code": "provider_timeout"' in response.text
    body = trace.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "provider_timeout"


def _providers():
    from app.providers.base import ChatChunk, ModelInfo, ProviderError, Usage

    class FailingProvider:
        id = "bad"

        async def list_models(self):
            return [ModelInfo(id="bad-model", provider_id="bad")]

        async def stream_chat(self, messages, model, **_opts):
            raise ProviderError("provider_unreachable", "down")
            yield ChatChunk()  # pragma: no cover

    class WorkingProvider:
        id = "good"

        async def list_models(self):
            return [ModelInfo(id="good-model", provider_id="good")]

        async def stream_chat(self, messages, model, **_opts):
            yield ChatChunk(delta="OK")
            yield ChatChunk(usage=Usage(prompt_tokens=1, completion_tokens=1))
            yield ChatChunk(finish_reason="stop")

    return {"bad": FailingProvider(), "good": WorkingProvider()}


async def test_auto_trace_records_attempts(client, api):
    from app.db import SessionLocal
    from app.deps import get_registry
    from app.main import app
    from app.models import ModelCatalog
    from app.providers.registry import ProviderRegistry

    app.dependency_overrides[get_registry] = lambda: ProviderRegistry(_providers())
    try:
        async with SessionLocal() as session:
            session.add_all(
                [
                    ModelCatalog(
                        provider_id="bad",
                        model_id="bad-model",
                        display_name="bad",
                        priority=10,
                    ),
                    ModelCatalog(
                        provider_id="good",
                        model_id="good-model",
                        display_name="good",
                        priority=20,
                    ),
                ]
            )
            await session.commit()

        headers = await api.headers("trace-auto@example.com")
        conversation = await client.post(
            "/conversations",
            json={"provider_id": "auto", "model": "auto", "kb_id": None},
            headers=headers,
        )
        await _send(client, headers, conversation.json()["id"], "trace-auto-1")
        trace = await client.get("/traces/trace-auto-1", headers=headers)
    finally:
        app.dependency_overrides.pop(get_registry, None)

    assert trace.status_code == 200
    assert trace.json()["provider_id"] == "good"
    assert trace.json()["attempts"] == 2


async def test_cleanup_traces_removes_only_old_rows(client):
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Trace
    from app.services.maintenance import cleanup_traces

    now = datetime.now(UTC)
    async with SessionLocal() as session:
        session.add_all(
            [
                Trace(
                    request_id="old-trace",
                    workspace_id=uuid4(),
                    user_id=uuid4(),
                    status="completed",
                    attempts=1,
                    created_at=now - timedelta(days=8),
                ),
                Trace(
                    request_id="new-trace",
                    workspace_id=uuid4(),
                    user_id=uuid4(),
                    status="completed",
                    attempts=1,
                    created_at=now - timedelta(days=1),
                ),
            ]
        )
        await session.commit()

        removed = await cleanup_traces(session, now=now)
        remaining = list((await session.execute(select(Trace.request_id))).scalars())

    assert removed == 1
    assert remaining == ["new-trace"]
