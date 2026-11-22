import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TEST_POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not TEST_POSTGRES_URL,
    reason="TEST_POSTGRES_URL not set; skipping pgvector retrieval integration",
)


def _vector(position: int) -> list[float]:
    vector = [0.0] * 1024
    vector[position] = 1.0
    return vector


async def test_hnsw_and_trigram_indexes_are_created_idempotently():
    from app.db import CHUNK_EMBEDDING_HNSW_INDEX_SQL, CHUNK_TEXT_TRGM_INDEX_SQL
    from app.models import Base

    engine = create_async_engine(TEST_POSTGRES_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text(CHUNK_EMBEDDING_HNSW_INDEX_SQL))
            await conn.execute(text(CHUNK_EMBEDDING_HNSW_INDEX_SQL))
            await conn.execute(text(CHUNK_TEXT_TRGM_INDEX_SQL))
            await conn.execute(text(CHUNK_TEXT_TRGM_INDEX_SQL))
            rows = (
                await conn.execute(
                    text(
                        "SELECT indexname, indexdef FROM pg_indexes "
                        "WHERE indexname IN "
                        "('ix_chunk_embeddings_embedding_hnsw', 'ix_chunks_text_trgm')"
                    )
                )
            ).all()
        indexes = {name: definition for name, definition in rows}
        assert "hnsw" in indexes["ix_chunk_embeddings_embedding_hnsw"].lower()
        assert "vector_l2_ops" in indexes["ix_chunk_embeddings_embedding_hnsw"]
        assert "gin" in indexes["ix_chunks_text_trgm"].lower()
        assert "gin_trgm_ops" in indexes["ix_chunks_text_trgm"]
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def test_retrieval_uses_pgvector_ordering_and_filters():
    from app.models import Base, ChunkEmbedding, KnowledgeBase, User, Workspace
    from app.services.retrieval import retrieve_chunks

    class QueryEmbedder:
        async def embed(self, texts):
            return [_vector(0) for _ in texts]

    engine = create_async_engine(TEST_POSTGRES_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text(_HNSW_SQL))

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            user = User(email=f"{uuid4()}@retrieval.test", password_hash="x")
            session.add(user)
            await session.flush()
            workspace = Workspace(name="kb", plan="free", is_personal=False)
            session.add(workspace)
            await session.flush()
            kb = KnowledgeBase(workspace_id=workspace.id, user_id=user.id, name="kb")
            other_kb = KnowledgeBase(workspace_id=workspace.id, user_id=user.id, name="other")
            session.add_all([kb, other_kb])
            await session.flush()
            near_document = _document(kb, user, "near.txt")
            far_document = _document(kb, user, "far.txt")
            other_document = _document(other_kb, user, "other.txt")
            session.add_all([near_document, far_document, other_document])
            await session.flush()
            near = _chunk(near_document, user, kb, "near", 0)
            far = _chunk(far_document, user, kb, "far", 0)
            other = _chunk(other_document, user, other_kb, "other kb", 0)
            session.add_all([near, far, other])
            await session.flush()
            session.add_all(
                [
                    ChunkEmbedding(chunk_id=near.id, embedding=_vector(0)),
                    ChunkEmbedding(chunk_id=far.id, embedding=_vector(1)),
                    ChunkEmbedding(chunk_id=other.id, embedding=_vector(0)),
                ]
            )
            await session.commit()

            results = await retrieve_chunks(
                session,
                workspace_id=kb.workspace_id,
                kb_id=kb.id,
                query="anything",
                embedder=QueryEmbedder(),
            )

            assert [result.text for result in results] == ["near", "far"]
            assert results[0].distance == pytest.approx(0.0)
            assert results[1].distance == pytest.approx(2**0.5)

            await session.execute(
                text("TRUNCATE chunk_embeddings, chunks, documents, knowledge_bases, users CASCADE")
            )
            await session.commit()
    finally:
        await engine.dispose()


async def test_hybrid_search_uses_pg_trgm_lexical_candidates():
    from app.models import Base, ChunkEmbedding, KnowledgeBase, User, Workspace
    from app.services.retrieval import retrieve_chunks

    class ZeroEmbedder:
        async def embed(self, texts):
            return [_vector(0) for _ in texts]

    engine = create_async_engine(TEST_POSTGRES_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text(_HNSW_SQL))

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            user = User(email=f"{uuid4()}@hybrid.test", password_hash="x")
            session.add(user)
            await session.flush()
            workspace = Workspace(name="kb", plan="free", is_personal=False)
            session.add(workspace)
            await session.flush()
            kb = KnowledgeBase(workspace_id=workspace.id, user_id=user.id, name="kb")
            session.add(kb)
            await session.flush()
            alpha_document = _document(kb, user, "alpha.txt")
            refund_document = _document(kb, user, "refund.txt")
            session.add_all([alpha_document, refund_document])
            await session.flush()
            alpha = _chunk(alpha_document, user, kb, "alpha only", 0)
            refund = _chunk(refund_document, user, kb, "退款 3 个工作日到账", 1)
            session.add_all([alpha, refund])
            await session.flush()
            session.add_all(
                [
                    ChunkEmbedding(chunk_id=alpha.id, embedding=_vector(0)),
                    ChunkEmbedding(chunk_id=refund.id, embedding=_vector(0)),
                ]
            )
            await session.commit()

            results = await retrieve_chunks(
                session,
                workspace_id=kb.workspace_id,
                kb_id=kb.id,
                query="退款多久到账",
                embedder=ZeroEmbedder(),
            )

            assert results[0].text == "退款 3 个工作日到账"
            assert results[0].lexical_rank == 1
            assert results[0].vector_rank == 2
    finally:
        await engine.dispose()


def _document(kb, user, filename: str):
    from app.models import Document

    return Document(
        workspace_id=kb.workspace_id,
        kb_id=kb.id,
        user_id=user.id,
        filename=filename,
        mime="text/plain",
        size_bytes=1,
        content_hash=uuid4().hex,
        storage_path=filename,
        status="ready",
    )


def _chunk(document, user, kb, text: str, index: int):
    from app.models import Chunk

    return Chunk(
        workspace_id=kb.workspace_id,
        document_id=document.id,
        user_id=user.id,
        kb_id=kb.id,
        page_no=1,
        chunk_index=index,
        text=text,
    )


_HNSW_SQL = (
    "CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_embedding_hnsw "
    "ON chunk_embeddings USING hnsw (embedding vector_l2_ops)"
)
