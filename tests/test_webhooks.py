import hashlib
import hmac
from uuid import UUID

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Webhook, WebhookDelivery, WorkspaceMember


async def _owner(client, api, email="webhook-owner@example.com"):
    headers = await api.headers(email)
    me = await client.get("/auth/me", headers=headers)
    return headers, me.json()["id"]


async def _noop_validate(*_args, **_kwargs) -> None:
    return None


def _fake_client_factory(captured: dict, status_code: int = 200):
    response_status = status_code

    class FakeResponse:
        status_code = response_status

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, content, headers):
            captured["url"] = url
            captured["body"] = content
            captured["headers"] = headers
            return FakeResponse()

    return lambda **_kwargs: FakeClient()


async def test_create_webhook_returns_secret_once_and_encrypts_at_rest(client, api, monkeypatch):
    from app.routers import webhooks as router_module

    monkeypatch.setattr(router_module, "validate_webhook_url", _noop_validate)
    headers, _user_id = await _owner(client, api)

    created = await client.post(
        "/webhooks",
        json={"url": "https://example.com/hook", "events": ["message.completed"]},
        headers=headers,
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["secret"].startswith("whsec_")
    assert body["events"] == ["message.completed"]

    listed = await client.get("/webhooks", headers=headers)
    assert listed.status_code == 200
    assert "secret" not in listed.json()[0]

    async with SessionLocal() as session:
        hook = (await session.execute(select(Webhook))).scalar_one()
        assert hook.secret_encrypted != body["secret"]
        from app.services.webhooks import decrypt_secret

        assert decrypt_secret(hook.secret_encrypted) == body["secret"]


async def test_webhook_event_creates_delivery_with_valid_signature(client, api, monkeypatch):
    from app.routers import webhooks as router_module
    from app.services import webhooks as service

    monkeypatch.setattr(router_module, "validate_webhook_url", _noop_validate)
    monkeypatch.setattr(service, "validate_webhook_url", _noop_validate)
    captured: dict = {}
    monkeypatch.setattr(service.httpx, "AsyncClient", _fake_client_factory(captured))
    headers, _user_id = await _owner(client, api, "webhook-deliver@example.com")
    created = await client.post(
        "/webhooks",
        json={"url": "https://example.com/hook", "events": ["message.completed"]},
        headers=headers,
    )
    secret = created.json()["secret"]

    async with SessionLocal() as session:
        hook = (await session.execute(select(Webhook))).scalar_one()
        workspace_id = hook.workspace_id
        await service.enqueue_event(workspace_id, "message.completed", {"message_id": "m1"})
        await session.commit()

    delivered = await service.deliver_due_deliveries()
    assert delivered == 1
    assert captured["url"] == "https://example.com/hook"
    assert captured["headers"]["X-AI-Power-Event"] == "message.completed"
    signature = captured["headers"]["X-AI-Power-Signature"]
    timestamp, digest = signature.split(",")
    timestamp_value = int(timestamp.removeprefix("t="))
    expected = hmac.new(
        secret.encode(),
        f"{timestamp_value}.{captured['body'].decode()}".encode(),
        hashlib.sha256,
    ).hexdigest()
    assert digest == f"v1={expected}"

    async with SessionLocal() as session:
        delivery = (await session.execute(select(WebhookDelivery))).scalar_one()
        assert delivery.status == "delivered"
        assert delivery.attempts == 1


async def test_failed_delivery_is_retried_and_can_be_replayed(client, api, monkeypatch):
    from app.routers import webhooks as router_module
    from app.services import webhooks as service

    monkeypatch.setattr(router_module, "validate_webhook_url", _noop_validate)
    monkeypatch.setattr(service, "validate_webhook_url", _noop_validate)
    captured: dict = {}
    monkeypatch.setattr(
        service.httpx, "AsyncClient", _fake_client_factory(captured, status_code=503)
    )
    headers, _user_id = await _owner(client, api, "webhook-retry@example.com")
    created = await client.post(
        "/webhooks",
        json={"url": "https://example.com/hook", "events": ["document.ready"]},
        headers=headers,
    )
    hook_id = created.json()["id"]

    async with SessionLocal() as session:
        hook = (await session.execute(select(Webhook))).scalar_one()
        await service.enqueue_event(hook.workspace_id, "document.ready", {"document_id": "d1"})
        await session.commit()

    await service.deliver_due_deliveries()
    async with SessionLocal() as session:
        delivery = (await session.execute(select(WebhookDelivery))).scalar_one()
        delivery_id = delivery.id
        assert delivery.status == "failed"
        assert delivery.attempts == 1

    replayed = await client.post(
        f"/webhooks/{hook_id}/deliveries/{delivery_id}/replay", headers=headers
    )
    assert replayed.status_code == 200
    assert replayed.json()["status"] == "pending"
    assert replayed.json()["attempts"] == 0


async def test_webhook_management_requires_owner(client, api, monkeypatch):
    from app.routers import webhooks as router_module

    monkeypatch.setattr(router_module, "validate_webhook_url", _noop_validate)
    owner_headers, _owner_id = await _owner(client, api, "webhook-owner2@example.com")
    member_headers, member_id = await _owner(client, api, "webhook-member2@example.com")
    workspaces = await client.get("/workspaces", headers=owner_headers)
    workspace_id = next(item["id"] for item in workspaces.json() if item["is_personal"])
    async with SessionLocal() as session:
        session.add(
            WorkspaceMember(
                workspace_id=UUID(workspace_id),
                user_id=UUID(member_id),
                role="member",
            )
        )
        await session.commit()

    response = await client.get(
        "/webhooks",
        headers={**member_headers, "X-Workspace-Id": workspace_id},
    )
    assert response.status_code == 403


async def test_webhook_rejects_unknown_events(client, api, monkeypatch):
    from app.routers import webhooks as router_module

    monkeypatch.setattr(router_module, "validate_webhook_url", _noop_validate)
    headers, _user_id = await _owner(client, api, "webhook-invalid@example.com")

    response = await client.post(
        "/webhooks",
        json={"url": "https://example.com/hook", "events": ["not.real"]},
        headers=headers,
    )

    assert response.status_code == 422


async def test_message_finalize_enqueues_webhook_delivery(
    client, api, registry, fake_provider, monkeypatch
):
    from app.routers import webhooks as router_module

    monkeypatch.setattr(router_module, "validate_webhook_url", _noop_validate)
    headers, _user_id = await _owner(client, api, "webhook-message@example.com")
    created = await client.post(
        "/webhooks",
        json={"url": "https://example.com/hook", "events": ["message.completed"]},
        headers=headers,
    )
    assert created.status_code == 201
    conversation = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )

    await client.post(
        f"/conversations/{conversation.json()['id']}/messages",
        json={"content": "hello"},
        headers=headers,
    )

    async with SessionLocal() as session:
        delivery = (await session.execute(select(WebhookDelivery))).scalar_one()
        assert delivery.event == "message.completed"
        assert delivery.status == "pending"
        assert delivery.payload["conversation_id"] == conversation.json()["id"]


async def test_ssrf_guard_rejects_private_addresses():
    from app.config import Settings
    from app.services.webhooks import (
        _is_blocked_address,
        validate_url_shape,
        validate_webhook_url,
    )

    assert _is_blocked_address("127.0.0.1", False)
    assert not _is_blocked_address("93.184.216.34", False)

    with pytest.raises(ValueError):
        validate_url_shape("ftp://example.com/hook")
    with pytest.raises(ValueError):
        validate_url_shape("http://user:pass@example.com/hook")

    with pytest.raises(ValueError):
        await validate_webhook_url("http://127.0.0.1/hook", Settings(app_env="dev"))
    await validate_webhook_url(
        "http://127.0.0.1/hook",
        Settings(app_env="dev", webhook_allow_private_hosts=True),
    )


def test_signature_is_stable_and_body_bound():
    from app.services.webhooks import build_signature

    first = build_signature("secret", 100, '{"a":1}')
    second = build_signature("secret", 100, '{"a":2}')

    assert first.startswith("t=100,v1=")
    assert first != second
    assert first == build_signature("secret", 100, '{"a":1}')
