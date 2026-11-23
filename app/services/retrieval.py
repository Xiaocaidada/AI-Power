import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from uuid import UUID

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.metrics import metrics
from app.models import (
    Chunk,
    ChunkEmbedding,
    Document,
    KnowledgeBase,
    Workflow,
    WorkflowVersion,
)
from app.providers.base import ProviderError
from app.providers.embedding import EmbeddingProvider
from app.providers.rerank import Reranker, RerankResult
from app.services.kb_models import build_kb_embedder, build_kb_reranker
from app.services.knowledge_settings import KnowledgeBaseSettings, resolve_kb_settings

logger = logging.getLogger(__name__)

SNIPPET_MAX_CHARS = 240
SNIPPET_ELLIPSIS = "…"
RRF_K = 60
LEXICAL_WORD_MIN = 0.1
LEXICAL_TRIGRAM_MIN = 0.05


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    filename: str
    page_no: int | None
    chunk_index: int
    text: str
    distance: float | None
    vector_rank: int | None = None
    lexical_rank: int | None = None
    fused_score: float | None = None
    rerank_score: float | None = None


@dataclass(frozen=True, slots=True)
class Citation:
    index: int
    document_id: UUID
    chunk_id: UUID
    page_no: int | None
    snippet: str


@dataclass(frozen=True, slots=True)
class RetrievalOptions:
    top_k: int
    candidate_k: int
    hybrid_enabled: bool
    rerank_enabled: bool


@dataclass(frozen=True, slots=True)
class RetrievalOutcome:
    chunks: list[RetrievedChunk]
    timings: dict[str, float]
    mode: str
    options: RetrievalOptions


def resolve_options(
    settings: KnowledgeBaseSettings,
    *,
    top_k: int | None = None,
    candidate_k: int | None = None,
    hybrid_enabled: bool | None = None,
    rerank_enabled: bool | None = None,
) -> RetrievalOptions:
    retrieval = settings.retrieval
    resolved_top_k = retrieval.top_k if top_k is None else top_k
    if resolved_top_k < 1:
        raise ValueError("top_k must be >= 1")
    resolved_candidate_k = retrieval.candidate_k if candidate_k is None else candidate_k
    if resolved_candidate_k < resolved_top_k:
        resolved_candidate_k = resolved_top_k
    return RetrievalOptions(
        top_k=resolved_top_k,
        candidate_k=resolved_candidate_k,
        hybrid_enabled=retrieval.hybrid_enabled if hybrid_enabled is None else hybrid_enabled,
        rerank_enabled=retrieval.rerank_enabled if rerank_enabled is None else rerank_enabled,
    )


async def retrieve_chunks(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    kb_id: UUID | None = None,
    kb_ids: Sequence[UUID] | None = None,
    query: str,
    top_k: int | None = None,
    embedder: EmbeddingProvider | None = None,
    reranker: Reranker | None = None,
    options: RetrievalOptions | None = None,
    candidate_k: int | None = None,
    hybrid_enabled: bool | None = None,
    rerank_enabled: bool | None = None,
) -> list[RetrievedChunk]:
    """Retrieve the best chunks for one or more workspace knowledge bases."""
    outcome = await retrieve_with_diagnostics(
        session,
        workspace_id=workspace_id,
        kb_id=kb_id,
        kb_ids=kb_ids,
        query=query,
        top_k=top_k,
        embedder=embedder,
        reranker=reranker,
        options=options,
        candidate_k=candidate_k,
        hybrid_enabled=hybrid_enabled,
        rerank_enabled=rerank_enabled,
    )
    return outcome.chunks


