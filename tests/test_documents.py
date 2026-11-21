from types import SimpleNamespace
from uuid import UUID


async def _create_kb(client, headers, name="Docs KB"):
    return await client.post("/knowledge-bases", json={"name": name}, headers=headers)


async def _upload(
    client,
    headers,
    kb_id,
    filename="note.txt",
    content=b"hello world",
    content_type="text/plain",
):
    return await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": (filename, content, content_type)},
        headers=headers,
    )


async def _count_rows(model):
    from sqlalchemy import func, select

    from app.db import SessionLocal

    async with SessionLocal() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_upload_requires_auth(client):
    response = await client.post("/knowledge-bases/00000000-0000-0000-0000-000000000000/documents")

    assert response.status_code == 401


async def test_upload_to_foreign_knowledge_base_returns_404(client, api, fake_ingestion):
    alice = await api.headers("kb-alice@example.com")
    bob = await api.headers("kb-bob@example.com")
    kb = await _create_kb(client, alice)

    response = await _upload(client, bob, kb.json()["id"])

    assert response.status_code == 404


async def test_upload_rejects_unsupported_extension(client, api, fake_ingestion):
    headers = await api.headers("bad-ext@example.com")
    kb = await _create_kb(client, headers)

    response = await _upload(client, headers, kb.json()["id"], filename="evil.exe")

    assert response.status_code == 415


