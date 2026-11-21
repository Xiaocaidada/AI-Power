from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.db import SessionLocal
from app.models import Chunk, ChunkEmbedding, Document, KnowledgeBase, User


def _vector(position: int) -> list[float]:
    vector = [0.0] * 1024
    vector[position] = 1.0
    return vector


async def _seed_owner(session, email: str, kb_name: str = "KB"):
    user = User(email=email, password_hash="x")
    session.add(user)
    await session.flush()
    kb = KnowledgeBase(user_id=user.id, name=kb_name)
    session.add(kb)
    await session.flush()
    return user, kb


async def _seed_chunk(
    session,
    *,
    user: User,
    kb: KnowledgeBase,
    text: str,
    vector: list[float],
    index: int = 0,
    filename: str = "note.txt",
    status: str = "ready",
    deleted_at=None,
) -> tuple[Chunk, Document]:
    document = Document(
        kb_id=kb.id,
        user_id=user.id,
        filename=filename,
        mime="text/plain",
        size_bytes=1,
        content_hash=uuid4().hex,
        storage_path="note.txt",
        status=status,
        deleted_at=deleted_at,
    )
    session.add(document)
    await session.flush()
    chunk = Chunk(
        document_id=document.id,
        user_id=user.id,
        kb_id=kb.id,
        page_no=1,
        chunk_index=index,
        text=text,
    )
    session.add(chunk)
    await session.flush()
    session.add(ChunkEmbedding(chunk_id=chunk.id, embedding=vector))
    await session.flush()
    return chunk, document


async def test_search_orders_by_distance_and_limits_top_k(keyword_embedder):
    from app.services.retrieval import retrieve_chunks

    keyword_embedder.mapping = {"alpha": 0, "beta": 1}
    async with SessionLocal() as session:
        user, kb = await _seed_owner(session, "search-order@example.com")
        far, _ = await _seed_chunk(
            session, user=user, kb=kb, text="beta text", vector=_vector(1), index=0
        )
        near, _ = await _seed_chunk(
            session, user=user, kb=kb, text="alpha text", vector=_vector(0), index=1
        )
        await session.commit()

        results = await retrieve_chunks(
            session, user_id=user.id, kb_id=kb.id, query="alpha?", embedder=keyword_embedder
        )

        assert [result.chunk_id for result in results] == [near.id, far.id]
        assert results[0].distance == pytest.approx(0.0)
        assert results[1].distance == pytest.approx(2**0.5)
        assert keyword_embedder.calls == [["alpha?"]]

        limited = await retrieve_chunks(
            session,
            user_id=user.id,
            kb_id=kb.id,
            query="alpha?",
            top_k=1,
            embedder=keyword_embedder,
        )
        assert [result.chunk_id for result in limited] == [near.id]


async def test_search_filters_by_user_and_knowledge_base(keyword_embedder):
    from app.services.retrieval import retrieve_chunks

    async with SessionLocal() as session:
        alice, alice_kb = await _seed_owner(session, "search-alice@example.com", "Alice KB")
        alice_other_kb = KnowledgeBase(user_id=alice.id, name="Other KB")
        session.add(alice_other_kb)
        await session.flush()
        bob, bob_kb = await _seed_owner(session, "search-bob@example.com", "Bob KB")
        await _seed_chunk(session, user=alice, kb=alice_kb, text="wanted", vector=_vector(0))
        await _seed_chunk(
            session, user=alice, kb=alice_other_kb, text="other kb", vector=_vector(0)
        )
        await _seed_chunk(session, user=bob, kb=bob_kb, text="other user", vector=_vector(0))
        await session.commit()

        results = await retrieve_chunks(
            session, user_id=alice.id, kb_id=alice_kb.id, query="wanted", embedder=keyword_embedder
        )

        assert [result.text for result in results] == ["wanted"]


