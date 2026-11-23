import asyncio
import json

import pytest
from sqlalchemy import select

from app.services.outbound import OutboundError, validate_outbound_url


async def _seed_model_catalog() -> None:
    from app.db import SessionLocal
    from app.models import ModelCatalog

    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(ModelCatalog.id).where(
                    ModelCatalog.provider_id == "fake",
                    ModelCatalog.model_id == "fake-model",
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                ModelCatalog(
                    provider_id="fake",
                    model_id="fake-model",
                    display_name="Fake Model",
                    enabled=True,
                )
            )
            await session.commit()


async def _make_admin(email: str) -> None:
    from app.db import SessionLocal
    from app.models import User

    async with SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        user.role = "admin"
        await session.commit()


async def _create_workflow(client, headers: dict[str, str], definition: dict) -> str:
    response = await client.post(
        "/workflows",
        json={"name": "S5c workflow", "description": "s5c", "definition": definition},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_catalog_exposes_s5c_nodes(client, api):
    headers = await api.headers("p8s5c-catalog@example.com")
    catalog = await client.get("/workflows/catalog", headers=headers)
    assert catalog.status_code == 200
    types = {item["type"] for item in catalog.json()["nodes"]}
    assert {"review", "loop", "http", "mcp", "memory_read", "memory_write"} <= types


async def test_loop_memory_and_http_nodes(client, api, registry, monkeypatch):
    headers = await api.headers("p8s5c-nodes@example.com")
    await _seed_model_catalog()
    definition = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "loop1",
                "type": "loop",
                "config": {
                    "mode": "foreach",
                    "items": "alpha\nbeta",
                    "provider_id": "fake",
                    "model": "fake-model",
                    "prompt": "Do {{item}} #{{index}}",
                    "max_iterations": 2,
                    "separator": "\n",
                },
            },
            {
                "id": "save",
                "type": "memory_write",
                "config": {
                    "title": "Summary",
                    "content": "{{loop1}}",
                    "scope": "user",
                    "kind": "summary",
                },
            },
            {
                "id": "read",
                "type": "memory_read",
                "config": {"query": "Summary", "limit": 5, "scope": "user"},
            },
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": "loop1"},
            {"from": "loop1", "to": "save"},
            {"from": "save", "to": "read"},
            {"from": "read", "to": "out"},
        ],
    }
    workflow_id = await _create_workflow(client, headers, definition)
    started = await client.post(
        f"/workflows/{workflow_id}/runs", json={"input": "go"}, headers=headers
    )
    assert started.status_code == 202
    detail = await client.get(
        f"/workflows/runs/{started.json()['run_id']}", headers=headers
    )
    payload = detail.json()
    assert payload["status"] == "completed"
    assert len(registry.get("fake").calls) == 2

    memories = await client.get("/memories", headers=headers)
    assert memories.status_code == 200
    items = memories.json()
    assert len(items) == 1
    assert items[0]["title"] == "Summary"
    assert items[0]["source"] == "workflow"
    assert "Hello" in items[0]["content"]

    async def fake_outbound(method, url, **kwargs):
        assert method == "GET"
        assert url == "https://api.example.com/ping"
        return "pong"

    monkeypatch.setattr("app.services.workflow.runner.request_outbound", fake_outbound)
    http_definition = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "fetch",
                "type": "http",
                "config": {
                    "method": "GET",
                    "url": "https://api.example.com/ping",
                    "headers": {},
                    "timeout_seconds": 5,
                },
            },
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": "fetch"},
            {"from": "fetch", "to": "out"},
        ],
    }
    http_workflow = await _create_workflow(client, headers, http_definition)
    http_run = await client.post(
        f"/workflows/{http_workflow}/runs", json={"input": "go"}, headers=headers
    )
    http_detail = await client.get(
        f"/workflows/runs/{http_run.json()['run_id']}", headers=headers
    )
    assert http_detail.json()["status"] == "completed"