async def test_upload_ingests_and_marks_ready(client, api, fake_ingestion):
    from app.models import Chunk, ChunkEmbedding

    headers = await api.headers("upload@example.com")
    kb = await _create_kb(client, headers)

    response = await _upload(client, headers, kb.json()["id"])

    assert response.status_code == 202
    document_id = response.json()["id"]
    detail = await client.get(f"/documents/{document_id}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "ready"
    assert body["page_count"] == 1
    assert "storage_path" not in body
    assert await _count_rows(Chunk) == 1
    assert await _count_rows(ChunkEmbedding) == 1


async def test_duplicate_upload_reuses_existing_document(client, api, fake_ingestion):
    from app.models import Chunk

    headers = await api.headers("duplicate@example.com")
    kb = await _create_kb(client, headers)

    first = await _upload(client, headers, kb.json()["id"])
    second = await _upload(client, headers, kb.json()["id"])

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["id"] == first.json()["id"]
    assert await _count_rows(Chunk) == 1


async def test_get_other_users_document_returns_404(client, api, fake_ingestion):
    alice = await api.headers("doc-alice@example.com")
    bob = await api.headers("doc-bob@example.com")
    kb = await _create_kb(client, alice)
    created = await _upload(client, alice, kb.json()["id"])

    response = await client.get(f"/documents/{created.json()['id']}", headers=bob)

    assert response.status_code == 404


async def test_delete_other_users_document_returns_404(client, api, fake_ingestion):
    alice = await api.headers("del-alice@example.com")
    bob = await api.headers("del-bob@example.com")
    kb = await _create_kb(client, alice)
    created = await _upload(client, alice, kb.json()["id"])

    response = await client.delete(f"/documents/{created.json()['id']}", headers=bob)

    assert response.status_code == 404


async def test_owner_can_delete_document_and_chunks(client, api, fake_ingestion):
    from app.models import Chunk, ChunkEmbedding

    headers = await api.headers("delete@example.com")
    kb = await _create_kb(client, headers)
    created = await _upload(client, headers, kb.json()["id"])
    document_id = created.json()["id"]

    deleted = await client.delete(f"/documents/{document_id}", headers=headers)
    fetched = await client.get(f"/documents/{document_id}", headers=headers)

    assert deleted.status_code == 204
    assert fetched.status_code == 404
    assert await _count_rows(Chunk) == 0
    assert await _count_rows(ChunkEmbedding) == 0


async def test_parser_failure_marks_document_failed(client, api, fake_ingestion):
    fake_ingestion.parser.error = RuntimeError("bad document")
    headers = await api.headers("parse-fail@example.com")
    kb = await _create_kb(client, headers)

    response = await _upload(client, headers, kb.json()["id"])

    detail = await client.get(f"/documents/{response.json()['id']}", headers=headers)
    assert detail.json()["status"] == "failed"
    assert detail.json()["error_code"] == "parse_failed"


async def test_embedder_failure_marks_document_failed(client, api, fake_ingestion):
    from app.providers.base import ProviderError

    fake_ingestion.embedder.error = ProviderError("embedding_http_error", "down")
    headers = await api.headers("embed-fail@example.com")
    kb = await _create_kb(client, headers)

    response = await _upload(client, headers, kb.json()["id"])

    detail = await client.get(f"/documents/{response.json()['id']}", headers=headers)
    assert detail.json()["status"] == "failed"
    assert detail.json()["error_code"] == "embedding_failed"


async def test_page_limit_marks_document_failed(client, api, fake_ingestion):
    from app.services.parsing import ParsedPage

    fake_ingestion.parser.pages = [ParsedPage(page_no=index + 1, text="x") for index in range(201)]
    headers = await api.headers("pages@example.com")
    kb = await _create_kb(client, headers)

    response = await _upload(client, headers, kb.json()["id"])

    detail = await client.get(f"/documents/{response.json()['id']}", headers=headers)
    assert detail.json()["status"] == "failed"
    assert detail.json()["error_code"] == "too_many_pages"


async def test_empty_upload_is_rejected(client, api, fake_ingestion):
    headers = await api.headers("empty@example.com")
    kb = await _create_kb(client, headers)

    response = await _upload(client, headers, kb.json()["id"], content=b"")

    assert response.status_code == 400


async def test_oversize_upload_is_rejected(client, api, fake_ingestion, monkeypatch):
    import app.routers.documents as documents_module

    real = documents_module.get_settings()
    monkeypatch.setattr(
        documents_module,
        "get_settings",
        lambda: SimpleNamespace(upload_dir=real.upload_dir, max_upload_bytes=10),
    )
    headers = await api.headers("oversize@example.com")
    kb = await _create_kb(client, headers)

    response = await _upload(client, headers, kb.json()["id"], content=b"x" * 11)

    assert response.status_code == 413


async def test_storage_path_is_not_exposed_and_uses_uuid_name(client, api, fake_ingestion):
    from app.db import SessionLocal
    from app.models import Document

    headers = await api.headers("storage@example.com")
    kb = await _create_kb(client, headers)
    created = await _upload(client, headers, kb.json()["id"], filename="note.txt")

    async with SessionLocal() as session:
        document = await session.get(Document, UUID(created.json()["id"]))
    assert document is not None
    assert "note.txt" not in document.storage_path
    assert document.storage_path.endswith(".txt")


async def test_upload_enqueues_ingestion(client, api, fake_ingestion, fake_queue):
    headers = await api.headers("enqueue@example.com")
    kb = await _create_kb(client, headers)

    created = await _upload(client, headers, kb.json()["id"])

    assert created.status_code == 202
    assert fake_queue.calls == [UUID(created.json()["id"])]


async def test_retry_failed_document_reingests(client, api, fake_ingestion, fake_queue):
    fake_ingestion.parser.error = RuntimeError("bad document")
    headers = await api.headers("retry@example.com")
    kb = await _create_kb(client, headers)
    created = await _upload(client, headers, kb.json()["id"])
    document_id = created.json()["id"]
    failed = await client.get(f"/documents/{document_id}", headers=headers)
    assert failed.json()["status"] == "failed"

    fake_ingestion.parser.error = None
    retry = await client.post(f"/documents/{document_id}/retry", headers=headers)

    assert retry.status_code == 202
    detail = await client.get(f"/documents/{document_id}", headers=headers)
    assert detail.json()["status"] == "ready"
    assert detail.json()["error_code"] is None
    assert fake_queue.calls == [UUID(document_id), UUID(document_id)]
    assert fake_queue.unique_flags == [False, True]


async def test_retry_ready_document_returns_409(client, api, fake_ingestion):
    headers = await api.headers("retry-ready@example.com")
    kb = await _create_kb(client, headers)
    created = await _upload(client, headers, kb.json()["id"])

    response = await client.post(f"/documents/{created.json()['id']}/retry", headers=headers)

    assert response.status_code == 409


async def test_delete_removes_stored_file(client, api, fake_ingestion):
    from pathlib import Path

    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import Document

    headers = await api.headers("delete-file@example.com")
    kb = await _create_kb(client, headers)
    created = await _upload(client, headers, kb.json()["id"])
    document_id = created.json()["id"]

    async with SessionLocal() as session:
        document = await session.get(Document, UUID(document_id))
        stored_path = Path(get_settings().upload_dir) / document.storage_path
    assert stored_path.exists()

    deleted = await client.delete(f"/documents/{document_id}", headers=headers)

    assert deleted.status_code == 204
    assert not stored_path.exists()


async def test_upload_marks_failed_when_queue_unavailable(client, api, fake_ingestion, fake_queue):
    fake_queue.fail = True
    headers = await api.headers("queue-down@example.com")
    kb = await _create_kb(client, headers)

    response = await _upload(client, headers, kb.json()["id"])

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "queue_unavailable"
    fetched = await client.get(f"/documents/{detail['document_id']}", headers=headers)
    assert fetched.json()["status"] == "failed"
    assert fetched.json()["error_code"] == "queue_unavailable"
