from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

KnowledgeNodeType = Literal[
    "start",
    "parse_document",
    "ocr_document",
    "clean_text",
    "filter_text",
    "chunk_text",
    "enrich_metadata",
    "extract_keywords",
    "summarize_chunks",
    "dedupe_chunks",
    "embed_chunks",
    "index_knowledge",
    "output",
]
KNOWLEDGE_NODE_TYPES: frozenset[str] = frozenset(
    {
        "start",
        "parse_document",
        "ocr_document",
        "clean_text",
        "filter_text",
        "chunk_text",
        "enrich_metadata",
        "extract_keywords",
        "summarize_chunks",
        "dedupe_chunks",
        "embed_chunks",
        "index_knowledge",
        "output",
    }
)
ChunkStrategy = Literal[
    "fixed",
    "markdown",
    "recursive",
    "custom",
    "parent_child",
    "semantic",
]


class EmptyKnowledgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParseDocumentConfig(BaseModel):
    keep_blank_pages: bool = False
    format: Literal[
        "auto",
        "pdf",
        "text",
        "markdown",
        "html",
        "csv",
        "docx",
        "xlsx",
        "pptx",
        "image",
    ] = "auto"


class OcrDocumentConfig(BaseModel):
    mode: Literal["blank", "short", "always"] = "blank"
    min_chars: int = Field(default=0, ge=0, le=5000)
    max_pages: int = Field(default=50, ge=1, le=200)


class CleanTextConfig(BaseModel):
    collapse_whitespace: bool = True
    strip_urls: bool = False
    strip_control: bool = True


class FilterTextConfig(BaseModel):
    min_line_chars: int = Field(default=0, ge=0, le=2000)
    drop_patterns: str = Field(default="", max_length=4000)
    dedupe_lines: bool = True
    normalize_width: bool = True
    drop_boilerplate: bool = False


