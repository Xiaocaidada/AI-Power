from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditLog, ModelCatalog, User


async def _make_admin(email: str) -> None:
    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        user.role = "admin"
        await session.commit()


async def _add_catalog() -> str:
    async with SessionLocal() as session:
        entry = ModelCatalog(
            provider_id="fake",
            model_id="fake-model",
            display_name="Fake",
            input_price=1.0,
            output_price=2.0,
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        return str(entry.id)


async def _send_message(client, headers) -> None:
    conversation = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )
    response = await client.post(
        f"/conversations/{conversation.json()['id']}/messages",
        json={"content": "admin usage"},
        headers=headers,
    )
    assert response.status_code == 200


async def test_admin_endpoints_hide_from_non_admins(client, api):
    user = await api.headers("plain-user@example.com")

    for response in (
        await client.get("/admin/users", headers=user),
        await client.get("/admin/workspaces", headers=user),
        await client.get("/admin/usage", headers=user),
        await client.get("/admin/audit-logs", headers=user),
        await client.get("/admin/users"),
    ):
        assert response.status_code in {401, 404}
    assert (await client.get("/admin/users", headers=user)).status_code == 404


async def test_admin_lists_users_workspaces_and_members(client, api):
    admin = await api.headers("admin-list@example.com")
    await _make_admin("admin-list@example.com")
    await api.headers("member-one@example.com")
    await api.headers("member-two@example.com")

    users = await client.get("/admin/users?limit=2", headers=admin)
    workspaces = await client.get("/admin/workspaces", headers=admin)

    assert users.status_code == 200
    assert len(users.json()) == 2
    assert users.json()[0]["role"] in {"user", "admin"}
    assert workspaces.status_code == 200
    assert len(workspaces.json()) == 3
    assert all(item["member_count"] == 1 for item in workspaces.json())

    admin_workspaces = await client.get("/workspaces", headers=admin)
    admin_workspace_id = admin_workspaces.json()[0]["id"]
    members = await client.get(f"/admin/workspaces/{admin_workspace_id}/members", headers=admin)
    assert members.status_code == 200
    assert members.json()[0]["role"] == "owner"


async def test_admin_toggles_model_and_writes_audit_log(client, api, registry, fake_provider):
    admin = await api.headers("admin-model@example.com")
    await _make_admin("admin-model@example.com")
    model_id = await _add_catalog()

    before = await client.get("/models", headers=admin)
    assert "fake-model" in [item["model_id"] for item in before.json()]

    disabled = await client.patch(
        f"/admin/models/{model_id}", json={"enabled": False}, headers=admin
    )

    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    admin_models = await client.get("/admin/models", headers=admin)
    assert admin_models.json()[0]["enabled"] is False
    after = await client.get("/models", headers=admin)
    assert "fake-model" not in [item["model_id"] for item in after.json()]

    logs = await client.get("/admin/audit-logs", headers=admin)
    assert logs.status_code == 200
    entry = logs.json()[0]
    assert entry["action"] == "model.toggle"
    assert entry["target_type"] == "model_catalog"
    assert entry["target_id"] == model_id
    assert entry["detail"] == {"enabled": False}


async def test_admin_usage_aggregates_all_workspaces(client, api, registry, fake_provider):
    admin = await api.headers("admin-usage@example.com")
    await _make_admin("admin-usage@example.com")
    await _add_catalog()
    alice = await api.headers("admin-usage-alice@example.com")
    bob = await api.headers("admin-usage-bob@example.com")
    await _send_message(client, alice)
    await _send_message(client, bob)

    response = await client.get("/admin/usage?group_by=model", headers=admin)

    assert response.status_code == 200
    body = response.json()
    assert body["requests"] == 2
    assert body["total_tokens"] == 6
    assert body["total_cost"] == pytest.approx(1e-05)
    assert body["unpriced_requests"] == 0
    assert body["buckets"][0]["key"] == "fake-model"
    assert body["buckets"][0]["requests"] == 2


async def test_admin_can_paginate_audit_logs(client, api):
    admin = await api.headers("admin-audit@example.com")
    await _make_admin("admin-audit@example.com")
    model_id = await _add_catalog()
    for enabled in (False, True):
        await client.patch(f"/admin/models/{model_id}", json={"enabled": enabled}, headers=admin)

    page = await client.get("/admin/audit-logs?limit=1", headers=admin)

    assert len(page.json()) == 1
    cursor = page.json()[0]["id"]
    next_page = await client.get(f"/admin/audit-logs?limit=1&before={cursor}", headers=admin)
    assert len(next_page.json()) == 1
    assert next_page.json()[0]["id"] != cursor


async def test_cleanup_audit_logs_removes_expired():
    from app.services.maintenance import cleanup_audit_logs

    old = datetime.now(UTC) - timedelta(days=120)
    async with SessionLocal() as session:
        user = User(email="audit-cleanup@example.com", password_hash="x")
        session.add(user)
        await session.flush()
        session.add_all(
            [
                AuditLog(
                    actor_user_id=user.id,
                    action="old",
                    target_type="test",
                    created_at=old,
                ),
                AuditLog(
                    actor_user_id=user.id,
                    action="new",
                    target_type="test",
                ),
            ]
        )
        await session.commit()

        removed = await cleanup_audit_logs(session, max_age_days=90)
        remaining = list((await session.execute(select(AuditLog))).scalars())

    assert removed == 1
    assert [entry.action for entry in remaining] == ["new"]