async def test_outbound_guard_blocks_private_addresses():
    with pytest.raises(OutboundError) as rejected:
        await validate_outbound_url("http://127.0.0.1/internal")
    assert rejected.value.code in {"invalid_url", "host_not_allowed"}
    with pytest.raises(OutboundError):
        await validate_outbound_url("file:///etc/passwd")


async def test_review_node_approve_and_reject(client, api):
    headers = await api.headers("p8s5c-review@example.com")
    definition = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "gate",
                "type": "review",
                "config": {"prompt": "Please review: {{input}}", "timeout_seconds": 60},
            },
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": "gate"},
            {"from": "gate", "to": "out"},
        ],
    }
    workflow_id = await _create_workflow(client, headers, definition)

    async def start_and_wait() -> tuple[dict, list[dict]]:
        task = asyncio.create_task(
            client.post(
                f"/workflows/{workflow_id}/runs",
                json={"input": "draft"},
                headers=headers,
            )
        )
        pending: list[dict] = []
        for _ in range(100):
            await asyncio.sleep(0.05)
            listing = await client.get(
                "/workflows/reviews?status=pending", headers=headers
            )
            pending = listing.json()
            if pending:
                break
        assert pending, "review was not created"
        return task, pending

    approved_task, approved_pending = await start_and_wait()
    approved_review = approved_pending[0]
    assert "draft" in approved_review["prompt"]
    responded = await client.post(
        f"/workflows/reviews/{approved_review['id']}/respond",
        json={"decision": "approved", "comment": "looks good"},
        headers=headers,
    )
    assert responded.status_code == 200, responded.text
    approved_run = await asyncio.wait_for(approved_task, timeout=10)
    assert approved_run.status_code == 202
    detail = await client.get(
        f"/workflows/runs/{approved_run.json()['run_id']}", headers=headers
    )
    assert detail.json()["status"] == "completed"
    gate = next(node for node in detail.json()["nodes"] if node["node_id"] == "gate")
    assert gate["status"] == "completed"

    rejected_task, rejected_pending = await start_and_wait()
    rejected_review = rejected_pending[0]
    rejected = await client.post(
        f"/workflows/reviews/{rejected_review['id']}/respond",
        json={"decision": "rejected", "comment": "not acceptable"},
        headers=headers,
    )
    assert rejected.status_code == 200
    rejected_run = await asyncio.wait_for(rejected_task, timeout=10)
    rejected_detail = await client.get(
        f"/workflows/runs/{rejected_run.json()['run_id']}", headers=headers
    )
    assert rejected_detail.json()["status"] == "failed"
    assert rejected_detail.json()["error_code"] == "review_rejected"

    repeat = await client.post(
        f"/workflows/reviews/{approved_review['id']}/respond",
        json={"decision": "approved"},
        headers=headers,
    )
    assert repeat.status_code == 409


