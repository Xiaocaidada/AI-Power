from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    AgentMemory,
    CustomAgent,
    WorkflowNodeRun,
    WorkflowRun,
    WorkflowVersion,
)
from app.services.memories import memory_feedback_scores
from app.services.parsing import ParsedPage


async def _agent(client, headers, name: str) -> dict:
    response = await client.post(
        "/agents",
        json={
            "name": name,
            "description": "Analytics agent",
            "instructions": "Help with tasks.",
            "default_provider_id": "fake",
            "default_model": "fake-model",
            "tools": ["calculator"],
            "visibility": "private",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_agent_analytics_aggregates_runs_and_slow_nodes(
    client, api, registry
):
    headers = await api.headers("p11s11-analytics@example.com")
    agent = await _agent(client, headers, "Analytics Agent")
    conversation = await client.post(
        "/conversations",
        json={
            "custom_agent_id": agent["id"],
            "provider_id": "fake",
            "model": "fake-model",
        },
        headers=headers,
    )
    assert conversation.status_code == 201, conversation.text

    template = await client.post(
        "/agents/from-template",
        json={
            "template": "assistant",
            "name": "Workflow analytics agent",
            "description": "Has a workflow",
            "provider_id": "fake",
            "model": "fake-model",
        },
        headers=headers,
    )
    assert template.status_code == 201, template.text
    workflow_agent = template.json()
    async with SessionLocal() as session:
        stored = await session.get(CustomAgent, UUID(workflow_agent["id"]))
        assert stored is not None and stored.workflow_id is not None
        workspace_id, user_id, workflow_id = (
            stored.workspace_id,
            stored.owner_user_id,
            stored.workflow_id,
        )
        version_id = (
            await session.execute(
                select(WorkflowVersion.id)
                .where(WorkflowVersion.workflow_id == workflow_id)
                .order_by(WorkflowVersion.version.desc())
                .limit(1)
            )
        ).scalar_one()
        completed = WorkflowRun(
            workflow_id=workflow_id,
            version_id=version_id,
            workspace_id=workspace_id,
            user_id=user_id,
            status="completed",
            input_text="task",
            total_ms=12000,
            prompt_tokens=100,
            completion_tokens=50,
            cost=0.01,
        )
        failed = WorkflowRun(
            workflow_id=workflow_id,
            version_id=version_id,
            workspace_id=workspace_id,
            user_id=user_id,
            status="failed",
            error_code="node_failed",
            input_text="task",
            total_ms=3000,
        )
        session.add_all([completed, failed])
        await session.flush()
        session.add_all(
            [
                WorkflowNodeRun(
                    run_id=completed.id,
                    node_id="slow",
                    node_type="llm",
                    status="completed",
                    duration_ms=9000,
                ),
                WorkflowNodeRun(
                    run_id=failed.id,
                    node_id="slow",
                    node_type="llm",
                    status="failed",
                    error_code="node_failed",
                    duration_ms=2500,
                ),
            ]
        )
        await session.commit()

    response = await client.get(
        f"/agents/{workflow_agent['id']}/analytics?days=30", headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["workflow_runs"] == 2
    assert body["completed"] == 1
    assert body["failed"] == 1
    assert body["failure_codes"]["node_failed"] >= 1
    assert body["slow_nodes"][0]["node_id"] == "slow"
    suggestions = {item["kind"] for item in body["suggestions"]}
    assert "review_failures" in suggestions
    assert "inspect_node" in suggestions

    foreign = await api.headers("p11s11-analytics-other@example.com")
    assert (
        await client.get(
            f"/agents/{workflow_agent['id']}/analytics", headers=foreign
        )
    ).status_code == 404


async def test_document_parse_preview(client, api, fake_ingestion):
    headers = await api.headers("p11s11-parse@example.com")
    fake_ingestion.parser.pages = [
        ParsedPage(page_no=1, text="x" * 6000),
        ParsedPage(page_no=2, text="second page"),
    ]
    kb = await client.post(
        "/knowledge-bases", json={"name": "Parse preview"}, headers=headers
    )
    assert kb.status_code == 201, kb.text
    uploaded = await client.post(
        f"/knowledge-bases/{kb.json()['id']}/documents",
        files={"file": ("long.txt", b"x" * 6000, "text/plain")},
        headers=headers,
    )
    assert uploaded.status_code in {201, 202}, uploaded.text
    document_id = uploaded.json()["id"]

    preview = await client.get(
        f"/documents/{document_id}/parse-preview", headers=headers
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["page_count"] == 1
    assert len(body["pages"][0]["text"]) == 5000
    assert body["pages"][0]["truncated"] is True
    assert body["truncated"] is True

    foreign = await api.headers("p11s11-parse-other@example.com")
    assert (
        await client.get(
            f"/documents/{document_id}/parse-preview", headers=foreign
        )
    ).status_code == 404


async def test_memory_feedback_loop_and_quality_suggestion(client, api):
    headers = await api.headers("p11s11-feedback@example.com")
    created = await client.post(
        "/memories",
        json={
            "title": "Feedback memory",
            "content": "Feedback loop candidate",
            "category": "technical",
            "scope_type": "global",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    memory = created.json()

    initial = await client.get(
        f"/memories/{memory['id']}/feedback", headers=headers
    )
    assert initial.status_code == 200
    assert initial.json()["rating"] is None

    unhelpful = await client.put(
        f"/memories/{memory['id']}/feedback",
        json={"rating": "unhelpful", "context_type": "manual"},
        headers=headers,
    )
    assert unhelpful.status_code == 200, unhelpful.text
    assert unhelpful.json()["unhelpful_count"] == 1

    second = await client.put(
        f"/memories/{memory['id']}/feedback",
        json={"rating": "unhelpful", "context_type": "chat", "context_id": "c1"},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["unhelpful_count"] == 2

    async with SessionLocal() as session:
        row = await session.get(AgentMemory, UUID(memory["id"]))
        assert row is not None
        scores = await memory_feedback_scores(
            session,
            workspace_id=row.workspace_id,
            user_id=row.user_id,
            memory_ids=[row.id],
        )
        assert scores[row.id] == (0, 2)

    analyzed = await client.post("/memories/quality/analyze", headers=headers)
    assert analyzed.status_code == 200, analyzed.text
    kinds = {item["kind"] for item in analyzed.json()["suggestions"]}
    assert "review_feedback" in kinds

    foreign = await api.headers("p11s11-feedback-other@example.com")
    assert (
        await client.get(
            f"/memories/{memory['id']}/feedback", headers=foreign
        )
    ).status_code == 404

    cleared = await client.delete(
        f"/memories/{memory['id']}/feedback", headers=headers
    )
    assert cleared.status_code == 204
    after = await client.get(f"/memories/{memory['id']}/feedback", headers=headers)
    assert after.json()["unhelpful_count"] == 0