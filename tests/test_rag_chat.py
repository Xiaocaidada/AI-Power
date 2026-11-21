import json
from uuid import UUID

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Chunk, ChunkEmbedding, Document, User


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        event = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data = json.loads(
            next(line[len("data: ") :] for line in lines if line.startswith("data: "))
        )
        events.append((event, data))
    return events


async def _create_kb(client, headers, name="RAG KB"):
    return await client.post("/knowledge-bases", json={"name": name}, headers=headers)


async def _upload(client, headers, kb_id, filename="note.txt", content=b"hello world"):
    return await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": (filename, content, "text/plain")},
        headers=headers,
    )


async def _create_conversation(client, headers, kb_id=None):
    payload: dict[str, object] = {"provider_id": "fake", "model": "fake-model"}
    if kb_id is not None:
        payload["kb_id"] = kb_id
    return await client.post("/conversations", json=payload, headers=headers)


async def _send(client, headers, conversation_id, content="hello?"):
    return await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": content},
        headers=headers,
    )


async def _single_chunk() -> Chunk:
    async with SessionLocal() as session:
        return (await session.execute(select(Chunk))).scalars().first()


async def test_rag_conversation_emits_citations_for_retrieved_chunks(
    client, api, registry, fake_provider, fake_ingestion, fake_retrieval
):
    headers = await api.headers("rag-cite@example.com")
    kb = await _create_kb(client, headers)
    await _upload(client, headers, kb.json()["id"])
    conversation = await _create_conversation(client, headers, kb.json()["id"])

    response = await _send(client, headers, conversation.json()["id"], "hello?")

    events = _parse_sse(response.text)
    assert [event for event, _ in events] == [
        "meta",
        "citation",
        "delta",
        "delta",
        "usage",
        "done",
    ]
    citation = events[1][1]
    chunk = await _single_chunk()
    assert chunk is not None
    assert citation["index"] == 1
    assert citation["chunk_id"] == str(chunk.id)
    assert citation["document_id"] == str(chunk.document_id)
    assert citation["page_no"] == 1
    assert citation["snippet"] == "hello world"
    assert set(citation) == {"index", "document_id", "chunk_id", "page_no", "snippet"}

    detail = await client.get(f"/conversations/{conversation.json()['id']}", headers=headers)
    assistant_message = detail.json()["messages"][1]
    assert assistant_message["citations"] == [citation]


async def test_rag_system_prompt_contains_reference_and_injection_guard(
    client, api, registry, fake_provider, fake_ingestion, fake_retrieval
):
    headers = await api.headers("rag-prompt@example.com")
    kb = await _create_kb(client, headers)
    await _upload(client, headers, kb.json()["id"])
    conversation = await _create_conversation(client, headers, kb.json()["id"])

    await _send(client, headers, conversation.json()["id"], "hello?")

    messages, _ = fake_provider.calls[-1]
    assert messages[0].role == "system"
    assert "<reference_material>" in messages[0].content
    assert "untrusted DATA" in messages[0].content
    assert "hello world" in messages[0].content
    assert messages[-1].role == "user"
    assert messages[-1].content == "hello?"


async def test_rag_only_cites_chunks_from_conversation_kb(
    client, api, registry, fake_provider, fake_ingestion, fake_retrieval
):
    from app.services.parsing import ParsedPage

    headers = await api.headers("rag-scope@example.com")
    first_kb = await _create_kb(client, headers, "First KB")
    await _upload(client, headers, first_kb.json()["id"])
    second_kb = await _create_kb(client, headers, "Second KB")
    fake_ingestion.parser.pages = [ParsedPage(page_no=1, text="other secret")]
    await _upload(client, headers, second_kb.json()["id"], filename="other.txt")
    conversation = await _create_conversation(client, headers, first_kb.json()["id"])

    response = await _send(client, headers, conversation.json()["id"], "hello?")

    citations = [data for event, data in _parse_sse(response.text) if event == "citation"]
    assert [citation["snippet"] for citation in citations] == ["hello world"]