async def test_mcp_node_and_admin_endpoints(client, api, monkeypatch):
    headers = await api.headers("p8s5c-mcp@example.com")
    admin_headers = await api.headers("p8s5c-mcp-admin@example.com")
    await _make_admin("p8s5c-mcp-admin@example.com")

    async def fake_validate(*_args, **_kwargs):
        return None

    async def fake_tools(*_args, **_kwargs):
        return [
            {
                "name": "search_docs",
                "description": "Search documentation",
                "input_schema": {"type": "object"},
            }
        ]

    monkeypatch.setattr(
        "app.routers.mcp_servers.validate_outbound_url", fake_validate
    )
    monkeypatch.setattr("app.routers.mcp_servers.list_mcp_tools", fake_tools)

    created = await client.post(
        "/admin/mcp-servers",
        json={
            "name": "Docs MCP",
            "description": "internal docs",
            "endpoint_url": "https://mcp.example.com/mcp",
            "auth_token": "mcp-secret-token",
            "enabled": True,
            "timeout_seconds": 10,
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    server = created.json()
    assert server["auth_hint"]
    assert "auth_token" not in json.dumps(server)

    listed = await client.get("/mcp-servers", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "Docs MCP"

    tools = await client.get(f"/admin/mcp-servers/{server['id']}/tools", headers=admin_headers)
    assert tools.status_code == 200
    assert tools.json()[0]["name"] == "search_docs"

    definition = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "call",
                "type": "mcp",
                "config": {
                    "server_id": server["id"],
                    "tool": "search_docs",
                    "arguments": {"query": "{{input}}"},
                    "timeout_seconds": 5,
                },
            },
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": "call"},
            {"from": "call", "to": "out"},
        ],
    }

    async def fake_call(_server, tool, arguments, **_kwargs):
        assert tool == "search_docs"
        assert arguments == {"query": "hello"}
        return "mcp result"

    monkeypatch.setattr("app.services.workflow.runner.call_mcp_tool", fake_call)
    workflow_id = await _create_workflow(client, headers, definition)
    started = await client.post(
        f"/workflows/{workflow_id}/runs", json={"input": "hello"}, headers=headers
    )
    detail = await client.get(
        f"/workflows/runs/{started.json()['run_id']}", headers=headers
    )
    assert detail.json()["status"] == "completed"


