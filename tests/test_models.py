import pytest


async def _seed_model(
    provider_id: str,
    model_id: str,
    *,
    priority: int = 10,
    enabled: bool = True,
) -> str:
    from app.db import SessionLocal
    from app.models import ModelCatalog

    async with SessionLocal() as session:
        row = ModelCatalog(
            provider_id=provider_id,
            model_id=model_id,
            display_name=f"{provider_id}/{model_id}",
            context_window=8192,
            input_price=1.0,
            output_price=2.0,
            tags="fast,zh",
            priority=priority,
            enabled=enabled,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return str(row.id)


def _override_registry(providers):
    from app.deps import get_registry
    from app.main import app
    from app.providers.registry import ProviderRegistry

    registry = ProviderRegistry(providers)
    app.dependency_overrides[get_registry] = lambda: registry
    return registry


@pytest.fixture
def clear_registry_override():
    from app.deps import get_registry
    from app.main import app

    yield
    app.dependency_overrides.pop(get_registry, None)


async def _create_conversation(client, headers):
    return await client.post(
        "/conversations",
        json={"provider_id": "auto", "model": "auto", "kb_id": None},
        headers=headers,
    )


async def test_models_lists_catalog_and_compare(client, api, registry):
    headers = await api.headers("models-list@example.com")
    first = await _seed_model("fake", "fake-model")
    await _seed_model("fake", "disabled-model", enabled=False)

    listed = await client.get("/models", headers=headers)
    compared = await client.get(f"/models/compare?ids={first}", headers=headers)

    assert listed.status_code == 200
    entries = listed.json()
    assert [entry["model_id"] for entry in entries] == ["fake-model"]
    assert entries[0]["available"] is True
    assert entries[0]["tags"] == ["fast", "zh"]
    assert compared.status_code == 200
    assert compared.json()[0]["id"] == first


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


async def test_auto_falls_back_to_next_provider(client, api, clear_registry_override):
    headers = await api.headers("models-auto@example.com")
    _override_registry(_providers())
    await _seed_model("bad", "bad-model", priority=10)
    await _seed_model("good", "good-model", priority=20)
    conversation = await _create_conversation(client, headers)
    assert conversation.status_code == 201

    response = await client.post(
        f"/conversations/{conversation.json()['id']}/messages",
        json={"content": "hello"},
        headers=headers,
    )

    assert response.status_code == 200
    assert '"provider": "good"' in response.text
    assert '"model": "good-model"' in response.text
    assert '"OK"' in response.text
    assert '"code": "provider_unreachable"' not in response.text


async def test_auto_returns_503_when_all_providers_fail(client, api, clear_registry_override):
    headers = await api.headers("models-down@example.com")
    _override_registry({"bad": _providers()["bad"]})
    await _seed_model("bad", "bad-model", priority=10)
    conversation = await _create_conversation(client, headers)

    response = await client.post(
        f"/conversations/{conversation.json()['id']}/messages",
        json={"content": "hello"},
        headers=headers,
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "no_provider_available"


async def test_circuit_breaker_marks_provider_unavailable(client, api, registry, fake_redis):
    from app.services.routing import record_failure

    headers = await api.headers("models-circuit@example.com")
    await _seed_model("fake", "fake-model")
    for _ in range(3):
        await record_failure(fake_redis, "fake")

    response = await client.get("/models", headers=headers)

    assert response.status_code == 200
    assert response.json()[0]["available"] is False


async def test_compare_rejects_unknown_ids(client, api, registry):
    headers = await api.headers("models-missing@example.com")

    response = await client.get("/models/compare?ids=missing", headers=headers)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "model_not_found"