async def test_search_excludes_documents_that_are_not_ready_or_deleted(keyword_embedder):
    from app.services.retrieval import retrieve_chunks

    async with SessionLocal() as session:
        user, kb = await _seed_owner(session, "search-status@example.com")
        await _seed_chunk(session, user=user, kb=kb, text="ready", vector=_vector(0), index=0)
        await _seed_chunk(
            session, user=user, kb=kb, text="failed", vector=_vector(0), index=1, status="failed"
        )
        await _seed_chunk(
            session,
            user=user,
            kb=kb,
            text="deleted",
            vector=_vector(0),
            index=2,
            deleted_at=user.created_at,
        )
        await session.commit()

        results = await retrieve_chunks(
            session, user_id=user.id, kb_id=kb.id, query="ready", embedder=keyword_embedder
        )

        assert [result.text for result in results] == ["ready"]


async def test_search_returns_empty_when_knowledge_base_has_no_chunks(keyword_embedder):
    from app.services.retrieval import retrieve_chunks

    async with SessionLocal() as session:
        user, kb = await _seed_owner(session, "search-empty@example.com")
        await session.commit()

        results = await retrieve_chunks(
            session, user_id=user.id, kb_id=kb.id, query="anything", embedder=keyword_embedder
        )

        assert results == []


async def test_search_returns_empty_for_blank_query_without_embedding(keyword_embedder):
    from app.services.retrieval import retrieve_chunks

    async with SessionLocal() as session:
        user, kb = await _seed_owner(session, "search-blank@example.com")

        results = await retrieve_chunks(
            session, user_id=user.id, kb_id=kb.id, query="   ", embedder=keyword_embedder
        )

        assert results == []
        assert keyword_embedder.calls == []


async def test_search_rejects_embedder_returning_missing_query_vector(keyword_embedder):
    from app.providers.base import ProviderError
    from app.services.retrieval import retrieve_chunks

    class EmptyEmbedder:
        async def embed(self, texts):
            return []

    async with SessionLocal() as session:
        user, kb = await _seed_owner(session, "search-missing-vector@example.com")
        with pytest.raises(ProviderError) as excinfo:
            await retrieve_chunks(
                session,
                user_id=user.id,
                kb_id=kb.id,
                query="anything",
                embedder=EmptyEmbedder(),
            )

        assert excinfo.value.code == "embedding_bad_response"


async def test_l2_distance_rejects_dimension_mismatch():
    from app.services.retrieval import _l2_distance

    with pytest.raises(ValueError):
        _l2_distance([0.0, 1.0], [0.0])


def test_build_embedder_uses_configured_endpoint():
    from app.config import get_settings
    from app.services.embedding_factory import build_embedder

    settings = get_settings()
    embedder = build_embedder()

    assert embedder.base_url == settings.embedding_base_url.rstrip("/")
    assert embedder.model == settings.embedding_model
    assert embedder.dimensions == settings.embedding_dim


async def test_search_rejects_non_positive_top_k(keyword_embedder):
    from app.services.retrieval import retrieve_chunks

    async with SessionLocal() as session:
        user, kb = await _seed_owner(session, "search-topk@example.com")
        with pytest.raises(ValueError):
            await retrieve_chunks(
                session,
                user_id=user.id,
                kb_id=kb.id,
                query="anything",
                top_k=0,
                embedder=keyword_embedder,
            )


async def test_search_propagates_embedding_provider_errors():
    from app.providers.base import ProviderError
    from app.services.retrieval import retrieve_chunks

    class FailingEmbedder:
        async def embed(self, texts):
            raise ProviderError("embedding_unreachable", "down")

    async with SessionLocal() as session:
        user, kb = await _seed_owner(session, "search-fail@example.com")
        with pytest.raises(ProviderError) as excinfo:
            await retrieve_chunks(
                session,
                user_id=user.id,
                kb_id=kb.id,
                query="anything",
                embedder=FailingEmbedder(),
            )

        assert excinfo.value.code == "embedding_unreachable"