async def test_agent_reviews_and_report_moderation(client, api):
    author = await api.headers("p8s5c-author@example.com")
    reviewer = await api.headers("p8s5c-reviewer@example.com")
    admin = await api.headers("p8s5c-admin@example.com")
    await _make_admin("p8s5c-admin@example.com")

    agent = await client.post(
        "/agents",
        json={
            "name": "Reviewable agent",
            "description": "S5c review target",
            "instructions": "Be useful.",
            "category": "general",
            "mode": "autonomous",
        },
        headers=author,
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["id"]
    published = await client.post(
        f"/agents/{agent_id}/publish",
        json={"slug": "reviewable-agent", "allow_copy": True, "show_structure": True},
        headers=author,
    )
    assert published.status_code == 200, published.text

    review = await client.put(
        f"/agents/{agent_id}/review",
        json={"rating": 4, "content": "Solid, could be faster."},
        headers=reviewer,
    )
    assert review.status_code == 200, review.text
    assert review.json()["rating"] == 4

    public_reviews = await client.get("/market/agents/reviewable-agent/reviews")
    assert public_reviews.status_code == 200
    assert public_reviews.json()["rating_count"] == 1
    assert public_reviews.json()["rating_avg"] == 4.0
    assert public_reviews.json()["reviews"][0]["author"].startswith("p***@")

    updated = await client.put(
        f"/agents/{agent_id}/review",
        json={"rating": 5, "content": "Even better on retry."},
        headers=reviewer,
    )
    assert updated.status_code == 200
    detail = await client.get("/market/agents/reviewable-agent")
    assert detail.json()["rating_avg"] == 5.0
    assert detail.json()["rating_count"] == 1

    mine = await client.get(f"/agents/{agent_id}/review", headers=reviewer)
    assert mine.status_code == 200
    assert mine.json()["rating"] == 5

    hidden = await client.post(
        f"/admin/agent-reviews/{mine.json()['id']}/visibility",
        json={"visible": False},
        headers=admin,
    )
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["status"] == "hidden"
    after_hide = await client.get("/market/agents/reviewable-agent")
    assert after_hide.json()["rating_count"] == 0
    restored = await client.post(
        f"/admin/agent-reviews/{mine.json()['id']}/visibility",
        json={"visible": True},
        headers=admin,
    )
    assert restored.status_code == 200
    after_restore = await client.get("/market/agents/reviewable-agent")
    assert after_restore.json()["rating_count"] == 1

    report = await client.post(
        f"/agents/{agent_id}/report",
        json={"reason": "misleading", "detail": "The description overpromises."},
        headers=reviewer,
    )
    assert report.status_code == 201, report.text
    duplicate = await client.post(
        f"/agents/{agent_id}/report",
        json={"reason": "spam", "detail": "again"},
        headers=reviewer,
    )
    assert duplicate.status_code == 409

    reports = await client.get("/admin/agent-reports?status=open", headers=admin)
    assert reports.status_code == 200
    assert len(reports.json()) == 1
    resolved = await client.post(
        f"/admin/agent-reports/{reports.json()[0]['id']}/resolve",
        json={"action": "unpublish", "resolution": "Confirmed misleading"},
        headers=admin,
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"

    gone = await client.get("/market/agents/reviewable-agent")
    assert gone.status_code == 404


async def test_memory_crud_and_isolation(client, api):
    owner = await api.headers("p8s5c-memory-owner@example.com")
    other = await api.headers("p8s5c-memory-other@example.com")

    created = await client.post(
        "/memories",
        json={
            "content": "Prefers concise Chinese answers.",
            "title": "Style",
            "scope": "user",
            "kind": "preference",
            "importance": 5,
        },
        headers=owner,
    )
    assert created.status_code == 201, created.text
    memory_id = created.json()["id"]

    listing = await client.get("/memories?q=concise", headers=owner)
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    hidden = await client.patch(
        f"/memories/{memory_id}", json={"content": "hijack"}, headers=other
    )
    assert hidden.status_code == 404
    assert (await client.delete(f"/memories/{memory_id}", headers=other)).status_code == 404

    updated = await client.patch(
        f"/memories/{memory_id}",
        json={"content": "Prefers short answers.", "importance": 4},
        headers=owner,
    )
    assert updated.status_code == 200
    assert updated.json()["importance"] == 4

    deleted = await client.delete(f"/memories/{memory_id}", headers=owner)
    assert deleted.status_code == 204
    assert (await client.get("/memories", headers=owner)).json() == []

async def test_publish_sanitizes_outbound_and_memory_configs(client, api):
    headers = await api.headers("p8s5c-sanitize@example.com")
    definition = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "fetch",
                "type": "http",
                "config": {
                    "method": "POST",
                    "url": "https://api.example.com/private?token=abc",
                    "headers": {"Authorization": "Bearer secret"},
                    "body": "{\"key\": \"secret\"}",
                    "timeout_seconds": 5,
                },
            },
            {
                "id": "call",
                "type": "mcp",
                "config": {
                    "server_id": "00000000-0000-0000-0000-000000000123",
                    "tool": "search",
                    "arguments": {"query": "private"},
                    "timeout_seconds": 5,
                },
            },
            {
                "id": "remember",
                "type": "memory_write",
                "config": {
                    "title": "Private",
                    "content": "internal secret",
                    "scope": "user",
                    "kind": "fact",
                },
            },
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": "fetch"},
            {"from": "fetch", "to": "call"},
            {"from": "call", "to": "remember"},
            {"from": "remember", "to": "out"},
        ],
    }
    workflow_id = await _create_workflow(client, headers, definition)
    created = await client.post(
        "/agents",
        json={
            "name": "Sanitized agent",
            "description": "Publishes sanitized structure",
            "instructions": "Use tools carefully.",
            "category": "general",
            "mode": "workflow",
            "workflow_id": workflow_id,
            "provider_id": "fake",
            "model": "fake-model",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    agent_id = created.json()["id"]
    published = await client.post(
        f"/agents/{agent_id}/publish",
        json={"slug": "sanitized-agent", "allow_copy": True, "show_structure": True},
        headers=headers,
    )
    assert published.status_code == 200, published.text
    detail = await client.get("/market/agents/sanitized-agent")
    nodes = {
        node["id"]: node
        for node in detail.json()["workflow"]["definition"]["nodes"]
    }
    assert nodes["fetch"]["config"]["url"] == ""
    assert nodes["fetch"]["config"]["headers"] == {}
    assert nodes["fetch"]["config"]["body"] == ""
    assert "server_id" not in nodes["call"]["config"]
    assert nodes["call"]["config"]["arguments"] == {}
    assert nodes["remember"]["config"]["content"] == ""


async def test_review_resumes_after_worker_restart(client, api, fake_redis):
    from app.db import SessionLocal
    from app.models import Workflow, WorkflowRun, WorkflowVersion
    from app.services.run_execution import execute_workflow_run

    headers = await api.headers("p8s5c-resume@example.com")
    definition = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "gate",
                "type": "review",
                "config": {"prompt": "Approve {{input}}", "timeout_seconds": 60},
            },
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [{"from": "start", "to": "gate"}, {"from": "gate", "to": "out"}],
    }
    workflow_id = await _create_workflow(client, headers, definition)

    from uuid import UUID

    async with SessionLocal() as session:
        workflow = await session.get(Workflow, UUID(workflow_id))
        assert workflow is not None and workflow.created_by is not None
        version = (
            await session.execute(
                select(WorkflowVersion)
                .where(WorkflowVersion.workflow_id == workflow.id)
                .order_by(WorkflowVersion.version.desc())
                .limit(1)
            )
        ).scalar_one()
        run = WorkflowRun(
            workflow_id=workflow.id,
            version_id=version.id,
            workspace_id=workflow.workspace_id,
            user_id=workflow.created_by,
            status="queued",
            input_text="checkpoint",
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_id = run.id

    task = asyncio.create_task(execute_workflow_run(run_id, redis=fake_redis))
    pending: list[dict] = []
    for _ in range(100):
        await asyncio.sleep(0.05)
        listing = await client.get("/workflows/reviews?status=pending", headers=headers)
        pending = listing.json()
        if pending:
            break
    assert pending, "review was not created"

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    seen: set[str] = set()
    for _ in range(100):
        async with SessionLocal() as session:
            paused = await session.get(WorkflowRun, run_id)
            if paused is not None:
                seen.add(paused.status)
                if paused.status == "waiting_review":
                    assert paused.checkpoint.get("pending_reviews")
                    break
        await asyncio.sleep(0.05)
    else:
        raise AssertionError(f"run did not pause after cancellation: {seen}")

    approved = await client.post(
        f"/workflows/reviews/{pending[0]['id']}/respond",
        json={"decision": "approved", "comment": "resume ok"},
        headers=headers,
    )
    assert approved.status_code == 200, approved.text

    detail = await client.get(f"/workflows/runs/{run_id}", headers=headers)
    assert detail.json()["status"] == "completed", detail.text
    gates = [node for node in detail.json()["nodes"] if node["node_id"] == "gate"]
    assert gates and all(node["status"] == "completed" for node in gates)


async def test_code_node_and_sandbox(client, api):
    from app.services.sandbox import SandboxError, evaluate_expression

    headers = await api.headers("p8s5d-code@example.com")
    definition = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "shape",
                "type": "code",
                "config": {"code": "input.upper()", "max_output_chars": 100},
            },
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [{"from": "start", "to": "shape"}, {"from": "shape", "to": "out"}],
    }
    workflow_id = await _create_workflow(client, headers, definition)
    started = await client.post(
        f"/workflows/{workflow_id}/runs", json={"input": "hello"}, headers=headers
    )
    detail = await client.get(
        f"/workflows/runs/{started.json()['run_id']}", headers=headers
    )
    assert detail.json()["status"] == "completed"
    shape = next(node for node in detail.json()["nodes"] if node["node_id"] == "shape")
    assert shape["output_summary"] == "HELLO"

    assert evaluate_expression('"x".upper()', {}) == "X"
    assert (
        evaluate_expression('json_dumps({"n": len(input)})', {"input": "abc"})
        == '{"n": 3}'
    )
    assert evaluate_expression('f"{input}-{len(input)}"', {"input": "ab"}) == "ab-2"
    for forbidden in [
        "__import__('os')",
        "input.__class__",
        "open('/etc/passwd')",
        "[x for x in [1]]",
        "lambda: 1",
    ]:
        with pytest.raises(SandboxError):
            evaluate_expression(forbidden, {"input": ""})


