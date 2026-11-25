from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.deps import get_scoped_registry
from app.main import app as app_instance
from app.models import ProviderConfig
from app.providers.base import ChatChunk, ModelInfo, ProviderError, Usage
from app.providers.registry import ProviderRegistry
from app.services.provider_secrets import decrypt_api_key


async def _create_config(client, headers, **overrides):
    payload = {
        "name": "My provider",
        "provider_type": "openai_compatible",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-secret-1234",
        "note": "personal",
        **overrides,
    }
    return await client.post("/provider-configs", json=payload, headers=headers)


class _FakeProvider:
    id = "fake"

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def list_models(self):
        if self.fail:
            raise ProviderError("provider_http_error", "boom")
        return [ModelInfo(id="m1", provider_id=self.id), ModelInfo(id="m2", provider_id=self.id)]

    async def stream_chat(self, messages, model, **_opts):
        self.calls += 1
        yield ChatChunk(delta="hi")
        yield ChatChunk(usage=Usage(prompt_tokens=1, completion_tokens=2))
        yield ChatChunk(finish_reason="stop")


async def test_provider_config_crud_encrypts_key(client, api):
    headers = await api.headers("provider-crud@example.com")

    created = await _create_config(client, headers)

    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "My provider"
    assert "sk-secret-1234" not in created.text
    assert body["api_key_hint"].endswith("1234")
    assert body["status"] == "unknown"
    assert body["owned"] is True
    assert body["model_count"] == 0

    async with SessionLocal() as session:
        stored = (await session.execute(select(ProviderConfig))).scalar_one()
    assert stored.api_key_encrypted != "sk-secret-1234"
    assert decrypt_api_key(stored.api_key_encrypted) == "sk-secret-1234"

    listed = await client.get("/provider-configs", headers=headers)
    assert [item["id"] for item in listed.json()] == [body["id"]]

    patched = await client.patch(
        f"/provider-configs/{body['id']}",
        json={"name": "Renamed", "api_key": "sk-new-5678"},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed"
    assert patched.json()["api_key_hint"].endswith("5678")

    deleted = await client.delete(f"/provider-configs/{body['id']}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get("/provider-configs", headers=headers)).json() == []


async def test_provider_configs_are_isolated_and_shared_read_only(client, api):
    alice = await api.headers("provider-alice@example.com")
    bob = await api.headers("provider-bob@example.com")
    team = await client.post("/workspaces", json={"name": "Provider team"}, headers=alice)
    team_id = team.json()["id"]
    invited = await client.post(
        f"/workspaces/{team_id}/members",
        json={"email": "provider-bob@example.com"},
        headers=alice,
    )
    assert invited.status_code == 201
    alice_team = {**alice, "X-Workspace-Id": team_id}
    bob_team = {**bob, "X-Workspace-Id": team_id}

    shared = await _create_config(client, alice_team, name="Team", shared=True)
    private = await _create_config(client, alice_team, name="Private", shared=False)
    shared_id = shared.json()["id"]
    private_id = private.json()["id"]

    bob_list = (await client.get("/provider-configs", headers=bob_team)).json()
    assert [item["id"] for item in bob_list] == [shared_id]
    assert bob_list[0]["owned"] is False
    assert (
        await client.get(f"/provider-configs/{private_id}", headers=bob_team)
    ).status_code == 404
    assert (await client.get(f"/provider-configs/{shared_id}", headers=bob_team)).status_code == 200
    assert (
        await client.patch(
            f"/provider-configs/{shared_id}", json={"name": "Hijack"}, headers=bob_team
        )
    ).status_code == 404
    assert (
        await client.post(f"/provider-configs/{shared_id}/sync", headers=bob_team)
    ).status_code == 404


async def test_provider_test_and_sync_models(client, api, monkeypatch):
    from app.services import provider_configs

    monkeypatch.setattr(provider_configs, "build_provider", lambda _config: _FakeProvider())
    headers = await api.headers("provider-sync@example.com")
    config_id = (await _create_config(client, headers)).json()["id"]

    tested = await client.post(f"/provider-configs/{config_id}/test", headers=headers)
    assert tested.status_code == 200
    assert tested.json() == {"status": "ok", "model_count": 2, "error_code": None}

    synced = await client.post(f"/provider-configs/{config_id}/sync", headers=headers)
    assert synced.status_code == 200
    assert synced.json() == {"added": 2, "updated": 0, "total": 2}
    models = await client.get(f"/provider-configs/{config_id}/models", headers=headers)
    assert [model["model_id"] for model in models.json()] == ["m1", "m2"]
    assert all(model["source"] == "synced" for model in models.json())

    personal = await client.get("/provider-configs/models", headers=headers)
    assert [model["model_id"] for model in personal.json()] == ["m1", "m2"]
    assert personal.json()[0]["provider_id"] == config_id


class _GlmProvider(_FakeProvider):
    async def list_models(self):
        return [ModelInfo(id="glm-4.5-air", provider_id=self.id)]


async def test_sync_infers_glm_tool_capability_and_enables_agent(client, api, monkeypatch):
    from app.services import provider_configs

    provider = _GlmProvider()
    monkeypatch.setattr(provider_configs, "build_provider", lambda _config: provider)
    headers = await api.headers("provider-glm-tools@example.com")
    config_id = (await _create_config(client, headers)).json()["id"]

    synced = await client.post(f"/provider-configs/{config_id}/sync", headers=headers)
    models = await client.get(f"/provider-configs/{config_id}/models", headers=headers)
    personal = await client.get("/provider-configs/models", headers=headers)

    assert synced.status_code == 200
    assert "tools" in models.json()[0]["capabilities"]
    assert "tools" in personal.json()[0]["capabilities"]

    app_instance.dependency_overrides[get_scoped_registry] = lambda: ProviderRegistry(
        {config_id: provider}
    )
    try:
        created = await client.post(
            "/conversations",
            json={"provider_id": config_id, "model": "glm-4.5-air"},
            headers=headers,
        )
        switched = await client.patch(
            f"/conversations/{created.json()['id']}",
            json={"default_mode": "agent"},
            headers=headers,
        )
    finally:
        app_instance.dependency_overrides.pop(get_scoped_registry, None)

    assert created.status_code == 201
    assert switched.status_code == 200
    assert switched.json()["default_mode"] == "agent"
    assert switched.json()["agent"] is True


async def test_provider_test_failure_marks_status(client, api, monkeypatch):
    from app.services import provider_configs

    def build(_config):
        return _FakeProvider(fail=True)

    monkeypatch.setattr(provider_configs, "build_provider", build)
    headers = await api.headers("provider-fail@example.com")
    config_id = (await _create_config(client, headers)).json()["id"]

    tested = await client.post(f"/provider-configs/{config_id}/test", headers=headers)

    assert tested.json() == {
        "status": "error",
        "model_count": 0,
        "error_code": "provider_http_error",
    }
    detail = await client.get(f"/provider-configs/{config_id}", headers=headers)
    assert detail.json()["status"] == "error"
    assert detail.json()["last_error"] == "provider_http_error"


async def test_manual_model_capabilities_and_toggle(client, api):
    headers = await api.headers("provider-models@example.com")
    config_id = (await _create_config(client, headers)).json()["id"]

    created = await client.post(
        f"/provider-configs/{config_id}/models",
        json={
            "model_id": "custom-chat",
            "display_name": "Custom",
            "capabilities": ["chat", "tools"],
            "reasoning_levels": ["fast", "deep"],
            "context_window": 128000,
            "max_output": 4096,
        },
        headers=headers,
    )
    assert created.status_code == 201
    model_id = created.json()["id"]
    assert created.json()["capabilities"] == ["chat", "tools"]
    assert created.json()["context_window"] == 128000
    assert created.json()["max_output"] == 4096
    assert created.json()["reasoning_levels"] == ["fast", "deep"]

    edited = await client.patch(
        f"/provider-configs/{config_id}/models/{model_id}",
        json={
            "enabled": False,
            "capabilities": ["chat", "vision"],
            "reasoning_levels": ["standard"],
            "context_window": 8192,
            "max_output": 1024,
        },
        headers=headers,
    )
    assert edited.status_code == 200
    assert edited.json()["enabled"] is False
    assert edited.json()["context_window"] == 8192
    assert edited.json()["max_output"] == 1024
    assert edited.json()["reasoning_levels"] == ["standard"]
    assert (await client.get("/provider-configs/models", headers=headers)).json() == []

    deleted = await client.delete(
        f"/provider-configs/{config_id}/models/{model_id}", headers=headers
    )
    assert deleted.status_code == 204


async def test_invalid_provider_endpoint_is_rejected(client, api):
    headers = await api.headers("provider-invalid@example.com")
    response = await _create_config(client, headers, base_url="ftp://example.com")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_endpoint"


async def test_chat_uses_user_provider_config(client, api, monkeypatch):
    from app.services import provider_configs

    provider = _FakeProvider()
    monkeypatch.setattr(provider_configs, "build_provider", lambda _config: provider)
    headers = await api.headers("provider-chat@example.com")
    config_id = (await _create_config(client, headers)).json()["id"]
    await client.post(
        f"/provider-configs/{config_id}/models",
        json={"model_id": "custom-chat", "capabilities": ["chat"]},
        headers=headers,
    )

    created = await client.post(
        "/conversations",
        json={"provider_id": config_id, "model": "custom-chat"},
        headers=headers,
    )
    assert created.status_code == 201
    sent = await client.post(
        f"/conversations/{created.json()['id']}/messages",
        json={"content": "Hi"},
        headers=headers,
    )

    assert sent.status_code == 200
    assert "hi" in sent.text
    assert provider.calls == 1


async def test_provider_config_not_found_is_404(client, api):
    headers = await api.headers("provider-missing@example.com")
    response = await client.get(f"/provider-configs/{UUID(int=0)}", headers=headers)
    assert response.status_code == 404


async def test_chat_rejects_unsupported_provider_model_capability(client, api, monkeypatch):
    from app.services import provider_configs

    monkeypatch.setattr(provider_configs, "build_provider", lambda _config: _FakeProvider())
    headers = await api.headers("provider-capability@example.com")
    config_id = (await _create_config(client, headers)).json()["id"]
    await client.post(
        f"/provider-configs/{config_id}/models",
        json={"model_id": "no-chat", "capabilities": ["stream"]},
        headers=headers,
    )

    response = await client.post(
        "/conversations",
        json={"provider_id": config_id, "model": "no-chat"},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "capability_unsupported"