async def test_build_citations_numbers_from_one_with_real_chunk_ids():
    from app.services.retrieval import RetrievedChunk, build_citations

    first = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="handbook.pdf",
        page_no=2,
        chunk_index=0,
        text="line one\n\nline two",
        distance=0.1,
    )
    second = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="notes.txt",
        page_no=None,
        chunk_index=1,
        text="x" * 300,
        distance=0.2,
    )

    citations = build_citations([first, second])

    assert [citation.index for citation in citations] == [1, 2]
    assert [citation.chunk_id for citation in citations] == [first.chunk_id, second.chunk_id]
    assert [citation.document_id for citation in citations] == [
        first.document_id,
        second.document_id,
    ]
    assert citations[0].snippet == "line one line two"
    assert citations[0].page_no == 2
    assert len(citations[1].snippet) == 240
    assert citations[1].snippet.endswith("…")


async def test_fit_context_keeps_rank_order_within_budget():
    from app.services.rag import fit_context
    from app.services.retrieval import RetrievedChunk

    def chunk(text: str, distance: float) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=uuid4(),
            document_id=uuid4(),
            filename="a.txt",
            page_no=1,
            chunk_index=0,
            text=text,
            distance=distance,
        )

    chunks = [chunk("a" * 100, 0.1), chunk("b" * 100, 0.2), chunk("c" * 100, 0.3)]

    kept = fit_context(chunks, 250)

    assert [item.text for item in kept] == ["a" * 100, "b" * 100]


async def test_fit_context_truncates_oversized_first_chunk():
    from app.services.rag import fit_context
    from app.services.retrieval import RetrievedChunk

    oversized = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="a.txt",
        page_no=1,
        chunk_index=0,
        text="a" * 100,
        distance=0.1,
    )

    kept = fit_context([oversized], 50)

    assert len(kept) == 1
    assert kept[0].text == "a" * 50
    assert kept[0].chunk_id == oversized.chunk_id


async def test_rag_messages_place_untrusted_references_before_history():
    from app.providers.base import ChatMessage
    from app.services.rag import build_rag_messages
    from app.services.retrieval import RetrievedChunk

    chunk = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="handbook.pdf",
        page_no=3,
        chunk_index=0,
        text="Refunds take 5 days.",
        distance=0.1,
    )

    messages = build_rag_messages([chunk], [ChatMessage(role="user", content="How long?")])

    assert messages[0].role == "system"
    assert "<reference_material>" in messages[0].content
    assert "untrusted DATA" in messages[0].content
    assert "[1] (handbook.pdf, page 3)" in messages[0].content
    assert "Refunds take 5 days." in messages[0].content
    assert messages[1:] == [ChatMessage(role="user", content="How long?")]


async def test_fit_context_rejects_non_positive_budget():
    from app.services.rag import fit_context

    with pytest.raises(ValueError):
        fit_context([], 0)


async def test_rag_messages_reference_without_page_number():
    from app.providers.base import ChatMessage
    from app.services.rag import build_rag_messages
    from app.services.retrieval import RetrievedChunk

    chunk = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        filename="notes.txt",
        page_no=None,
        chunk_index=0,
        text="Plain text reference.",
        distance=0.1,
    )

    messages = build_rag_messages([chunk], [ChatMessage(role="user", content="Hi")])

    assert "[1] (notes.txt)" in messages[0].content


async def test_rag_messages_without_chunks_declare_missing_context():
    from app.providers.base import ChatMessage
    from app.services.rag import build_rag_messages

    messages = build_rag_messages([], [ChatMessage(role="user", content="Hi")])

    assert messages[0].role == "system"
    assert "No reference material" in messages[0].content
    assert messages[1:] == [ChatMessage(role="user", content="Hi")]


def test_hnsw_index_sql_uses_l2_operator_class():
    from app.db import CHUNK_EMBEDDING_HNSW_INDEX_SQL

    assert "USING hnsw" in CHUNK_EMBEDDING_HNSW_INDEX_SQL
    assert "vector_l2_ops" in CHUNK_EMBEDDING_HNSW_INDEX_SQL
    assert "IF NOT EXISTS" in CHUNK_EMBEDDING_HNSW_INDEX_SQL


def test_retrieval_settings_must_be_positive():
    with pytest.raises(ValidationError):
        Settings(retrieval_top_k=0)

    with pytest.raises(ValidationError):
        Settings(retrieval_max_context_chars=0)