async def test_database_connection_admin_and_node(client, api, monkeypatch):
    from app.services.database_nodes import (
        DatabaseNodeError,
        normalize_dsn,
        validate_read_query,
    )

    headers = await api.headers("p8s5d-db@example.com")
    admin = await api.headers("p8s5d-db-admin@example.com")
    await _make_admin("p8s5d-db-admin@example.com")

    created = await client.post(
        "/admin/database-connections",
        json={
            "name": "Analytics",
            "description": "read-only analytics",
            "dsn": "postgresql+asyncpg://reader:secret@db.internal:5432/analytics",
            "enabled": True,
            "max_rows": 50,
            "timeout_seconds": 10,
        },
        headers=admin,
    )
    assert created.status_code == 201, created.text
    connection = created.json()
    assert "dsn" not in connection
    assert "secret" not in json.dumps(connection)

    hidden = await client.get("/admin/database-connections", headers=headers)
    assert hidden.status_code == 404

    options = await client.get("/database-connections", headers=headers)
    assert options.status_code == 200
    assert options.json()[0]["name"] == "Analytics"

    async def fake_test(*_args, **_kwargs):
        return 1

    monkeypatch.setattr(
        "app.routers.database_connections.test_connection", fake_test
    )
    tested = await client.post(
        f"/admin/database-connections/{connection['id']}/test", headers=admin
    )
    assert tested.status_code == 200
    assert tested.json()["value"] == 1

    async def fake_execute(_connection, query, params, **_kwargs):
        assert "select" in query.lower()
        assert params == {"q": "hello"}
        return '[{"x": 1}]'

    monkeypatch.setattr(
        "app.services.workflow.runner.execute_read_query", fake_execute
    )
    definition = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "query",
                "type": "database",
                "config": {
                    "connection_id": connection["id"],
                    "query": "SELECT :q AS q",
                    "params": {"q": "{{input}}"},
                    "max_rows": 10,
                    "timeout_seconds": 5,
                },
            },
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [{"from": "start", "to": "query"}, {"from": "query", "to": "out"}],
    }
    workflow_id = await _create_workflow(client, headers, definition)
    started = await client.post(
        f"/workflows/{workflow_id}/runs", json={"input": "hello"}, headers=headers
    )
    detail = await client.get(
        f"/workflows/runs/{started.json()['run_id']}", headers=headers
    )
    assert detail.json()["status"] == "completed"

    with pytest.raises(DatabaseNodeError):
        validate_read_query("DELETE FROM users")
    with pytest.raises(DatabaseNodeError):
        validate_read_query("SELECT 1; DROP TABLE users")
    with pytest.raises(DatabaseNodeError):
        normalize_dsn("mysql+aiomysql://user:pass@host/db")


