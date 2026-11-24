import time
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select

from app.models import KnowledgeBase
from app.providers.base import ChatMessage, ProviderError
from app.providers.registry import ProviderRegistry
from app.services.knowledge.retrieval_schema import (
    ContextConfig,
    FallbackSearchConfig,
    FilterResultsConfig,
    HybridSearchConfig,
    KnowledgeRetrievalDefinition,
    LexicalSearchConfig,
    MultiQueryConfig,
    RerankConfig,
    RewriteQueryConfig,
    TopKConfig,
    VectorSearchConfig,
)
from app.services.model_stream import ModelCompletion
from app.services.provider_configs import build_user_registry
from app.services.rag import fit_context
from app.services.retrieval import (
    Citation,
    RetrievedChunk,
    build_citations,
    expand_parent_context,
    fuse_rrf,
    hybrid_search_chunks,
    lexical_search_chunks,
    rerank_chunks,
    vector_search_chunks,
)
from app.services.usage_ledger import SOURCE_KNOWLEDGE_RETRIEVAL


class RetrievalWorkflowError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class RetrievalTrace:
    node_id: str
    node_type: str
    status: str
    duration_ms: float
    count: int = 0
    error_code: str | None = None


@dataclass(slots=True)
class RetrievalWorkflowResult:
    query: str
    rewritten_query: str = ""
    chunks: list[RetrievedChunk] = field(default_factory=list)
    selected: list[RetrievedChunk] = field(default_factory=list)
    context: str = ""
    citations: list[Citation] = field(default_factory=list)
    traces: list[RetrievalTrace] = field(default_factory=list)
    mode: str = "workflow"


def _render_query(prompt: str, query: str) -> str:
    return prompt.replace("{{query}}", query).replace("{{input}}", query)


