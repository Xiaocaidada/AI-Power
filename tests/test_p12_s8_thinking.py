from uuid import UUID

import pytest

from app.db import SessionLocal
from app.deps import get_scoped_registry
from app.main import app as app_instance
from app.models import ProviderConfig, ProviderModel
from app.providers.registry import ProviderRegistry
from app.services.chat_modes import (
    ChatModeError,
    thinking_provider_opts,
    validate_turn_mode,
)


def test_thinking_levels_map_to_provider_parameters():
    assert thinking_provider_opts("fast") == {"reasoning_effort": "low"}
    assert thinking_provider_opts("standard") == {}
    assert thinking_provider_opts("deep") == {"reasoning_effort": "high"}


def test_unsupported_thinking_level_is_rejected_not_downgraded():
    with pytest.raises(ChatModeError) as exc:
        validate_turn_mode(
            mode="chat",
            mode_meta={"thinking_level": "fast"},
            capabilities=["chat"],
            reasoning_levels=["standard", "deep"],
            agent=False,
        )
    assert exc.value.code == "thinking_level_unsupported"


async def _reasoner(client, headers, levels: list[str]) -> str:
    me = await client.get("/auth/me", headers=headers)
    workspaces = await client.get("/workspaces", headers=headers)
    async with SessionLocal() as session:
        config = ProviderConfig(
            workspace_id=UUID(workspaces.json()[0]["id"]),
            owner_user_id=UUID(me.json()["id"]),
            name="Reasoner",
            base_url="https://reasoner.example/v1",
            api_key_encrypted="test-only",
        )
        session.add(config)
        await session.flush()
        session.add(
            ProviderModel(
                config_id=config.id,
                model_id="reasoner-1",
                display_name="Reasoner 1",
                capabilities=["chat", "reasoning"],
                reasoning_levels=levels,
            )
        )
        await session.commit()
        return str(config.id)


async def test_deep_thinking_sends_reasoning_effort(
    client, api, fake_provider
):
    from app.providers.base import ChatChunk, Usage

    headers = await api.headers("p12-s8-deep@example.com")
    config_id = await _reasoner(client, headers, ["standard", "deep"])
    app_instance.dependency_overrides[get_scoped_registry] = lambda: ProviderRegistry(
        {config_id: fake_provider}
    )
    try:
        conversation = await client.post(
            "/conversations",
            json={"provider_id": config_id, "model": "reasoner-1"},
            headers=headers,
        )
        assert conversation.status_code == 201
        fake_provider.chunks = [
            ChatChunk(delta="Deep"),
            ChatChunk(usage=Usage(prompt_tokens=2, completion_tokens=3)),
            ChatChunk(finish_reason="stop"),
        ]

        response = await client.post(
            f"/conversations/{conversation.json()['id']}/messages",
            json={"content": "深度思考", "mode": "chat", "mode_meta": {"thinking_level": "deep"}},
            headers=headers,
        )
    finally:
        app_instance.dependency_overrides.pop(get_scoped_registry, None)

    assert response.status_code == 200
    assert fake_provider.opts_calls[-1]["reasoning_effort"] == "high"
    detail = await client.get(
        f"/conversations/{conversation.json()['id']}", headers=headers
    )
    assistant = [item for item in detail.json()["messages"] if item["role"] == "assistant"]
    assert assistant[-1]["mode_meta"]["thinking_level"] == "deep"


async def test_unsupported_fast_level_returns_422(client, api, fake_provider):
    headers = await api.headers("p12-s8-fast@example.com")
    config_id = await _reasoner(client, headers, ["standard", "deep"])
    app_instance.dependency_overrides[get_scoped_registry] = lambda: ProviderRegistry(
        {config_id: fake_provider}
    )
    try:
        conversation = await client.post(
            "/conversations",
            json={"provider_id": config_id, "model": "reasoner-1"},
            headers=headers,
        )
        response = await client.post(
            f"/conversations/{conversation.json()['id']}/messages",
            json={"content": "快速思考", "mode": "chat", "mode_meta": {"thinking_level": "fast"}},
            headers=headers,
        )
    finally:
        app_instance.dependency_overrides.pop(get_scoped_registry, None)

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "thinking_level_unsupported"