async def test_mcp_resource_and_prompt_nodes(client, api, monkeypatch):
    headers = await api.headers("p8s5d-mcp@example.com")
    admin = await api.headers("p8s5d-mcp-admin@example.com")
    await _make_admin("p8s5d-mcp-admin@example.com")

    async def fake_validate(*_args, **_kwargs):
        return None

    async def fake_tools(*_args, **_kwargs):
        return []

    async def fake_resources(*_args, **_kwargs):
        return [
            {
                "uri": "memo://docs",
                "name": "Docs",
                "description": "docs",
                "mime_type": "text/plain",
            }
        ]

    async def fake_prompts(*_args, **_kwargs):
        return [{"name": "summarize", "description": "summarize", "arguments": []}]

    monkeypatch.setattr("app.routers.mcp_servers.validate_outbound_url", fake_validate)
    monkeypatch.setattr("app.routers.mcp_servers.list_mcp_tools", fake_tools)
    monkeypatch.setattr("app.routers.mcp_servers.list_mcp_resources", fake_resources)
    monkeypatch.setattr("app.routers.mcp_servers.list_mcp_prompts", fake_prompts)
    created = await client.post(
        "/admin/mcp-servers",
        json={
            "name": "Deep MCP",
            "endpoint_url": "https://mcp.example.com/mcp",
            "enabled": True,
        },
        headers=admin,
    )
    assert created.status_code == 201, created.text
    server = created.json()

    resources = await client.get(
        f"/admin/mcp-servers/{server['id']}/resources", headers=admin
    )
    assert resources.status_code == 200
    assert resources.json()[0]["uri"] == "memo://docs"
    prompts = await client.get(
        f"/admin/mcp-servers/{server['id']}/prompts", headers=admin
    )
    assert prompts.status_code == 200
    assert prompts.json()[0]["name"] == "summarize"

    async def fake_read(_server, uri, **_kwargs):
        assert uri == "memo://docs"
        return "resource body"

    async def fake_prompt(_server, name, arguments, **_kwargs):
        assert name == "summarize"
        assert arguments == {"topic": "hello"}
        return "prompt body"

    monkeypatch.setattr("app.services.workflow.runner.read_mcp_resource", fake_read)
    monkeypatch.setattr("app.services.workflow.runner.get_mcp_prompt", fake_prompt)
    definition = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "read",
                "type": "mcp_resource",
                "config": {"server_id": server["id"], "uri": "memo://docs"},
            },
            {
                "id": "prompt",
                "type": "mcp_prompt",
                "config": {
                    "server_id": server["id"],
                    "name": "summarize",
                    "arguments": {"topic": "{{input}}"},
                },
            },
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": "read"},
            {"from": "read", "to": "prompt"},
            {"from": "prompt", "to": "out"},
        ],
    }
    workflow_id = await _create_workflow(client, headers, definition)
    started = await client.post(
        f"/workflows/{workflow_id}/runs", json={"input": "hello"}, headers=headers
    )
    detail = await client.get(
        f"/workflows/runs/{started.json()['run_id']}", headers=headers
    )
    assert detail.json()["status"] == "completed"