async def run_retrieval_workflow(
    session,
    *,
    definition: KnowledgeRetrievalDefinition,
    workspace_id: UUID,
    kb_ids: list[UUID],
    query: str,
    registry: ProviderRegistry | None = None,
    user_id: UUID | None = None,
    collect_traces: bool = False,
) -> RetrievalWorkflowResult:
    if not kb_ids:
        raise RetrievalWorkflowError("no_knowledge_base", "No knowledge base selected")
    state = RetrievalWorkflowResult(query=query)
    chunks: list[RetrievedChunk] = []
    active_registry = registry
    traces: list[RetrievalTrace] = []

    for node in definition.ordered_nodes():
        started = time.perf_counter()
        try:
            if node.type == "start":
                state.rewritten_query = query
            elif node.type == "rewrite_query":
                config = RewriteQueryConfig.model_validate(node.config)
                active_registry = active_registry or await build_user_registry(
                    session, workspace_id, user_id or workspace_id
                )
                try:
                    provider = active_registry.get(config.provider_id)
                except ProviderError:
                    raise RetrievalWorkflowError(
                        "rewrite_provider_unavailable",
                        "Query rewrite provider is unavailable",
                    ) from None
                messages = []
                if config.system_prompt:
                    messages.append(
                        ChatMessage(role="system", content=config.system_prompt)
                    )
                messages.append(
                    ChatMessage(role="user", content=_render_query(config.prompt, query))
                )
                completion = ModelCompletion(
                    provider=provider,
                    model=config.model,
                    messages=messages,
                    opts={},
                    workspace_id=workspace_id,
                    user_id=user_id or workspace_id,
                    source=SOURCE_KNOWLEDGE_RETRIEVAL,
                )
                metrics = await completion.run()
                if metrics.status != "completed" or not metrics.content.strip():
                    raise RetrievalWorkflowError(
                        "rewrite_failed", "Query rewrite failed"
                    )
                query = metrics.content.strip()[:2000]
                state.rewritten_query = query
            elif node.type == "multi_query":
                config = MultiQueryConfig.model_validate(node.config)
                active_registry = active_registry or await build_user_registry(
                    session, workspace_id, user_id or workspace_id
                )
                try:
                    provider = active_registry.get(config.provider_id)
                except ProviderError:
                    raise RetrievalWorkflowError(
                        "multi_query_provider_unavailable",
                        "Multi-query provider is unavailable",
                    ) from None
                messages = []
                if config.system_prompt:
                    messages.append(
                        ChatMessage(role="system", content=config.system_prompt)
                    )
                prompt = _render_query(config.prompt, query).replace(
                    "{variants}", str(config.variants)
                )
                messages.append(ChatMessage(role="user", content=prompt))
                completion = ModelCompletion(
                    provider=provider,
                    model=config.model,
                    messages=messages,
                    opts={},
                    workspace_id=workspace_id,
                    user_id=user_id or workspace_id,
                    source=SOURCE_KNOWLEDGE_RETRIEVAL,
                )
                metrics = await completion.run()
                if metrics.status != "completed":
                    raise RetrievalWorkflowError(
                        "multi_query_failed", "Query variant generation failed"
                    )
                variants = [
                    line.strip(" -\t")
                    for line in metrics.content.splitlines()
                    if line.strip(" -\t")
                ][: config.variants]
                if not variants:
                    raise RetrievalWorkflowError(
                        "multi_query_failed", "Query variant generation was empty"
                    )
                search_ids = await _resolve_search_ids(
                    session,
                    workspace_id,
                    list(config.kb_ids) or list(kb_ids),
                )
                merged: list[RetrievedChunk] = []
                for variant in [query, *variants]:
                    result_chunks = await hybrid_search_chunks(
                        session,
                        workspace_id=workspace_id,
                        kb_ids=search_ids,
                        query=variant[:2000],
                        top_k=config.candidate_k,
                        candidate_k=config.candidate_k,
                        metadata_filter=config.metadata_filter or None,
                    )
                    merged = (
                        fuse_rrf(merged, result_chunks)
                        if merged
                        else result_chunks
                    )
                chunks = merged[: config.top_k]
                state.rewritten_query = variants[0]
            elif node.type == "vector_search":
                config = VectorSearchConfig.model_validate(node.config)
                chunks = await vector_search_chunks(
                    session,
                    workspace_id=workspace_id,
                    kb_ids=await _resolve_search_ids(
                        session,
                        workspace_id,
                        list(config.kb_ids) or list(kb_ids),
                    ),
                    query=query,
                    top_k=config.top_k,
                    metadata_filter=config.metadata_filter or None,
                )
            elif node.type == "lexical_search":
                config = LexicalSearchConfig.model_validate(node.config)
                chunks = await lexical_search_chunks(
                    session,
                    workspace_id=workspace_id,
                    kb_ids=await _resolve_search_ids(
                        session,
                        workspace_id,
                        list(config.kb_ids) or list(kb_ids),
                    ),
                    query=query,
                    top_k=config.top_k,
                    metadata_filter=config.metadata_filter or None,
                )
            elif node.type == "hybrid_search":
                config = HybridSearchConfig.model_validate(node.config)
                chunks = await hybrid_search_chunks(
                    session,
                    workspace_id=workspace_id,
                    kb_ids=await _resolve_search_ids(
                        session,
                        workspace_id,
                        list(config.kb_ids) or list(kb_ids),
                    ),
                    query=query,
                    top_k=config.top_k,
                    candidate_k=config.candidate_k,
                    metadata_filter=config.metadata_filter or None,
                )
            elif node.type == "filter_results":
                config = FilterResultsConfig.model_validate(node.config)
                chunks = _filter_results(chunks, config)
            elif node.type == "fallback_search":
                config = FallbackSearchConfig.model_validate(node.config)
                if not chunks:
                    chunks = await hybrid_search_chunks(
                        session,
                        workspace_id=workspace_id,
                        kb_ids=kb_ids,
                        query=query,
                        top_k=config.top_k,
                        candidate_k=config.candidate_k,
                    )
            elif node.type == "rerank":
                config = RerankConfig.model_validate(node.config)
                chunks = await rerank_chunks(
                    session,
                    workspace_id=workspace_id,
                    kb_ids=kb_ids,
                    query=query,
                    chunks=chunks,
                    top_k=config.top_k,
                )
            elif node.type == "top_k":
                config = TopKConfig.model_validate(node.config)
                chunks = chunks[: config.top_k]
            elif node.type == "context":
                config = ContextConfig.model_validate(node.config)
                state.selected = fit_context(
                    expand_parent_context(chunks), config.max_chars
                )
                state.context = "\n\n".join(
                    f"[{index}] {chunk.text}"
                    for index, chunk in enumerate(state.selected, start=1)
                )
                state.citations = build_citations(state.selected)
            elif node.type == "output":
                if not state.selected:
                    state.selected = expand_parent_context(chunks)
                    state.citations = build_citations(state.selected)
                    if not state.context:
                        state.context = "\n\n".join(
                            f"[{index}] {chunk.text}"
                            for index, chunk in enumerate(state.selected, start=1)
                        )
            else:
                raise RetrievalWorkflowError(
                    "unsupported_node_type", f"Unsupported node type: {node.type}"
                )
        except RetrievalWorkflowError:
            if collect_traces:
                traces.append(
                    RetrievalTrace(
                        node_id=node.id,
                        node_type=node.type,
                        status="failed",
                        duration_ms=_elapsed_ms(started),
                        error_code="workflow_error",
                    )
                )
            raise
        except Exception as exc:
            if collect_traces:
                traces.append(
                    RetrievalTrace(
                        node_id=node.id,
                        node_type=node.type,
                        status="failed",
                        duration_ms=_elapsed_ms(started),
                        error_code=type(exc).__name__,
                    )
                )
            raise RetrievalWorkflowError(
                "retrieval_workflow_failed", str(exc) or type(exc).__name__
            ) from None
        if collect_traces:
            traces.append(
                RetrievalTrace(
                    node_id=node.id,
                    node_type=node.type,
                    status="completed",
                    duration_ms=_elapsed_ms(started),
                    count=len(chunks),
                )
            )

    if not state.selected:
        state.selected = expand_parent_context(chunks)
    if not state.context:
        state.context = "\n\n".join(
            f"[{index}] {chunk.text}"
            for index, chunk in enumerate(state.selected, start=1)
        )
    if not state.citations:
        state.citations = build_citations(state.selected)
    state.chunks = chunks
    state.traces = traces
    return state


