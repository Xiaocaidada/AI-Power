from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Chunk, ChunkEmbedding, Document
from app.providers.base import ProviderError
from app.providers.embedding import EmbeddingProvider
from app.services.embedding_factory import build_embedder

SNIPPET_MAX_CHARS = 240
SNIPPET_ELLIPSIS = "…"


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_no: int | None
    chunk_index: int
    text: str
    distance: float


@dataclass(frozen=True, slots=True)
class Citation:
    index: int
    document_id: UUID
    chunk_id: UUID
    page_no: int | None
    snippet: str


async def retrieve_chunks(
    session: AsyncSession,
    *,
    user_id: UUID,
    kb_id: UUID,
    query: str,
    top_k: int | None = None,
    embedder: EmbeddingProvider | None = None,
) -> list[RetrievedChunk]:
    """Nearest chunks for one user's knowledge base, closest first."""
    limit = get_settings().retrieval_top_k if top_k is None else top_k
    if limit < 1:
        raise ValueError("top_k must be >= 1")

    question = query.strip()
    if not question:
        return []

    vectors = await (embedder or build_embedder()).embed([question])
    if len(vectors) != 1:
        raise ProviderError("embedding_bad_response", "Query embedding is missing")
    vector = vectors[0]

    if session.get_bind().dialect.name == "postgresql":
        return await _search_with_distance(session, user_id, kb_id, vector, limit)
    return await _search_in_python(session, user_id, kb_id, vector, limit)


def build_citations(chunks: Sequence[RetrievedChunk]) -> list[Citation]:
    return [
        Citation(
            index=index,
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            page_no=chunk.page_no,
            snippet=_snippet(chunk.text),
        )
        for index, chunk in enumerate(chunks, start=1)
    ]


def _filters(user_id: UUID, kb_id: UUID) -> tuple:
    return (
        Chunk.user_id == user_id,
        Chunk.kb_id == kb_id,
        Document.status == "ready",
        Document.deleted_at.is_(None),
    )


async def _search_with_distance(
    session: AsyncSession,
    user_id: UUID,
    kb_id: UUID,
    vector: list[float],
    limit: int,
) -> list[RetrievedChunk]:
    distance = ChunkEmbedding.embedding.l2_distance(vector).label("distance")
    statement = (
        select(Chunk, Document.filename, distance)
        .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
        .join(Document, Document.id == Chunk.document_id)
        .where(*_filters(user_id, kb_id))
        .order_by(distance, Chunk.chunk_index, Chunk.id)
        .limit(limit)
    )
    rows = (await session.execute(statement)).all()
    return [
        _to_chunk(chunk, filename, float(row_distance)) for chunk, filename, row_distance in rows
    ]


async def _search_in_python(
    session: AsyncSession,
    user_id: UUID,
    kb_id: UUID,
    vector: list[float],
    limit: int,
) -> list[RetrievedChunk]:
    """SQLite fallback: no vector operators, so score candidates in Python."""
    statement = (
        select(Chunk, Document.filename, ChunkEmbedding.embedding)
        .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
        .join(Document, Document.id == Chunk.document_id)
        .where(*_filters(user_id, kb_id))
    )
    rows = (await session.execute(statement)).all()
    scored = [
        (chunk, filename, _l2_distance(vector, embedding)) for chunk, filename, embedding in rows
    ]
    scored.sort(key=lambda item: (item[2], item[0].chunk_index, item[0].id.int))
    return [_to_chunk(chunk, filename, distance) for chunk, filename, distance in scored[:limit]]


def _l2_distance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding dimension mismatch")
    return sum((a - b) ** 2 for a, b in zip(left, right, strict=True)) ** 0.5


def _to_chunk(chunk: Chunk, filename: str, distance: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        filename=filename,
        page_no=chunk.page_no,
        chunk_index=chunk.chunk_index,
        text=chunk.text,
        distance=distance,
    )


def _snippet(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= SNIPPET_MAX_CHARS:
        return collapsed
    return collapsed[: SNIPPET_MAX_CHARS - 1] + SNIPPET_ELLIPSIS