class ChunkTextConfig(BaseModel):
    strategy: ChunkStrategy = "fixed"
    chunk_size: int = Field(default=800, ge=50, le=4000)
    chunk_overlap: int = Field(default=120, ge=0, le=1000)
    min_chars: int = Field(default=20, ge=0, le=2000)
    keep_heading: bool = True
    separators: str = Field(default="\\n\\n|\\n|。|！|？|. |，|,| ", max_length=500)
    parent_size: int = Field(default=2000, ge=200, le=8000)
    child_size: int = Field(default=400, ge=50, le=4000)
    semantic_threshold: float = Field(default=0.55, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _overlap_is_smaller(self) -> "ChunkTextConfig":
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if self.strategy == "parent_child" and self.child_size >= self.parent_size:
            raise ValueError("child_size must be smaller than parent_size")
        return self


class EnrichMetadataConfig(BaseModel):
    include_filename: bool = True
    include_folder: bool = True
    include_tags: bool = True
    include_source: bool = True
    prepend_title: bool = False


class ExtractKeywordsConfig(BaseModel):
    count: int = Field(default=8, ge=1, le=30)
    prepend: bool = False


class SummarizeChunksConfig(BaseModel):
    max_chars: int = Field(default=200, ge=40, le=1000)
    mode: Literal["extractive", "first_sentence"] = "extractive"
    prepend: bool = False


class DedupeChunksConfig(BaseModel):
    threshold: float = Field(default=0.92, ge=0.5, le=1.0)
    min_chars: int = Field(default=0, ge=0, le=2000)


class EmbedChunksConfig(BaseModel):
    batch_size: int | None = Field(default=None, ge=1, le=64)


class IndexKnowledgeConfig(BaseModel):
    mode: Literal["vector", "fulltext", "hybrid"] | None = None
    require_embeddings: bool = True

    @property
    def resolved_mode(self) -> Literal["vector", "fulltext", "hybrid"]:
        if self.mode is not None:
            return self.mode
        return "hybrid" if self.require_embeddings else "fulltext"


KNOWLEDGE_CONFIGS: dict[str, type[BaseModel]] = {
    "start": EmptyKnowledgeConfig,
    "parse_document": ParseDocumentConfig,
    "ocr_document": OcrDocumentConfig,
    "clean_text": CleanTextConfig,
    "filter_text": FilterTextConfig,
    "chunk_text": ChunkTextConfig,
    "enrich_metadata": EnrichMetadataConfig,
    "extract_keywords": ExtractKeywordsConfig,
    "summarize_chunks": SummarizeChunksConfig,
    "dedupe_chunks": DedupeChunksConfig,
    "embed_chunks": EmbedChunksConfig,
    "index_knowledge": IndexKnowledgeConfig,
    "output": EmptyKnowledgeConfig,
}


class KnowledgeNode(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,49}$")
    type: KnowledgeNodeType
    config: dict[str, object] = Field(default_factory=dict)
    ui: dict[str, float] | None = None


class KnowledgeEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_node: str = Field(alias="from")
    to: str
    when: Literal["true", "false"] | None = None


class KnowledgeProcessDefinition(BaseModel):
    nodes: list[KnowledgeNode] = Field(min_length=1, max_length=30)
    edges: list[KnowledgeEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_pipeline(self) -> "KnowledgeProcessDefinition":
        ids = [node.id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("Node ids must be unique")
        known = set(ids)
        for node in self.nodes:
            try:
                KNOWLEDGE_CONFIGS[node.type].model_validate(node.config)
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid config for node {node.id}: {exc.errors()[0]['msg']}"
                ) from None

        incoming: dict[str, list[KnowledgeEdge]] = {node_id: [] for node_id in ids}
        outgoing: dict[str, list[KnowledgeEdge]] = {node_id: [] for node_id in ids}
        seen: set[tuple[str, str]] = set()
        for edge in self.edges:
            if edge.from_node not in known or edge.to not in known:
                raise ValueError(
                    f"Edge references an unknown node: {edge.from_node}->{edge.to}"
                )
            if edge.from_node == edge.to:
                raise ValueError("Self edges are not allowed")
            if edge.when is not None:
                raise ValueError("Knowledge processing edges cannot be conditional")
            pair = (edge.from_node, edge.to)
            if pair in seen:
                raise ValueError(f"Duplicate edge: {edge.from_node}->{edge.to}")
            seen.add(pair)
            incoming[edge.to].append(edge)
            outgoing[edge.from_node].append(edge)

        starts = [node.id for node in self.nodes if node.type == "start"]
        outputs = [node.id for node in self.nodes if node.type == "output"]
        if len(starts) != 1:
            raise ValueError("A knowledge process needs exactly one start node")
        if len(outputs) != 1:
            raise ValueError("A knowledge process needs exactly one output node")
        start = starts[0]
        output = outputs[0]
        if incoming[start]:
            raise ValueError("Start node cannot have incoming edges")
        if outgoing[output]:
            raise ValueError("Output node cannot have outgoing edges")
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
            raise ValueError("Knowledge process must be a single linear pipeline")

        order: list[str] = []
        current = start
        while True:
            order.append(current)
            edges = outgoing[current]
            if not edges:
                break
            current = edges[0].to
            if current in order:
                raise ValueError("Knowledge process contains a cycle")
        if len(order) != len(self.nodes):
            raise ValueError("All nodes must be reachable from start")
        if order[-1] != output:
            raise ValueError("Pipeline must end at the output node")
        return self

    def ordered_nodes(self) -> list[KnowledgeNode]:
        by_id = {node.id: node for node in self.nodes}
        start = next(node.id for node in self.nodes if node.type == "start")
        outgoing: dict[str, list[KnowledgeEdge]] = {node.id: [] for node in self.nodes}
        for edge in self.edges:
            outgoing[edge.from_node].append(edge)
        order: list[KnowledgeNode] = []
        current = start
        while True:
            order.append(by_id[current])
            edges = outgoing[current]
            if not edges:
                break
            current = edges[0].to
        return order


class KnowledgeValidationError(Exception):
    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages


def validate_knowledge_process(raw: object) -> KnowledgeProcessDefinition:
    try:
        return KnowledgeProcessDefinition.model_validate(raw)
    except ValidationError as exc:
        messages = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()[:5]
        ]
        raise KnowledgeValidationError(messages) from None