async def _resolve_search_ids(
    session, workspace_id: UUID, requested: list[UUID]
) -> list[UUID]:
    ids = list(dict.fromkeys(requested))
    if not ids:
        raise RetrievalWorkflowError(
            "no_knowledge_base", "No knowledge base selected for this search node"
        )
    rows = set(
        (
            await session.execute(
                select(KnowledgeBase.id).where(
                    KnowledgeBase.id.in_(ids),
                    KnowledgeBase.workspace_id == workspace_id,
                    KnowledgeBase.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    if rows != set(ids):
        raise RetrievalWorkflowError(
            "invalid_knowledge_base",
            "A search node references a missing or inaccessible knowledge base",
        )
    return ids


def _filter_results(
    chunks: list[RetrievedChunk], config: FilterResultsConfig
) -> list[RetrievedChunk]:
    selected: list[RetrievedChunk] = []
    seen_documents: set[UUID] = set()
    seen_parents: set[tuple[UUID, str]] = set()
    for chunk in chunks:
        if (
            config.max_distance is not None
            and chunk.distance is not None
            and chunk.distance > config.max_distance
        ):
            continue
        if (
            config.min_rerank_score is not None
            and chunk.rerank_score is not None
            and chunk.rerank_score < config.min_rerank_score
        ):
            continue
        if (
            config.min_fused_score is not None
            and chunk.fused_score is not None
            and chunk.fused_score < config.min_fused_score
        ):
            continue
        if len(chunk.text) < config.min_text_chars:
            continue
        parent_id = chunk.chunk_meta.get("parent_id")
        if config.dedupe_parents and isinstance(parent_id, str) and parent_id:
            key = (chunk.document_id, parent_id)
            if key in seen_parents:
                continue
            seen_parents.add(key)
        if config.dedupe_documents:
            if chunk.document_id in seen_documents:
                continue
            seen_documents.add(chunk.document_id)
        selected.append(chunk)
    return selected


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)