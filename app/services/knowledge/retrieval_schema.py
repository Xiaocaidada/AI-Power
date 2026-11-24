import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

METADATA_KEY = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")

RetrievalNodeType = Literal[
    "start",
    "rewrite_query",
    "multi_query",
    "intent_classify",
    "synonym_expand",
    "vector_search",
    "lexical_search",
    "hybrid_search",
    "filter_results",
    "fallback_search",
    "rerank",
    "top_k",
    "context",
    "output",
]


class EmptyRetrievalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RewriteQueryConfig(BaseModel):
    provider_id: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=200)
    prompt: str = Field(
        default=(
            "Rewrite the user question for knowledge retrieval. "
            "Return only the rewritten query.\n\n{{query}}"
        ),
        min_length=1,
        max_length=20000,
    )
    system_prompt: str | None = Field(default=None, max_length=20000)


class SearchNodeConfig(BaseModel):
    top_k: int = Field(default=10, ge=1, le=50)
    metadata_filter: dict[str, str] = Field(default_factory=dict, max_length=10)
    kb_ids: list[UUID] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _metadata_filter(self) -> "SearchNodeConfig":
        for key, value in self.metadata_filter.items():
            if not METADATA_KEY.match(key):
                raise ValueError("metadata_filter key contains invalid characters")
            if len(value) > 200:
                raise ValueError("metadata_filter value is too long")
        return self


class VectorSearchConfig(SearchNodeConfig):
    pass


class LexicalSearchConfig(SearchNodeConfig):
    pass


class HybridSearchConfig(SearchNodeConfig):
    candidate_k: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def _candidates(self) -> "HybridSearchConfig":
        if self.candidate_k < self.top_k:
            raise ValueError("candidate_k must be >= top_k")
        return self


class MultiQueryConfig(SearchNodeConfig):
    provider_id: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=200)
    variants: int = Field(default=3, ge=2, le=5)
    prompt: str = Field(
        default=(
            "Generate {variants} alternative search queries for the user question. "
            "Return one query per line, no numbering.\n\n{{query}}"
        ),
        min_length=1,
        max_length=20000,
    )
    system_prompt: str | None = Field(default=None, max_length=20000)
    candidate_k: int = Field(default=20, ge=1, le=100)


class IntentClassifyConfig(BaseModel):
    provider_id: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=200)
    categories: list[str] = Field(
        default_factory=lambda: ["general"], min_length=1, max_length=10
    )
    routes: dict[str, list[UUID]] = Field(default_factory=dict)
    prompt: str = Field(
        default=(
            "Classify the user question into exactly one of these categories: "
            "{categories}. Return only the category name.\n\n{{query}}"
        ),
        min_length=1,
        max_length=20000,
    )
    system_prompt: str | None = Field(default=None, max_length=20000)

    @model_validator(mode="after")
    def _routes(self) -> "IntentClassifyConfig":
        cleaned = [item.strip()[:40] for item in self.categories if item.strip()]
        if not cleaned:
            raise ValueError("categories must not be empty")
        unknown = set(self.routes) - set(cleaned)
        if unknown:
            raise ValueError("routes must reference declared categories")
        return self


class SynonymExpandConfig(BaseModel):
    provider_id: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=200)
    max_terms: int = Field(default=5, ge=1, le=10)
    prompt: str = Field(
        default=(
            "List synonyms or related search terms for the user question. "
            "Return one term per line, no numbering.\n\n{{query}}"
        ),
        min_length=1,
        max_length=20000,
    )
    system_prompt: str | None = Field(default=None, max_length=20000)


class FilterResultsConfig(BaseModel):
    max_distance: float | None = Field(default=None, ge=0.0)
    min_rerank_score: float | None = Field(default=None)
    min_fused_score: float | None = Field(default=None, ge=0.0)
    min_text_chars: int = Field(default=0, ge=0, le=10000)
    dedupe_documents: bool = False
    dedupe_parents: bool = True


class FallbackSearchConfig(BaseModel):
    top_k: int = Field(default=8, ge=1, le=50)
    candidate_k: int = Field(default=20, ge=1, le=100)


class RerankConfig(BaseModel):
    top_k: int = Field(default=5, ge=1, le=50)


class TopKConfig(BaseModel):
    top_k: int = Field(default=5, ge=1, le=50)


class ContextConfig(BaseModel):
    max_chars: int = Field(default=6000, ge=200, le=30000)