async def test_memory_vector_recall(client, api, monkeypatch):
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import User, WorkspaceMember
    from app.services import memories as memory_service

    headers = await api.headers("p8s5d-vector@example.com")
    assert headers
    async with SessionLocal() as session:
        user = (
            await session.execute(
                select(User).where(User.email == "p8s5d-vector@example.com")
            )
        ).scalar_one()
        member = (
            await session.execute(
                select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
            )
        ).scalar_one()

    class FakeEmbedder:
        async def embed(self, texts):
            return [[1.0, 0.0] if "cat" in text else [0.0, 1.0] for text in texts]

    settings = get_settings()
    previous = settings.memory_embedding_enabled
    settings.memory_embedding_enabled = True
    monkeypatch.setattr(memory_service, "build_embedder", lambda: FakeEmbedder())
    try:
        async with SessionLocal() as session:
            await memory_service.create_memory(
                session,
                workspace_id=member.workspace_id,
                user_id=user.id,
                content="cat lives here",
                title="cat",
            )
            await memory_service.create_memory(
                session,
                workspace_id=member.workspace_id,
                user_id=user.id,
                content="dog lives here",
                title="dog",
            )
            await session.commit()
            block = await memory_service.memory_context(
                session,
                workspace_id=member.workspace_id,
                user_id=user.id,
                agent_id=None,
                query="cat",
                limit=5,
                max_chars=2000,
            )
    finally:
        settings.memory_embedding_enabled = previous
    assert "cat lives here" in block
    assert "dog lives here" not in block
