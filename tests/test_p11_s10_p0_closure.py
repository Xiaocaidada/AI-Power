from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.models import (
    AgentMemory,
    Chunk,
    Document,
    MemoryUsageEvent,
    Project,
    Workflow,
    WorkflowVersion,
)
from app.services.parsing import ParsedPage
from app.tools.base import ToolContext, ToolError
from app.tools.project_files import ProjectFilesArgs, project_files


async def _create_agent(client, headers, name: str) -> dict:
    response = await client.post(
        "/agents",
        json={
            "name": name,
            "description": "Project assistant",
            "instructions": "Help with the project.",
            "default_provider_id": "fake",
            "default_model": "fake-model",
            "tools": ["calculator"],
            "visibility": "private",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_kb_and_document(client, headers, fake_ingestion, *, text: str):
    fake_ingestion.parser.pages = [ParsedPage(page_no=1, text=text)]
    kb = await client.post(
        "/knowledge-bases", json={"name": f"KB {text[:8]}"}, headers=headers
    )
    assert kb.status_code == 201, kb.text
    uploaded = await client.post(
        f"/knowledge-bases/{kb.json()['id']}/documents",
        files={"file": ("notes.txt", b"notes", "text/plain")},
        headers=headers,
    )
    assert uploaded.status_code in {201, 202}, uploaded.text
    return kb.json()["id"], uploaded.json()["id"]


async def test_project_agents_files_and_conversation_scope(
    client, api, fake_ingestion, registry
):
    headers = await api.headers("p11s10-project@example.com")
    linked = await _create_agent(client, headers, "Linked Agent")
    other = await _create_agent(client, headers, "Other Agent")
    kb_id, document_id = await _create_kb_and_document(
        client, headers, fake_ingestion, text="project knowledge body"
    )
    project = await client.post(
        "/projects",
        json={"name": "Resource project", "instructions": "Use project files."},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]

    added = await client.post(
        f"/projects/{project_id}/agents",
        json={"agent_id": linked["id"]},
        headers=headers,
    )
    assert added.status_code == 201, added.text
    listed = await client.get(f"/projects/{project_id}/agents", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [row["agent_id"] for row in listed.json()] == [linked["id"]]

    attached = await client.post(
        f"/projects/{project_id}/files",
        json={"document_id": document_id},
        headers=headers,
    )
    assert attached.status_code == 201, attached.text
    files = await client.get(f"/projects/{project_id}/files", headers=headers)
    assert files.status_code == 200, files.text
    assert files.json()[0]["document_id"] == document_id

    async with SessionLocal() as session:
        row = await session.get(Project, UUID(project_id))
        assert row is not None
        workspace_id, user_id = row.workspace_id, row.owner_user_id
        loose_document = Document(
            workspace_id=workspace_id,
            kb_id=UUID(kb_id),
            user_id=user_id,
            filename="loose.txt",
            mime="text/plain",
            size_bytes=4,
            content_hash="loose",
            storage_path="loose.txt",
            status="ready",
        )
        session.add(loose_document)
        await session.commit()
        loose_id = loose_document.id

    context = ToolContext(
        workspace_id=workspace_id, user_id=user_id, project_id=UUID(project_id)
    )
    listing = await project_files(context, ProjectFilesArgs(query="notes"))
    assert "notes.txt" in listing
    excerpt = await project_files(
        context, ProjectFilesArgs(document_id=UUID(document_id))
    )
    assert "project knowledge body" in excerpt

    try:
        await project_files(context, ProjectFilesArgs(document_id=loose_id))
    except ToolError as exc:
        assert exc.code == "document_not_found"
    else:
        raise AssertionError("unattached document should be rejected")

    blocked = await client.post(
        "/conversations",
        json={"project_id": project_id, "custom_agent_id": other["id"]},
        headers=headers,
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "agent_not_in_project"

    allowed = await client.post(
        "/conversations",
        json={"project_id": project_id, "custom_agent_id": linked["id"]},
        headers=headers,
    )
    assert allowed.status_code == 201, allowed.text

    foreign = await api.headers("p11s10-project-other@example.com")
    assert (
        await client.get(f"/projects/{project_id}/agents", headers=foreign)
    ).status_code == 404
    assert (
        await client.get(f"/projects/{project_id}/files", headers=foreign)
    ).status_code == 404


async def _memory(client, headers, title: str, content: str) -> dict:
    response = await client.post(
        "/memories",
        json={
            "title": title,
            "content": content,
            "category": "technical",
            "scope_type": "global",
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_memory_retrieval_filters(client, api):
    headers = await api.headers("p11s10-memory-filters@example.com")
    first = await _memory(client, headers, "Filter one", "filter alpha")
    second = await _memory(client, headers, "Filter two", "filter beta")
    relation = await client.post(
        f"/memories/{first['id']}/relations",
        json={"to_id": second["id"], "relation_type": "related"},
        headers=headers,
    )
    assert relation.status_code == 200, relation.text

    async with SessionLocal() as session:
        row = await session.get(AgentMemory, UUID(first["id"]))
        assert row is not None
        workspace_id, user_id = row.workspace_id, row.user_id
        row.source_type = "document"
        session.add(
            MemoryUsageEvent(
                workspace_id=workspace_id,
                user_id=user_id,
                memory_id=row.id,
                context_type="workflow",
                injected_chars=10,
                relevance=1.0,
            )
        )
        old = await session.get(AgentMemory, UUID(second["id"]))
        assert old is not None
        old.created_at = datetime(2020, 1, 1, tzinfo=UTC)
        await session.commit()

    by_source = await client.get(
        "/memories?source_type=document", headers=headers
    )
    assert by_source.status_code == 200, by_source.text
    assert {row["id"] for row in by_source.json()} == {first["id"]}

    by_scene = await client.get("/memories?used_in=workflow", headers=headers)
    assert by_scene.status_code == 200, by_scene.text
    assert {row["id"] for row in by_scene.json()} == {first["id"]}

    related = await client.get(
        f"/memories?related_to={first['id']}", headers=headers
    )
    assert related.status_code == 200, related.text
    assert {row["id"] for row in related.json()} == {second["id"]}

    has_relations = await client.get(
        "/memories?has_relations=true", headers=headers
    )
    assert has_relations.status_code == 200, has_relations.text
    assert {row["id"] for row in has_relations.json()} == {
        first["id"],
        second["id"],
    }

    recent = await client.get(
        "/memories?created_after=2024-01-01T00:00:00Z", headers=headers
    )
    assert recent.status_code == 200, recent.text
    assert {row["id"] for row in recent.json()} == {first["id"]}

    from app.services.memories import select_memories

    async with SessionLocal() as session:
        selection = await select_memories(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            agent_id=None,
            query="filter",
            limit=10,
            max_chars=2000,
            source_type="document",
            used_in="workflow",
        )
        assert [item.memory.id for item in selection.items] == [UUID(first["id"])]
        related_selection = await select_memories(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            agent_id=None,
            query="filter",
            limit=10,
            max_chars=2000,
            related_to=UUID(first["id"]),
        )
        assert [item.memory.id for item in related_selection.items] == [
            UUID(second["id"])
        ]


async def test_processing_version_comparison(client, api, fake_ingestion):
    headers = await api.headers("p11s10-processing@example.com")
    kb = await client.post(
        "/knowledge-bases", json={"name": "Processing comparison"}, headers=headers
    )
    assert kb.status_code == 201, kb.text
    kb_id = kb.json()["id"]

    async def upload(text: str) -> str:
        fake_ingestion.parser.pages = [ParsedPage(page_no=1, text=text)]
        response = await client.post(
            f"/knowledge-bases/{kb_id}/documents",
            files={"file": (f"{text[:5]}.txt", text.encode(), "text/plain")},
            headers=headers,
        )
        assert response.status_code in {201, 202}, response.text
        return response.json()["id"]

    first_document_id = await upload("alpha processing text")
    second_document_id = await upload("beta processing text")

    async with SessionLocal() as session:
        first_document = await session.get(Document, UUID(first_document_id))
        second_document = await session.get(Document, UUID(second_document_id))
        assert first_document is not None and second_document is not None
        workspace_id = first_document.workspace_id
        workflow_a = Workflow(
            workspace_id=workspace_id, name="Processing A", kind="knowledge_process"
        )
        workflow_b = Workflow(
            workspace_id=workspace_id, name="Processing B", kind="knowledge_process"
        )
        session.add_all([workflow_a, workflow_b])
        await session.flush()
        version_a = WorkflowVersion(
            workflow_id=workflow_a.id, version=1, definition={"nodes": [], "edges": []}
        )
        version_b = WorkflowVersion(
            workflow_id=workflow_b.id, version=1, definition={"nodes": [], "edges": []}
        )
        session.add_all([version_a, version_b])
        await session.flush()
        first_document.process_version_id = version_a.id
        second_document.process_version_id = version_b.id
        first_chunk = (
            await session.execute(
                select(Chunk)
                .where(Chunk.document_id == first_document.id)
                .order_by(Chunk.chunk_index)
                .limit(1)
            )
        ).scalar_one()
        first_chunk.chunk_meta = {
            "parent_id": "parent-1",
            "keywords": ["alpha"],
            "summary": "alpha summary",
        }
        session.add(
            Chunk(
                workspace_id=first_chunk.workspace_id,
                document_id=first_chunk.document_id,
                user_id=first_chunk.user_id,
                kb_id=first_chunk.kb_id,
                chunk_index=99,
                text=first_chunk.text,
                chunk_meta={},
            )
        )
        await session.commit()

    response = await client.get(
        f"/knowledge-bases/{kb_id}/processing/versions/compare", headers=headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sampled_chunks"] >= 3
    assert len(body["versions"]) == 2
    first = next(
        item for item in body["versions"] if item["workflow_name"] == "Processing A"
    )
    assert first["document_count"] == 1
    assert first["metadata_coverage"] == 0.5
    assert first["parent_coverage"] == 0.5
    assert first["keyword_coverage"] == 0.5
    assert first["duplicate_ratio"] == 0.5


async def test_agent_templates_catalog_and_create(client, api, registry):
    headers = await api.headers("p11s10-templates@example.com")
    catalog = await client.get("/workflows/catalog?kind=agent", headers=headers)
    assert catalog.status_code == 200, catalog.text
    template_ids = {item["id"] for item in catalog.json()["templates"]}
    assert {"assistant", "research", "reviewed"} <= template_ids

    created = await client.post(
        "/agents/from-template",
        json={
            "template": "research",
            "name": "Research from template",
            "description": "Template-created agent",
            "provider_id": "fake",
            "model": "fake-model",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["workflow_id"] is not None