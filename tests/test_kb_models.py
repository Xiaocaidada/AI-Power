from uuid import UUID

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import KnowledgeBase
from app.providers.base import ProviderError
from app.services.knowledge_settings import resolve_kb_settings


async def _setup(client, api, email="kb-models@example.com"):
    headers = await api.headers(email)
    config = await client.post(
        "/provider-configs",
        json={
            "name": "Local embedding",
            "provider_type": "openai_compatible",
            "base_url": "http://embedding.local/v1",
            "api_key": "sk-embed-1234",
        },
        headers=headers,
    )
    config_id = config.json()["id"]
    embedding = await client.post(
        f"/provider-configs/{config_id}/models",
        json={"model_id": "bge-custom", "capabilities": ["embedding"]},
        headers=headers,
    )
    rerank = await client.post(
        f"/provider-configs/{config_id}/models",
        json={"model_id": "rerank-custom", "capabilities": ["rerank"]},
        headers=headers,
    )
    kb = await client.post("/knowledge-bases", json={"name": "KB models"}, headers=headers)
    kb_id = kb.json()["id"]
    patched = await client.patch(
        f"/knowledge-bases/{kb_id}/settings",
        json={
            "embedding": {"provider_config_id": config_id, "model": embedding.json()["model_id"]},
            "rerank": {"provider_config_id": config_id, "model": rerank.json()["model_id"]},
        },
        headers=headers,
    )
    assert patched.status_code == 200
    async with SessionLocal() as session:
        stored = (
            await session.execute(select(KnowledgeBase).where(KnowledgeBase.id == UUID(kb_id)))
        ).scalar_one()
    return headers, config_id, kb_id, stored


async def test_kb_settings_persist_model_selections(client, api):
    headers, config_id, _kb_id, kb = await _setup(client, api, "kb-settings-models@example.com")
    settings = resolve_kb_settings(kb)

    assert str(settings.embedding.provider_config_id) == config_id
    assert settings.embedding.model == "bge-custom"
    assert settings.rerank.model == "rerank-custom"


async def test_kb_uses_provider_embedding_and_rerank_models(client, api, monkeypatch):
    from app.services import kb_models

    _headers, _config_id, _kb_id, kb = await _setup(client, api, "kb-use-models@example.com")
    settings = resolve_kb_settings(kb)
    captured: dict[str, object] = {}

    class FakeEmbedding:
        def __init__(self, base_url, api_key, *, model, dimensions, timeout):
            captured["embedding"] = (base_url, api_key, model, dimensions)

        async def embed(self, texts):
            return [[0.0] * 1024 for _ in texts]

    class FakeReranker:
        def __init__(self, *, base_url, model, timeout, api_key):
            captured["rerank"] = (base_url, model, api_key)

    monkeypatch.setattr(kb_models, "OpenAICompatEmbeddingProvider", FakeEmbedding)
    monkeypatch.setattr(kb_models, "HttpReranker", FakeReranker)

    async with SessionLocal() as session:
        embedder = await kb_models.build_kb_embedder(session, kb, settings)
        reranker = await kb_models.build_kb_reranker(session, kb, settings)

    assert isinstance(embedder, FakeEmbedding)
    assert captured["embedding"][0] == "http://embedding.local/v1"
    assert captured["embedding"][2] == "bge-custom"
    assert captured["embedding"][3] == 1024
    assert captured["rerank"] == (
        "http://embedding.local/v1",
        "rerank-custom",
        "sk-embed-1234",
    )
    assert isinstance(reranker, FakeReranker)


async def test_kb_cannot_use_another_users_provider_config(client, api):
    from app.services import kb_models

    alice, _alice_config, _kb_id, alice_kb = await _setup(client, api, "kb-owner-alice@example.com")
    bob = await api.headers("kb-owner-bob@example.com")
    bob_config = await client.post(
        "/provider-configs",
        json={
            "name": "Bob embedding",
            "base_url": "http://bob.local/v1",
            "api_key": "sk-bob-1234",
        },
        headers=bob,
    )
    bob_id = bob_config.json()["id"]
    await client.post(
        f"/provider-configs/{bob_id}/models",
        json={"model_id": "bob-embed", "capabilities": ["embedding"]},
        headers=bob,
    )
    await client.patch(
        f"/knowledge-bases/{alice_kb.id}/settings",
        json={"embedding": {"provider_config_id": bob_id, "model": "bob-embed"}},
        headers=alice,
    )
    async with SessionLocal() as session:
        stored = await session.get(KnowledgeBase, alice_kb.id)
        assert stored is not None
        settings = resolve_kb_settings(stored)
        with pytest.raises(ProviderError) as excinfo:
            await kb_models.build_kb_embedder(session, stored, settings)

    assert excinfo.value.code == "embedding_config_unavailable"
