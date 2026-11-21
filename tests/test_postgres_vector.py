import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

TEST_POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not TEST_POSTGRES_URL, reason="TEST_POSTGRES_URL not set; skipping pgvector integration"
)


async def test_pgvector_stores_1024_dimensions_and_orders_by_l2_distance():
    from app.models import Base, Chunk, ChunkEmbedding, Document, KnowledgeBase, User

    engine = create_async_engine(TEST_POSTGRES_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            user = User(email=f"{uuid4()}@pgvector.test", password_hash="x")
            session.add(user)
            await session.flush()
            kb = KnowledgeBase(user_id=user.id, name="kb")
            session.add(kb)
            await session.flush()
            document = Document(
                kb_id=kb.id,
                user_id=user.id,
                filename="a.txt",
                mime="text/plain",
                size_bytes=1,
                content_hash="hash",
                status="ready",
                storage_path="a.txt",
            )
            session.add(document)
            await session.flush()
            first = Chunk(
                document_id=document.id,
                user_id=user.id,
                kb_id=kb.id,
                page_no=1,
                chunk_index=0,
                text="first",
            )
            second = Chunk(
                document_id=document.id,
                user_id=user.id,
                kb_id=kb.id,
                page_no=1,
                chunk_index=1,
                text="second",
            )
            session.add_all([first, second])
            await session.flush()
            session.add_all(
                [
                    ChunkEmbedding(chunk_id=first.id, embedding=[0.0] * 1023 + [1.0]),
                    ChunkEmbedding(chunk_id=second.id, embedding=[1.0] + [0.0] * 1023),
                ]
            )
            await session.commit()

            nearest = (
                await session.execute(
                    select(ChunkEmbedding.chunk_id)
                    .order_by(ChunkEmbedding.embedding.l2_distance([0.0] * 1023 + [1.0]))
                    .limit(1)
                )
            ).scalar_one()
            dimensions = (
                await session.execute(
                    text("SELECT vector_dims(embedding) FROM chunk_embeddings LIMIT 1")
                )
            ).scalar_one()

            assert nearest == first.id
            assert dimensions == 1024

            await session.execute(
                text("TRUNCATE chunk_embeddings, chunks, documents, knowledge_bases, users CASCADE")
            )
            await session.commit()
    finally:
        await engine.dispose()
