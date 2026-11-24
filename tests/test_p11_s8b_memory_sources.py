import json
from uuid import UUID

from app.config import get_settings
from app.db import SessionLocal
from app.models import Workflow, WorkflowRun, WorkflowVersion
from app.services.memory_extraction import (
    run_document_memory_extraction,
    run_workflow_memory_extraction,
)


def _extraction_payload(content="Workflow uses PostgreSQL for durable storage."):
    return json.dumps(
        [
            {
                "category": "technical",
                "title": "Durable storage choice",
                "content": content,
                "scope_type": "global",
                "confidence": 0.9,
                "tags": ["architecture"],
                "reason": "long-term technical decision",
            }
        ]
    )


async def _enable_sources(client, headers, **overrides):
    payload = {
        "enabled": True,
        "auto_extract": True,
        "require_confirmation": True,
        "auto_save": False,
        **overrides,
    }
    response = await client.patch("/memories/settings", json=payload, headers=headers)
    assert response.status_code == 200, response.text


async def test_settings_expose_source_switches_off_by_default(client, api):
    headers = await api.headers("p11s8b-settings@example.com")
    response = await client.get("/memories/settings", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["allow_workflow_extract"] is False
    assert body["allow_document_extract"] is False

    updated = await client.patch(
        "/memories/settings",
        json={"allow_workflow_extract": True, "allow_document_extract": True},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["allow_workflow_extract"] is True
    assert updated.json()["allow_document_extract"] is True


async def _create_workflow(client, headers, *, authorized: bool) -> dict:
    response = await client.post(
        "/workflows",
        json={
            "name": "Memory source workflow",
            "description": "Completed runs may feed memory.",
            "definition": {
                "nodes": [
                    {
                        "id": "answer",
                        "type": "llm",
                        "config": {
                            "provider_id": "fake",
                            "model": "fake-model",
                            "prompt": "Answer {{input}}",
                        },
                    }
                ],
                "edges": [],
            },
            "memory_extract_enabled": authorized,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_workflow_source_requires_opt_in_and_extracts_once(
    client, api, registry
):
    headers = await api.headers("p11s8b-workflow@example.com")
    unauthorized = await _create_workflow(client, headers, authorized=False)
    authorized = await _create_workflow(client, headers, authorized=True)
    await _enable_sources(client, headers, allow_workflow_extract=True)
    registry.get("fake").complete_content = _extraction_payload()

    async with SessionLocal() as session:
        workflow = await session.get(Workflow, UUID(authorized["id"]))
        assert workflow is not None
        version = (
            await session.execute(
                WorkflowVersion.__table__.select()
                .where(WorkflowVersion.workflow_id == workflow.id)
                .order_by(WorkflowVersion.version.desc())
                .limit(1)
            )
        ).first()
        assert version is not None
        run = WorkflowRun(
            workflow_id=workflow.id,
            version_id=version.id,
            workspace_id=workflow.workspace_id,
            user_id=workflow.created_by,
            status="completed",
            input_text="Design the storage layer.",
            output_payload={"result": "Use PostgreSQL with async sessions."},
        )
        unauthorized_workflow = await session.get(Workflow, UUID(unauthorized["id"]))
        assert unauthorized_workflow is not None
        unauthorized_run = WorkflowRun(
            workflow_id=unauthorized_workflow.id,
            version_id=version.id,
            workspace_id=unauthorized_workflow.workspace_id,
            user_id=unauthorized_workflow.created_by,
            status="completed",
            input_text="Should not be extracted.",
            output_payload={"result": "Nothing to remember."},
        )
        session.add_all([run, unauthorized_run])
        await session.commit()
        await session.refresh(run)
        await session.refresh(unauthorized_run)
        authorized_run_id = run.id
        unauthorized_run_id = unauthorized_run.id

    skipped = await run_workflow_memory_extraction(
        unauthorized_run_id, registry=registry, settings=get_settings()
    )
    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "source_not_authorized"

    result = await run_workflow_memory_extraction(
        authorized_run_id, registry=registry, settings=get_settings()
    )
    assert result["status"] == "completed", result
    assert result["pending"] == 1

    again = await run_workflow_memory_extraction(
        authorized_run_id, registry=registry, settings=get_settings()
    )
    assert again["status"] == "skipped"
    assert again["reason"] == "already_processed"

    candidates = await client.get(
        "/memories/candidates?status=pending", headers=headers
    )
    assert candidates.status_code == 200, candidates.text
    rows = candidates.json()
    assert len(rows) == 1
    assert rows[0]["source_type"] == "workflow_run"
    assert rows[0]["source_id"] == str(authorized_run_id)


async def test_document_source_requires_uploader_authorization(
    client, api, fake_ingestion, registry
):
    from app.services.parsing import ParsedPage

    fake_ingestion.parser.pages = [
        ParsedPage(
            page_no=1,
            text=(
                "This project keeps durable notes about the service architecture. "
                "The team decided to use PostgreSQL for durable storage and async "
                "sessions for every request path."
            ),
        )
    ]
    owner = await api.headers("p11s8b-doc-owner@example.com")
    other = await api.headers("p11s8b-doc-other@example.com")
    kb = await client.post("/knowledge-bases", json={"name": "Memory docs"}, headers=owner)
    assert kb.status_code == 201, kb.text
    uploaded = await client.post(
        f"/knowledge-bases/{kb.json()['id']}/documents",
        files={"file": ("notes.txt", b"notes", "text/plain")},
        headers=owner,
    )
    assert uploaded.status_code in {201, 202}, uploaded.text
    document_id = uploaded.json()["id"]
    detail = await client.get(f"/documents/{document_id}", headers=owner)
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "ready"

    forbidden = await client.patch(
        f"/documents/{document_id}",
        json={"memory_extract_enabled": True},
        headers=other,
    )
    assert forbidden.status_code == 404

    enabled = await client.patch(
        f"/documents/{document_id}",
        json={"memory_extract_enabled": True},
        headers=owner,
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["memory_extract_enabled"] is True

    await _enable_sources(client, owner, allow_document_extract=True)
    registry.get("fake").complete_content = _extraction_payload(
        "The service uses PostgreSQL with async sessions."
    )
    result = await run_document_memory_extraction(
        UUID(document_id),
        registry=registry,
        settings=get_settings().model_copy(
            update={
                "memory_extraction_provider_id": "fake",
                "memory_extraction_model": "fake-model",
            }
        ),
    )
    assert result["status"] == "completed", result
    assert result["pending"] == 1

    candidates = await client.get(
        "/memories/candidates?status=pending", headers=owner
    )
    assert candidates.status_code == 200, candidates.text
    rows = candidates.json()
    assert len(rows) == 1
    assert rows[0]["source_type"] == "document"
    assert rows[0]["source_id"] == document_id