async def test_plain_conversation_has_no_citations(client, api, registry, fake_provider):
    headers = await api.headers("rag-plain@example.com")
    conversation = await _create_conversation(client, headers)

    response = await _send(client, headers, conversation.json()["id"])

    events = _parse_sse(response.text)
    assert [event for event, _ in events] == ["meta", "delta", "delta", "usage", "done"]
    messages, _ = fake_provider.calls[-1]
    assert messages[0].role == "user"

    detail = await client.get(f"/conversations/{conversation.json()['id']}", headers=headers)
    assistant_message = detail.json()["messages"][1]
    assert assistant_message["citations"] == []


async def test_rag_retrieval_failure_returns_502_before_persisting(
    client, api, registry, fake_provider, fake_ingestion, fake_retrieval, monkeypatch
):
    import app.routers.conversations as conversations
    from app.providers.base import ProviderError

    async def boom(*_args, **_kwargs):
        raise ProviderError("embedding_unreachable", "down")

    monkeypatch.setattr(conversations, "retrieve_chunks", boom)
    headers = await api.headers("rag-failure@example.com")
    kb = await _create_kb(client, headers)
    await _upload(client, headers, kb.json()["id"])
    conversation = await _create_conversation(client, headers, kb.json()["id"])

    response = await _send(client, headers, conversation.json()["id"])

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert detail["code"] == "retrieval_failed"
    assert fake_provider.calls == []
    detail_response = await client.get(
        f"/conversations/{conversation.json()['id']}", headers=headers
    )
    assert detail_response.json()["messages"] == []


async def test_rag_empty_knowledge_base_streams_without_citations(
    client, api, registry, fake_provider, fake_ingestion, fake_retrieval
):
    headers = await api.headers("rag-empty@example.com")
    kb = await _create_kb(client, headers)
    conversation = await _create_conversation(client, headers, kb.json()["id"])

    response = await _send(client, headers, conversation.json()["id"])

    events = _parse_sse(response.text)
    assert [event for event, _ in events] == ["meta", "delta", "delta", "usage", "done"]
    messages, _ = fake_provider.calls[-1]
    assert "No reference material" in messages[0].content


async def test_rag_never_cites_chunks_owned_by_another_user(
    client, api, registry, fake_provider, fake_ingestion, fake_retrieval
):
    alice = await api.headers("rag-isolation-alice@example.com")
    bob = await api.headers("rag-isolation-bob@example.com")
    me = await client.get("/auth/me", headers=bob)
    bob_id = UUID(me.json()["id"])
    kb = await _create_kb(client, alice)
    await _upload(client, alice, kb.json()["id"])
    conversation = await _create_conversation(client, alice, kb.json()["id"])

    async with SessionLocal() as session:
        bob_user = await session.get(User, bob_id)
        assert bob_user is not None
        foreign_document = Document(
            kb_id=UUID(kb.json()["id"]),
            user_id=bob_id,
            filename="bob.txt",
            mime="text/plain",
            size_bytes=1,
            content_hash="bob-hash",
            storage_path="bob.txt",
            status="ready",
        )
        session.add(foreign_document)
        await session.flush()
        foreign_chunk = Chunk(
            document_id=foreign_document.id,
            user_id=bob_id,
            kb_id=UUID(kb.json()["id"]),
            page_no=1,
            chunk_index=0,
            text="bob secret",
        )
        session.add(foreign_chunk)
        await session.flush()
        session.add(ChunkEmbedding(chunk_id=foreign_chunk.id, embedding=[0.0] * 1024))
        await session.commit()

    response = await _send(client, alice, conversation.json()["id"], "secret")

    citations = [data for event, data in _parse_sse(response.text) if event == "citation"]
    assert [citation["snippet"] for citation in citations] == ["hello world"]