RETRIEVAL_CONFIGS: dict[str, type[BaseModel]] = {
    "start": EmptyRetrievalConfig,
    "rewrite_query": RewriteQueryConfig,
    "multi_query": MultiQueryConfig,
    "intent_classify": IntentClassifyConfig,
    "synonym_expand": SynonymExpandConfig,
    "vector_search": VectorSearchConfig,
    "lexical_search": LexicalSearchConfig,
    "hybrid_search": HybridSearchConfig,
    "filter_results": FilterResultsConfig,
    "fallback_search": FallbackSearchConfig,
    "rerank": RerankConfig,
    "top_k": TopKConfig,
    "context": ContextConfig,
    "output": EmptyRetrievalConfig,
}


class RetrievalNode(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,49}$")
    type: RetrievalNodeType
    config: dict[str, object] = Field(default_factory=dict)
    ui: dict[str, float] | None = None


class RetrievalEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_node: str = Field(alias="from")
    to: str
    when: Literal["true", "false"] | None = None


class KnowledgeRetrievalDefinition(BaseModel):
    nodes: list[RetrievalNode] = Field(min_length=1, max_length=20)
    edges: list[RetrievalEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_pipeline(self) -> "KnowledgeRetrievalDefinition":
        ids = [node.id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("Node ids must be unique")
        known = set(ids)
        for node in self.nodes:
            try:
                RETRIEVAL_CONFIGS[node.type].model_validate(node.config)
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid config for node {node.id}: {exc.errors()[0]['msg']}"
                ) from None
        incoming: dict[str, list[RetrievalEdge]] = {node_id: [] for node_id in ids}
        outgoing: dict[str, list[RetrievalEdge]] = {node_id: [] for node_id in ids}
        seen: set[tuple[str, str]] = set()
        for edge in self.edges:
            if edge.from_node not in known or edge.to not in known:
                raise ValueError(
                    f"Edge references an unknown node: {edge.from_node}->{edge.to}"
                )
            if edge.from_node == edge.to:
                raise ValueError("Self edges are not allowed")
            if edge.when is not None:
                raise ValueError("Retrieval edges cannot be conditional")
            pair = (edge.from_node, edge.to)
            if pair in seen:
                raise ValueError(f"Duplicate edge: {edge.from_node}->{edge.to}")
            seen.add(pair)
            incoming[edge.to].append(edge)
            outgoing[edge.from_node].append(edge)
        starts = [node.id for node in self.nodes if node.type == "start"]
        outputs = [node.id for node in self.nodes if node.type == "output"]
        if len(starts) != 1 or len(outputs) != 1:
            raise ValueError("A retrieval workflow needs exactly one start and one output")
        start, output = starts[0], outputs[0]
        if incoming[start] or outgoing[output]:
            raise ValueError("Start cannot have incoming or output outgoing edges")
        if len(outgoing[start]) != 1:
            raise ValueError("Start node must have exactly one outgoing edge")
        if len(incoming[output]) != 1:
            raise ValueError("Output node must have exactly one incoming edge")
        for node in self.nodes:
            if node.id in {start, output}:
                continue
            if len(incoming[node.id]) != 1 or len(outgoing[node.id]) != 1:
                raise ValueError(
                    f"Node {node.id} must have exactly one incoming and one outgoing edge"
                )
        if len(self.edges) != len(self.nodes) - 1:
            raise ValueError("Retrieval workflow must be a single linear pipeline")
        order: list[str] = []
        current = start
        while True:
            if current in order:
                raise ValueError("Retrieval workflow contains a cycle")
            order.append(current)
            edges = outgoing[current]
            if not edges:
                break
            current = edges[0].to
        if len(order) != len(self.nodes) or order[-1] != output:
            raise ValueError("All nodes must be reachable and end at output")
        return self

    def ordered_nodes(self) -> list[RetrievalNode]:
        by_id = {node.id: node for node in self.nodes}
        start = next(node.id for node in self.nodes if node.type == "start")
        outgoing: dict[str, list[RetrievalEdge]] = {node.id: [] for node in self.nodes}
        for edge in self.edges:
            outgoing[edge.from_node].append(edge)
        order: list[RetrievalNode] = []
        current = start
        while True:
            order.append(by_id[current])
            edges = outgoing[current]
            if not edges:
                break
            current = edges[0].to
        return order


class RetrievalValidationError(Exception):
    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages


def validate_knowledge_retrieval(raw: object) -> KnowledgeRetrievalDefinition:
    try:
        return KnowledgeRetrievalDefinition.model_validate(raw)
    except ValidationError as exc:
        messages = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        ][:5]
        raise RetrievalValidationError(messages) from None
