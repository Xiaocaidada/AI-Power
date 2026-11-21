from uuid import UUID, uuid4

from sqlalchemy import select

from app.db import SessionLocal
from app.metrics import MetricsRegistry
from app.models import AuditLog, UsageEvent
from app.services.budget import check_workspace_budget


def test_metrics_registry_renders_prometheus_text():
    registry = MetricsRegistry()
    registry.describe("demo_total", "Demo counter")
    registry.inc_counter("demo_total", 2, kind="a")
    registry.set_gauge("demo_gauge", 3, label="x")
    registry.observe("demo_latency_seconds", 0.02, route="/x")

    text = registry.render()

    assert "# TYPE demo_total counter" in text
    assert 'demo_total{kind="a"} 2' in text
    assert "# TYPE demo_gauge gauge" in text
    assert 'demo_gauge{label="x"} 3' in text
    assert "demo_latency_seconds_bucket" in text
    assert "demo_latency_seconds_count" in text


async def test_metrics_endpoint_exposes_http_queue_and_circuit_series(client, api, registry):
    await api.headers("metrics-endpoint@example.com")

    response = await client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "ai_power_http_requests_total" in body
    assert "ai_power_http_request_duration_seconds_bucket" in body
    assert 'ai_power_ingestion_jobs{status="queued"}' in body
    assert 'ai_power_circuit_open{provider="fake"} 0' in body


async def test_metrics_circuit_gauge_reflects_open_state(client, api, registry, fake_redis):
    fake_redis.counts["circuit:provider:fake"] = 3

    response = await client.get("/metrics")

    assert 'ai_power_circuit_open{provider="fake"} 1' in response.text


async def test_budget_alert_is_written_once_per_day(client, api, fake_redis):
    headers = await api.headers("budget-alert@example.com")
    workspace = (await client.get("/workspaces", headers=headers)).json()[0]
    me = (await client.get("/auth/me", headers=headers)).json()
    workspace_id = UUID(workspace["id"])

    async with SessionLocal() as session:
        session.add(
            UsageEvent(
                workspace_id=workspace_id,
                user_id=UUID(me["id"]),
                message_id=uuid4(),
                provider_id="fake",
                model="fake-model",
                prompt_tokens=1,
                completion_tokens=1,
                cost=2.0,
            )
        )
        await session.commit()
        first = await check_workspace_budget(session, fake_redis, workspace_id)
        await session.commit()
        second = await check_workspace_budget(session, fake_redis, workspace_id)

    assert first is True
    assert second is False
    async with SessionLocal() as session:
        logs = list(
            (
                await session.execute(select(AuditLog).where(AuditLog.action == "budget.exceeded"))
            ).scalars()
        )
    assert len(logs) == 1
    assert logs[0].detail is not None
    assert logs[0].detail["cost_usd"] == 2.0