async def retrieve_with_diagnostics(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    kb_id: UUID | None = None,
    kb_ids: Sequence[UUID] | None = None,
    query: str,
    top_k: int | None = None,
    embedder: EmbeddingProvider | None = None,
    reranker: Reranker | None = None,
    options: RetrievalOptions | None = None,
    candidate_k: int | None = None,
    hybrid_enabled: bool | None = None,
    rerank_enabled: bool | None = None,
) -> RetrievalOutcome:
    settings = get_settings()
    if top_k is not None and top_k < 1:
        raise ValueError("top_k must be >= 1")

    requested = list(
        dict.fromkeys(kb_ids or ([] if kb_id is None else [kb_id]))
    )
    if not requested:
        return RetrievalOutcome([], _empty_timings(), "empty", _fallback_options(top_k))
    kbs = list(
        (
            await session.execute(
                select(KnowledgeBase).where(
                    KnowledgeBase.id.in_(requested),
                    KnowledgeBase.workspace_id == workspace_id,
                    KnowledgeBase.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    if not kbs:
        return RetrievalOutcome([], _empty_timings(), "empty", _fallback_options(top_k))
    active_ids = [item.id for item in kbs]
    kb = next((item for item in kbs if item.id == requested[0]), kbs[0])
    kb_settings = resolve_kb_settings(kb, settings)
    if options is None:
        options = resolve_options(
            kb_settings,
            top_k=top_k,
            candidate_k=candidate_k,
            hybrid_enabled=hybrid_enabled,
            rerank_enabled=rerank_enabled,
        )
    elif top_k is not None or candidate_k is not None:
        options = replace(
            options,
            top_k=top_k if top_k is not None else options.top_k,
            candidate_k=max(candidate_k or options.candidate_k, top_k or options.top_k),
        )

    question = query.strip()
    if not question:
        return RetrievalOutcome([], _empty_timings(), "empty", options)

    bound_kb = next(
        (item for item in kbs if item.retrieval_workflow_version_id is not None),
        None,
    )
    if bound_kb is not None and bound_kb.retrieval_workflow_version_id is not None:
        try:
            from app.services.knowledge.retrieval_pipeline import (
                run_retrieval_workflow,
            )
            from app.services.knowledge.retrieval_schema import (
                validate_knowledge_retrieval,
            )

            version = await session.get(
                WorkflowVersion, bound_kb.retrieval_workflow_version_id
            )
            workflow = (
                await session.get(Workflow, version.workflow_id) if version else None
            )
            if (
                version is not None
                and workflow is not None
                and workflow.deleted_at is None
                and workflow.kind == "knowledge_retrieval"
            ):
                definition = validate_knowledge_retrieval(version.definition)
                custom = await run_retrieval_workflow(
                    session,
                    definition=definition,
                    workspace_id=workspace_id,
                    kb_ids=active_ids,
                    query=question,
                    user_id=bound_kb.user_id,
                    collect_traces=True,
                )
                custom_timings = {
                    "vector_ms": 0.0,
                    "lexical_ms": 0.0,
                    "rerank_ms": 0.0,
                    "total_ms": round(
                        sum(trace.duration_ms for trace in custom.traces), 1
                    ),
                }
                return RetrievalOutcome(
                    custom.selected or custom.chunks,
                    custom_timings,
                    "workflow",
                    options,
                )
        except Exception as exc:
            metrics.inc_counter(
                "ai_power_retrieval_workflow_failures_total",
                code=type(exc).__name__,
            )
            logger.warning(
                "retrieval workflow failed (%s); falling back to builtin retrieval",
                type(exc).__name__,
            )

    total_started = time.perf_counter()
    timings = _empty_timings()

    active_embedder = embedder or await build_kb_embedder(session, kb, kb_settings)
    vectors = await active_embedder.embed([question])
    if len(vectors) != 1:
        raise ProviderError("embedding_bad_response", "Query embedding is missing")
    vector = vectors[0]

    vector_limit = (
        options.candidate_k if options.hybrid_enabled or options.rerank_enabled else options.top_k
    )
    vector_started = time.perf_counter()
    if session.get_bind().dialect.name == "postgresql":
        vector_results = await _search_with_distance(
            session,
            workspace_id,
            active_ids,
            vector,
            vector_limit,
            kb_settings.retrieval.metadata_filter,
        )
    else:
        vector_results = await _search_in_python(
            session,
            workspace_id,
            active_ids,
            vector,
            vector_limit,
            kb_settings.retrieval.metadata_filter,
        )
    vector_results = [
        replace(chunk, vector_rank=index) for index, chunk in enumerate(vector_results, start=1)
    ]
    timings["vector_ms"] = _elapsed_ms(vector_started)

    lexical_results: list[RetrievedChunk] = []
    if options.hybrid_enabled:
        lexical_started = time.perf_counter()
        if session.get_bind().dialect.name == "postgresql":
            lexical_results = await _lexical_search_postgres(
                session,
                workspace_id,
                active_ids,
                question,
                options.candidate_k,
                kb_settings.retrieval.metadata_filter,
            )
        else:
            lexical_results = await _lexical_search_python(
                session,
                workspace_id,
                active_ids,
                question,
                options.candidate_k,
                kb_settings.retrieval.metadata_filter,
            )
        timings["lexical_ms"] = _elapsed_ms(lexical_started)

    if options.hybrid_enabled:
        fused = fuse_rrf(vector_results, lexical_results)
        mode = "hybrid"
    else:
        fused = vector_results
        mode = "vector"

    results = fused
    if options.rerank_enabled:
        active_reranker = reranker or await build_kb_reranker(session, kb, kb_settings)
        if active_reranker is not None and fused:
            rerank_started = time.perf_counter()
            candidates = fused[: min(options.candidate_k, settings.rerank_max_candidates)]
            try:
                reranked = await active_reranker.rerank(
                    question,
                    [chunk.text[: settings.rerank_max_doc_chars] for chunk in candidates],
                    top_n=options.top_k,
                )
                results = _order_by_rerank(candidates, reranked, options.top_k)
                mode = f"{mode}+rerank"
            except ProviderError as exc:
                metrics.inc_counter(
                    "ai_power_rerank_failures_total", code=exc.code, provider="rerank"
                )
                logger.warning("rerank failed (%s); using fused order", exc.code)
            except Exception:
                metrics.inc_counter(
                    "ai_power_rerank_failures_total", code="unexpected", provider="rerank"
                )
                logger.exception("rerank failed unexpectedly; using fused order")
            timings["rerank_ms"] = _elapsed_ms(rerank_started)

    results = results[: options.top_k]
    timings["total_ms"] = _elapsed_ms(total_started)
    metrics.inc_counter("ai_power_retrieval_requests_total", mode=mode)
    metrics.observe("ai_power_retrieval_duration_seconds", timings["total_ms"] / 1000, mode=mode)
    return RetrievalOutcome(results, timings, mode, options)


def fuse_rrf(
    vector_results: Sequence[RetrievedChunk],
    lexical_results: Sequence[RetrievedChunk],
    *,
    k: int = RRF_K,
) -> list[RetrievedChunk]:
    """Reciprocal rank fusion over vector and lexical candidate lists."""
    fused: dict[UUID, RetrievedChunk] = {}
    for rank, chunk in enumerate(vector_results, start=1):
        fused[chunk.chunk_id] = replace(
            chunk,
            vector_rank=rank,
            lexical_rank=None,
            fused_score=1 / (k + rank),
        )
    for rank, chunk in enumerate(lexical_results, start=1):
        existing = fused.get(chunk.chunk_id)
        if existing is None:
            fused[chunk.chunk_id] = replace(
                chunk,
                vector_rank=None,
                lexical_rank=rank,
                fused_score=1 / (k + rank),
            )
        else:
            fused[chunk.chunk_id] = replace(
                existing,
                lexical_rank=rank,
                fused_score=(existing.fused_score or 0.0) + 1 / (k + rank),
            )
    return sorted(
        fused.values(),
        key=lambda chunk: (
            -(chunk.fused_score or 0.0),
            chunk.vector_rank or 10**9,
            chunk.chunk_index,
            str(chunk.chunk_id),
        ),
    )


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


def _filters(
    session: AsyncSession,
    workspace_id: UUID,
    kb_ids: Sequence[UUID],
    metadata_filter: dict[str, str] | None = None,
) -> tuple:
    conditions: list = [
        Chunk.workspace_id == workspace_id,
        Chunk.kb_id.in_(list(kb_ids)),
        Document.status == "ready",
        Document.deleted_at.is_(None),
    ]
    if metadata_filter:
        if session.get_bind().dialect.name == "postgresql":
            for key, value in metadata_filter.items():
                conditions.append(Document.doc_metadata[key].astext == value)
        else:
            for key, value in metadata_filter.items():
                conditions.append(
                    func.json_extract(Document.doc_metadata, f"$.{key}") == value
                )
    return tuple(conditions)


async def _search_with_distance(
    session: AsyncSession,
    workspace_id: UUID,
    kb_ids: Sequence[UUID],
    vector: list[float],
    limit: int,
    metadata_filter: dict[str, str] | None = None,
) -> list[RetrievedChunk]:
    distance = ChunkEmbedding.embedding.l2_distance(vector).label("distance")
    statement = (
        select(Chunk, Document.filename, distance)
        .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
        .join(Document, Document.id == Chunk.document_id)
        .where(*_filters(session, workspace_id, kb_ids, metadata_filter))
        .order_by(distance, Chunk.chunk_index, Chunk.id)
        .limit(limit)
    )
    rows = (await session.execute(statement)).all()
    return [
        _to_chunk(chunk, filename, float(row_distance)) for chunk, filename, row_distance in rows
    ]


async def _search_in_python(
    session: AsyncSession,
    workspace_id: UUID,
    kb_ids: Sequence[UUID],
    vector: list[float],
    limit: int,
    metadata_filter: dict[str, str] | None = None,
) -> list[RetrievedChunk]:
    """SQLite fallback: no vector operators, so score candidates in Python."""
    statement = (
        select(Chunk, Document.filename, ChunkEmbedding.embedding)
        .join(ChunkEmbedding, ChunkEmbedding.chunk_id == Chunk.id)
        .join(Document, Document.id == Chunk.document_id)
        .where(*_filters(session, workspace_id, kb_ids, metadata_filter))
    )
    rows = (await session.execute(statement)).all()
    scored = [
        (chunk, filename, _l2_distance(vector, embedding)) for chunk, filename, embedding in rows
    ]
    scored.sort(key=lambda item: (item[2], item[0].chunk_index, item[0].id.int))
    return [_to_chunk(chunk, filename, distance) for chunk, filename, distance in scored[:limit]]


async def _lexical_search_postgres(
    session: AsyncSession,
    workspace_id: UUID,
    kb_ids: Sequence[UUID],
    query: str,
    limit: int,
    metadata_filter: dict[str, str] | None = None,
) -> list[RetrievedChunk]:
    """Trigram / substring / word similarity; requires pg_trgm."""
    contains = Chunk.text.contains(query, autoescape=True)
    word_score = func.word_similarity(query, Chunk.text)
    trigram_score = func.similarity(Chunk.text, query)
    score = func.greatest(
        case((contains, 1.0), else_=0.0),
        word_score,
        trigram_score,
    ).label("lexical_score")
    statement = (
        select(Chunk, Document.filename, score)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            *_filters(session, workspace_id, kb_ids, metadata_filter),
            or_(
                contains,
                word_score > LEXICAL_WORD_MIN,
                trigram_score > LEXICAL_TRIGRAM_MIN,
            ),
        )
        .order_by(score.desc(), Chunk.chunk_index, Chunk.id)
        .limit(limit)
    )
    rows = (await session.execute(statement)).all()
    return [
        replace(_to_chunk(chunk, filename, None), lexical_rank=index)
        for index, (chunk, filename, _score) in enumerate(rows, start=1)
    ]


async def _lexical_search_python(
    session: AsyncSession,
    workspace_id: UUID,
    kb_ids: Sequence[UUID],
    query: str,
    limit: int,
    metadata_filter: dict[str, str] | None = None,
) -> list[RetrievedChunk]:
    """SQLite fallback: character-bigram lexical score, no vector needed."""
    statement = (
        select(Chunk, Document.filename)
        .join(Document, Document.id == Chunk.document_id)
        .where(*_filters(session, workspace_id, kb_ids, metadata_filter))
    )
    rows = (await session.execute(statement)).all()
    scored = [(chunk, filename, _lexical_score(query, chunk.text)) for chunk, filename in rows]
    scored = [item for item in scored if item[2] > 0.0]
    scored.sort(key=lambda item: (-item[2], item[0].chunk_index, item[0].id.int))
    return [
        replace(_to_chunk(chunk, filename, None), lexical_rank=index)
        for index, (chunk, filename, _score) in enumerate(scored[:limit], start=1)
    ]


def _order_by_rerank(
    candidates: Sequence[RetrievedChunk],
    results: Sequence[RerankResult],
    top_k: int,
) -> list[RetrievedChunk]:
    ordered: list[RetrievedChunk] = []
    used: set[int] = set()
    for result in results:
        if 0 <= result.index < len(candidates) and result.index not in used:
            ordered.append(replace(candidates[result.index], rerank_score=result.score))
            used.add(result.index)
        if len(ordered) >= top_k:
            return ordered
    for index, candidate in enumerate(candidates):
        if index not in used:
            ordered.append(replace(candidate, rerank_score=None))
        if len(ordered) >= top_k:
            break
    return ordered


def _lexical_score(query: str, text: str) -> float:
    question = query.strip().lower()
    body = text.lower()
    if not question or not body:
        return 0.0
    if question in body:
        return 1.0 + min(len(question) / len(body), 1.0)
    query_grams = _bigrams(question)
    if not query_grams:
        return 0.0
    body_grams = _bigrams(body)
    return len(query_grams & body_grams) / len(query_grams)


def _bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text}
    return {text[index : index + 2] for index in range(len(text) - 1)}


def _l2_distance(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding dimension mismatch")
    return sum((a - b) ** 2 for a, b in zip(left, right, strict=True)) ** 0.5


def _to_chunk(chunk: Chunk, filename: str, distance: float | None) -> RetrievedChunk:
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


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _empty_timings() -> dict[str, float]:
    return {"vector_ms": 0.0, "lexical_ms": 0.0, "rerank_ms": 0.0, "total_ms": 0.0}


def _fallback_options(top_k: int | None) -> RetrievalOptions:
    settings = get_settings()
    top = settings.retrieval_top_k if top_k is None else top_k
    return RetrievalOptions(
        top_k=top,
        candidate_k=max(settings.retrieval_candidate_k, top),
        hybrid_enabled=settings.retrieval_hybrid_enabled,
        rerank_enabled=settings.rerank_enabled and bool(settings.rerank_base_url.strip()),
    )


async def vector_search_chunks(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    kb_ids: Sequence[UUID],
    query: str,
    top_k: int = 10,
    embedder: EmbeddingProvider | None = None,
) -> list[RetrievedChunk]:
    requested = list(dict.fromkeys(kb_ids))
    if not requested or not query.strip():
        return []
    kbs = list(
        (
            await session.execute(
                select(KnowledgeBase).where(
                    KnowledgeBase.id.in_(requested),
                    KnowledgeBase.workspace_id == workspace_id,
                    KnowledgeBase.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    if not kbs:
        return []
    kb = kbs[0]
    kb_settings = resolve_kb_settings(kb)
    active_embedder = embedder or await build_kb_embedder(session, kb, kb_settings)
    vectors = await active_embedder.embed([query.strip()])
    if len(vectors) != 1:
        raise ProviderError("embedding_bad_response", "Query embedding is missing")
    limit = max(1, top_k)
    if session.get_bind().dialect.name == "postgresql":
        results = await _search_with_distance(
            session,
            workspace_id,
            [item.id for item in kbs],
            vectors[0],
            limit,
            kb_settings.retrieval.metadata_filter,
        )
    else:
        results = await _search_in_python(
            session,
            workspace_id,
            [item.id for item in kbs],
            vectors[0],
            limit,
            kb_settings.retrieval.metadata_filter,
        )
    return [
        replace(chunk, vector_rank=index)
        for index, chunk in enumerate(results, start=1)
    ]


async def lexical_search_chunks(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    kb_ids: Sequence[UUID],
    query: str,
    top_k: int = 10,
) -> list[RetrievedChunk]:
    requested = list(dict.fromkeys(kb_ids))
    if not requested or not query.strip():
        return []
    kbs = list(
        (
            await session.execute(
                select(KnowledgeBase).where(
                    KnowledgeBase.id.in_(requested),
                    KnowledgeBase.workspace_id == workspace_id,
                    KnowledgeBase.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    if not kbs:
        return []
    kb_settings = resolve_kb_settings(kbs[0])
    limit = max(1, top_k)
    if session.get_bind().dialect.name == "postgresql":
        results = await _lexical_search_postgres(
            session,
            workspace_id,
            [item.id for item in kbs],
            query.strip(),
            limit,
            kb_settings.retrieval.metadata_filter,
        )
    else:
        results = await _lexical_search_python(
            session,
            workspace_id,
            [item.id for item in kbs],
            query.strip(),
            limit,
            kb_settings.retrieval.metadata_filter,
        )
    return [
        replace(chunk, lexical_rank=index)
        for index, chunk in enumerate(results, start=1)
    ]


async def hybrid_search_chunks(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    kb_ids: Sequence[UUID],
    query: str,
    top_k: int = 10,
    candidate_k: int = 20,
) -> list[RetrievedChunk]:
    vector_results = await vector_search_chunks(
        session,
        workspace_id=workspace_id,
        kb_ids=kb_ids,
        query=query,
        top_k=max(top_k, candidate_k),
    )
    lexical_results = await lexical_search_chunks(
        session,
        workspace_id=workspace_id,
        kb_ids=kb_ids,
        query=query,
        top_k=max(top_k, candidate_k),
    )
    return fuse_rrf(vector_results, lexical_results)[:top_k]


async def rerank_chunks(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    kb_ids: Sequence[UUID],
    query: str,
    chunks: Sequence[RetrievedChunk],
    top_k: int = 5,
    reranker: Reranker | None = None,
) -> list[RetrievedChunk]:
    if not chunks:
        return []
    requested = list(dict.fromkeys(kb_ids))
    kbs = list(
        (
            await session.execute(
                select(KnowledgeBase).where(
                    KnowledgeBase.id.in_(requested),
                    KnowledgeBase.workspace_id == workspace_id,
                    KnowledgeBase.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    if not kbs:
        return list(chunks[:top_k])
    kb = kbs[0]
    kb_settings = resolve_kb_settings(kb)
    settings = get_settings()
    active = reranker or await build_kb_reranker(session, kb, kb_settings)
    if active is None:
        return list(chunks[:top_k])
    candidates = list(chunks[: settings.rerank_max_candidates])
    try:
        reranked = await active.rerank(
            query,
            [chunk.text[: settings.rerank_max_doc_chars] for chunk in candidates],
            top_n=top_k,
        )
    except Exception:
        return list(chunks[:top_k])
    return _order_by_rerank(candidates, reranked, top_k)
