from uuid import uuid4

import pytest

from app.db import SessionLocal
from app.models import Chunk, ChunkEmbedding, Document, KnowledgeBase, User, Workspace


def _vector(position: int) -> list[float]:
    vector = [0.0] * 1024
    vector[position] = 1.0
    return vector


async def _seed_owner(session, email: str, kb_name: str = "KB"):
    user = User(email=email, password_hash="x")
    session.add(user)
    await session.flush()
    workspace = Workspace(name=kb_name, plan="free", is_personal=False)
    session.add(workspace)
    await session.flush()
    kb = KnowledgeBase(workspace_id=workspace.id, user_id=user.id, name=kb_name)
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
) -> Chunk:
    document = Document(
        workspace_id=kb.workspace_id,
        kb_id=kb.id,
        user_id=user.id,
        filename=filename,
        mime="text/plain",
        size_bytes=1,
        content_hash=uuid4().hex,
        storage_path="note.txt",
        status="ready",
    )
    session.add(document)
    await session.flush()
    chunk = Chunk(
        workspace_id=kb.workspace_id,
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
    return chunk


def _retrieved(chunk_id, text: str, distance: float):
    from app.services.retrieval import RetrievedChunk

    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=uuid4(),
        filename="note.txt",
        page_no=1,
        chunk_index=0,
        text=text,
        distance=distance,
    )


def test_rrf_fuses_vector_and_lexical_ranks():
    from app.services.retrieval import fuse_rrf

    first = _retrieved(uuid4(), "first", 0.1)
    second = _retrieved(uuid4(), "second", 0.2)
    third = _retrieved(uuid4(), "third", 0.3)

    fused = fuse_rrf([first, second, third], [third])

    assert [item.chunk_id for item in fused] == [
        third.chunk_id,
        first.chunk_id,
        second.chunk_id,
    ]
    assert fused[0].lexical_rank == 1
    assert fused[1].vector_rank == 1
    assert fused[0].fused_score == pytest.approx(1 / 63 + 1 / 61)
    assert fused[1].fused_score == pytest.approx(1 / 61)


async def test_hybrid_search_uses_lexical_match_to_surface_keyword(keyword_embedder):
    from app.services.retrieval import retrieve_chunks

    keyword_embedder.mapping = {"alpha": 0}
    async with SessionLocal() as session:
        user, kb = await _seed_owner(session, "hybrid-keyword@example.com")
        await _seed_chunk(session, user=user, kb=kb, text="alpha text", vector=_vector(0), index=0)
        await _seed_chunk(
            session,
            user=user,
            kb=kb,
            text="退款 3 个工作日到账",
            vector=_vector(1),
            index=1,
        )
        await session.commit()

        results = await retrieve_chunks(
            session,
            workspace_id=kb.workspace_id,
            kb_id=kb.id,
            query="退款",
            embedder=keyword_embedder,
        )

        assert results[0].text == "退款 3 个工作日到账"
        assert results[0].lexical_rank == 1
        assert results[0].vector_rank == 2
        assert results[0].fused_score is not None


async def test_hybrid_can_be_disabled_per_knowledge_base(keyword_embedder):
    from app.services.retrieval import retrieve_chunks

    keyword_embedder.mapping = {"alpha": 0}
    async with SessionLocal() as session:
        user, kb = await _seed_owner(session, "hybrid-off@example.com")
        kb.settings = {
            "retrieval": {
                "hybrid_enabled": False,
                "rerank_enabled": False,
                "top_k": 5,
                "candidate_k": 5,
            }
        }
        await _seed_chunk(session, user=user, kb=kb, text="alpha text", vector=_vector(0), index=0)
        await _seed_chunk(
            session, user=user, kb=kb, text="退款 3 个工作日到账", vector=_vector(1), index=1
        )
        await session.commit()

        results = await retrieve_chunks(
            session,
            workspace_id=kb.workspace_id,
            kb_id=kb.id,
            query="退款",
            embedder=keyword_embedder,
        )

        assert results[0].text == "alpha text"
        assert results[0].lexical_rank is None


async def test_reranker_reorders_candidates_and_records_score(keyword_embedder):
    from app.providers.rerank import RerankResult
    from app.services.retrieval import retrieve_chunks

    class FakeReranker:
        def __init__(self) -> None:
            self.calls: list[tuple[str, list[str], int | None]] = []

        async def rerank(self, query: str, documents: list[str], top_n: int | None = None):
            self.calls.append((query, list(documents), top_n))
            return [RerankResult(index=1, score=0.9), RerankResult(index=0, score=0.1)]

    keyword_embedder.mapping = {"alpha": 0}
    reranker = FakeReranker()
    async with SessionLocal() as session:
        user, kb = await _seed_owner(session, "rerank-order@example.com")
        kb.settings = {
            "retrieval": {
                "hybrid_enabled": False,
                "rerank_enabled": True,
                "top_k": 2,
                "candidate_k": 2,
            }
        }
        await _seed_chunk(
            session, user=user, kb=kb, text="alpha result", vector=_vector(0), index=0
        )
        await _seed_chunk(session, user=user, kb=kb, text="beta result", vector=_vector(1), index=1)
        await session.commit()

        results = await retrieve_chunks(
            session,
            workspace_id=kb.workspace_id,
            kb_id=kb.id,
            query="alpha",
            embedder=keyword_embedder,
            reranker=reranker,
        )

        assert [item.text for item in results] == ["beta result", "alpha result"]
        assert results[0].rerank_score == 0.9
        assert results[1].rerank_score == 0.1
        assert reranker.calls[0][1] == ["alpha result", "beta result"]


async def test_reranker_failure_falls_back_to_fused_order(keyword_embedder):
    from app.providers.base import ProviderError
    from app.services.retrieval import retrieve_chunks

    class FailingReranker:
        async def rerank(self, query: str, documents: list[str], top_n: int | None = None):
            raise ProviderError("rerank_http_error", "down")

    keyword_embedder.mapping = {"alpha": 0}
    async with SessionLocal() as session:
        user, kb = await _seed_owner(session, "rerank-fail@example.com")
        kb.settings = {
            "retrieval": {
                "hybrid_enabled": False,
                "rerank_enabled": True,
                "top_k": 2,
                "candidate_k": 2,
            }
        }
        await _seed_chunk(
            session, user=user, kb=kb, text="alpha result", vector=_vector(0), index=0
        )
        await _seed_chunk(session, user=user, kb=kb, text="beta result", vector=_vector(1), index=1)
        await session.commit()

        results = await retrieve_chunks(
            session,
            workspace_id=kb.workspace_id,
            kb_id=kb.id,
            query="alpha",
            embedder=keyword_embedder,
            reranker=FailingReranker(),
        )

        assert [item.text for item in results] == ["alpha result", "beta result"]
        assert results[0].rerank_score is None


async def test_retrieval_reports_stage_timings(keyword_embedder):
    from app.services.retrieval import retrieve_with_diagnostics

    keyword_embedder.mapping = {"alpha": 0}
    async with SessionLocal() as session:
        user, kb = await _seed_owner(session, "timings@example.com")
        await _seed_chunk(session, user=user, kb=kb, text="alpha text", vector=_vector(0))
        await session.commit()

        outcome = await retrieve_with_diagnostics(
            session,
            workspace_id=kb.workspace_id,
            kb_id=kb.id,
            query="alpha",
            embedder=keyword_embedder,
        )

        assert outcome.chunks[0].text == "alpha text"
        assert set(outcome.timings) == {"vector_ms", "lexical_ms", "rerank_ms", "total_ms"}
        assert outcome.mode == "hybrid"
