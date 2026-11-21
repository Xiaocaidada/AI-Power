from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditLog, CollaborationRun, ModelCatalog, User, WorkflowRun


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


async def test_admin_changes_workspace_plan_and_audits(client, api):
    admin = await api.headers("admin-plan@example.com")
    await _make_admin("admin-plan@example.com")
    workspace = (await client.get("/workspaces", headers=admin)).json()[0]

    changed = await client.patch(
        f"/admin/workspaces/{workspace['id']}/plan",
        json={"plan": "pro"},
        headers=admin,
    )

    assert changed.status_code == 200
    assert changed.json()["plan"] == "pro"
    quota = await client.get("/usage/quota", headers=admin)
    assert quota.json()["plan"] == "pro"
    assert quota.json()["requests"]["limit"] == 600

    logs = await client.get("/admin/audit-logs", headers=admin)
    entry = next(item for item in logs.json() if item["action"] == "workspace.plan_change")
    assert entry["target_id"] == workspace["id"]
    assert entry["detail"] == {"from": "free", "to": "pro"}

    invalid = await client.patch(
        f"/admin/workspaces/{workspace['id']}/plan",
        json={"plan": "enterprise"},
        headers=admin,
    )
    assert invalid.status_code == 422


async def test_admin_run_failure_summary(client, api, registry):
    admin = await api.headers("admin-runs@example.com")
    await _make_admin("admin-runs@example.com")
    me = (await client.get("/auth/me", headers=admin)).json()
    workspace = (await client.get("/workspaces", headers=admin)).json()[0]
    definition = {
        "nodes": [
            {
                "id": "only",
                "type": "llm",
                "config": {"provider_id": "fake", "model": "fake-model", "prompt": "hi"},
            }
        ],
        "edges": [],
    }
    workflow = await client.post(
        "/workflows",
        json={"name": "Failed WF", "definition": definition},
        headers=admin,
    )
    workflow_body = workflow.json()
    async with SessionLocal() as session:
        session.add(
            WorkflowRun(
                workflow_id=UUID(workflow_body["id"]),
                version_id=UUID(workflow_body["versions"][0]["id"]),
                workspace_id=UUID(workspace["id"]),
                user_id=UUID(me["id"]),
                status="failed",
                input_text="x",
            )
        )
        session.add(
            CollaborationRun(
                workspace_id=UUID(workspace["id"]),
                user_id=UUID(me["id"]),
                provider_id="fake",
                model="fake-model",
                status="failed",
                input_text="x",
            )
        )
        await session.commit()

    summary = await client.get("/admin/runs/summary", headers=admin)

    assert summary.status_code == 200
    body = summary.json()
    assert body["workflows"] == {"total": 1, "failed": 1, "failure_rate": 1.0}
    assert body["collaborations"] == {"total": 1, "failed": 1, "failure_rate": 1.0}


async def test_workflow_publish_writes_audit_log(client, api):
    admin = await api.headers("admin-publish@example.com")
    await _make_admin("admin-publish@example.com")
    definition = {
        "nodes": [
            {
                "id": "only",
                "type": "llm",
                "config": {"provider_id": "fake", "model": "fake-model", "prompt": "hi"},
            }
        ],
        "edges": [],
    }
    created = await client.post(
        "/workflows", json={"name": "Published", "definition": definition}, headers=admin
    )
    workflow_id = created.json()["id"]
    second = await client.post(
        f"/workflows/{workflow_id}/versions",
        json={"definition": definition},
        headers=admin,
    )

    assert second.status_code == 201
    assert second.json()["version"] == 2
    logs = await client.get("/admin/audit-logs", headers=admin)
    entries = [item for item in logs.json() if item["action"] == "workflow.publish"]
    assert [item["detail"]["version"] for item in entries] == [2, 1]
    assert all(item["target_id"] == workflow_id for item in entries)


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
