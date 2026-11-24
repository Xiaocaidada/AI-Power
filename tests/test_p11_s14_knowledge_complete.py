from uuid import UUID

from sqlalchemy import func, select

from app.db import SessionLocal
from app.models import Chunk, ChunkEmbedding, Document
from app.services.retrieval import lexical_search_chunks, vector_search_chunks


def _workflow_definition(parse_format: str = "auto", include_ocr: bool = False):
    nodes = [
        {"id": "start", "type": "start", "config": {}},
        {
            "id": "parse",
            "type": "parse_document",
            "config": {"format": parse_format},
        },
    ]
    if include_ocr:
        nodes.append(
            {"id": "ocr", "type": "ocr_document", "config": {"mode": "always"}}
        )
    nodes.extend(
        [
            {"id": "clean", "type": "clean_text", "config": {}},
            {
                "id": "chunk",
                "type": "chunk_text",
                "config": {
                    "strategy": "fixed",
                    "chunk_size": 100,
                    "chunk_overlap": 0,
                },
            },
            {
                "id": "index",
                "type": "index_knowledge",
                "config": {"mode": "fulltext", "require_embeddings": False},
            },
            {"id": "out", "type": "output", "config": {}},
        ]
    )
    ids = [node["id"] for node in nodes]
    return {
        "nodes": nodes,
        "edges": [
            {"from": ids[index - 1], "to": ids[index]}
            for index in range(1, len(ids))
        ],
    }


async def _create_workflow(client, headers, name: str, definition):
    response = await client.post(
        "/workflows",
        json={
            "name": name,
            "kind": "knowledge_process",
            "definition": definition,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _create_kb(client, headers, name: str) -> str:
    response = await client.post(
        "/knowledge-bases", json={"name": name}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _run(client, headers, workflow_id: str, document_id: str) -> dict:
    started = await client.post(
        f"/workflows/{workflow_id}/runs",
        json={"document_id": document_id},
        headers=headers,
    )
    assert started.status_code == 202, started.text
    detail = await client.get(
        f"/workflows/runs/{started.json()['run_id']}", headers=headers
    )
    return detail.json()


async def test_ocr_node_fulltext_index_and_retrieval_filter(
    client, api, fake_ingestion, fake_retrieval, monkeypatch
):
    from app.services import parsing
    from app.services.knowledge import pipeline

    monkeypatch.setattr(parsing, "ocr_ready", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        parsing, "ocr_image", lambda data, mime, *args, **kwargs: "image parsed text"
    )
    monkeypatch.setattr(pipeline, "ocr_ready", lambda: True)
    monkeypatch.setattr(
        pipeline, "ocr_file_text", lambda path, mime: "ocr text from image"
    )

    headers = await api.headers("p11s14-ocr@example.com")
    kb_id = await _create_kb(client, headers, "OCR fulltext")
    uploaded = await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("scan.png", b"fake-image-bytes", "image/png")},
        headers=headers,
    )
    assert uploaded.status_code in {201, 202}, uploaded.text
    document_id = uploaded.json()["id"]

    workflow = await _create_workflow(
        client,
        headers,
        "OCR to fulltext",
        _workflow_definition(include_ocr=True),
    )
    run = await _run(client, headers, workflow["id"], document_id)
    assert run["status"] == "completed", run
    assert run["output_payload"]["index_mode"] == "fulltext"

    applied = await client.post(
        f"/knowledge-bases/{kb_id}/processing/runs/{run['id']}/apply",
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    detail = await client.get(f"/documents/{document_id}", headers=headers)
    assert detail.json()["index_mode"] == "fulltext"

    async with SessionLocal() as session:
        document = await session.get(Document, UUID(document_id))
        assert document is not None
        workspace_id = document.workspace_id
        chunk_rows = list(
            (
                await session.execute(
                    select(Chunk).where(Chunk.document_id == document.id)
                )
            ).scalars()
        )
        assert chunk_rows
        assert "ocr text from image" in chunk_rows[0].text
        embedding_count = (
            await session.execute(
                select(func.count())
                .select_from(ChunkEmbedding)
                .where(
                    ChunkEmbedding.chunk_id.in_([chunk.id for chunk in chunk_rows])
                )
            )
        ).scalar_one()
        assert embedding_count == 0

        lexical = await lexical_search_chunks(
            session,
            workspace_id=workspace_id,
            kb_ids=[UUID(kb_id)],
            query="ocr text",
            top_k=5,
        )
        assert lexical
        vector = await vector_search_chunks(
            session,
            workspace_id=workspace_id,
            kb_ids=[UUID(kb_id)],
            query="ocr text",
            top_k=5,
        )
        assert vector == []


async def test_parse_format_mismatch_is_typed(
    client, api, fake_ingestion
):
    headers = await api.headers("p11s14-format@example.com")
    kb_id = await _create_kb(client, headers, "Format mismatch")
    uploaded = await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("note.txt", b"plain text body", "text/plain")},
        headers=headers,
    )
    assert uploaded.status_code in {201, 202}, uploaded.text
    document_id = uploaded.json()["id"]
    workflow = await _create_workflow(
        client,
        headers,
        "Wrong parser",
        _workflow_definition(parse_format="pdf"),
    )
    run = await _run(client, headers, workflow["id"], document_id)
    assert run["status"] == "failed"
    assert run["error_code"] == "format_mismatch"