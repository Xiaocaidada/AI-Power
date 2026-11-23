from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.config import get_settings

NodeType = Literal[
    "start",
    "llm",
    "kb_search",
    "tool",
    "agent",
    "condition",
    "parallel",
    "join",
    "output",
    "review",
    "loop",
    "http",
    "mcp",
    "memory_read",
    "memory_write",
    "code",
    "database",
    "mcp_resource",
    "mcp_prompt",
]
ConditionOperator = Literal[
    "equals", "not_equals", "contains", "not_contains", "not_empty", "is_empty"
]
MemoryScope = Literal["user", "workspace"]


class LLMNodeConfig(BaseModel):
    provider_id: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=20000)
    system_prompt: str | None = Field(default=None, max_length=20000)


class KbSearchNodeConfig(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    kb_ids: list[UUID] = Field(default_factory=list, max_length=10)


class ToolNodeConfig(BaseModel):
    tool: str = Field(min_length=1, max_length=80)
    arguments: dict[str, str] = Field(default_factory=dict)


class AgentNodeConfig(BaseModel):
    provider_id: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=200)
    task: str = Field(min_length=1, max_length=20000)
    agent_id: UUID | None = None
    kb_ids: list[UUID] = Field(default_factory=list, max_length=10)
    tools: list[str] = Field(default_factory=list, max_length=20)
    max_steps: int | None = Field(default=None, ge=1, le=32)

    @model_validator(mode="after")
    def _validate_target(self) -> "AgentNodeConfig":
        if self.agent_id is None and (not self.provider_id or not self.model):
            raise ValueError("agent node needs agent_id or provider_id + model")
        return self


class ConditionNodeConfig(BaseModel):
    left: str = Field(min_length=1, max_length=5000)
    operator: ConditionOperator
    right: str = Field(default="", max_length=5000)


class ReviewNodeConfig(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    timeout_seconds: int | None = Field(default=None, ge=30, le=86400)


class LoopNodeConfig(BaseModel):
    mode: Literal["foreach", "repeat"] = "foreach"
    items: str = Field(default="", max_length=20000)
    times: int = Field(default=3, ge=1, le=20)
    max_iterations: int = Field(default=5, ge=1, le=20)
    provider_id: str | None = Field(default=None, max_length=50)
    model: str | None = Field(default=None, max_length=200)
    system_prompt: str | None = Field(default=None, max_length=20000)
    prompt: str = Field(default="", max_length=20000)
    until_operator: ConditionOperator | Literal["none", ""] | None = None
    until_right: str = Field(default="", max_length=5000)
    separator: str = Field(default="\n", max_length=40)

    @model_validator(mode="after")
    def _validate_loop(self) -> "LoopNodeConfig":
        if self.mode == "foreach" and not self.items.strip():
            raise ValueError("foreach loop needs items")
        if self.prompt.strip() and (not self.provider_id or not self.model):
            raise ValueError("loop prompt needs provider_id + model")
        if self.until_operator in {"none", ""}:
            self.until_operator = None
        return self


class HttpNodeConfig(BaseModel):
    method: Literal["GET", "POST"] = "GET"
    url: str = Field(min_length=1, max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = Field(default="", max_length=20000)
    timeout_seconds: int = Field(default=15, ge=1, le=60)

    @field_validator("headers")
    @classmethod
    def _validate_headers(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 10:
            raise ValueError("at most 10 HTTP headers are allowed")
        for key, header_value in value.items():
            if not key or len(key) > 100 or any(char in key for char in "\r\n:"):
                raise ValueError("invalid HTTP header name")
            if len(header_value) > 2000 or any(char in header_value for char in "\r\n"):
                raise ValueError("invalid HTTP header value")
        return value


class McpNodeConfig(BaseModel):
    server_id: UUID
    tool: str = Field(min_length=1, max_length=120)
    arguments: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=20, ge=1, le=120)

    @field_validator("arguments")
    @classmethod
    def _validate_arguments(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 20:
            raise ValueError("at most 20 MCP arguments are allowed")
        return value


class McpResourceNodeConfig(BaseModel):
    server_id: UUID
    uri: str = Field(min_length=1, max_length=2000)
    timeout_seconds: int = Field(default=20, ge=1, le=120)


class McpPromptNodeConfig(BaseModel):
    server_id: UUID
    name: str = Field(min_length=1, max_length=120)
    arguments: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=20, ge=1, le=120)


class MemoryReadNodeConfig(BaseModel):
    query: str = Field(default="", max_length=2000)
    limit: int = Field(default=5, ge=1, le=20)
    scope: MemoryScope = "user"


class MemoryWriteNodeConfig(BaseModel):
    title: str = Field(default="", max_length=120)
    content: str = Field(min_length=1, max_length=10000)
    scope: MemoryScope = "user"
    kind: Literal["fact", "preference", "summary"] = "fact"


class CodeNodeConfig(BaseModel):
    code: str = Field(min_length=1, max_length=5000)
    max_output_chars: int = Field(default=20000, ge=1, le=100000)


class DatabaseNodeConfig(BaseModel):
    connection_id: UUID
    query: str = Field(min_length=1, max_length=10000)
    params: dict[str, str] = Field(default_factory=dict)
    max_rows: int = Field(default=100, ge=1, le=500)
    timeout_seconds: int = Field(default=15, ge=1, le=120)

    @field_validator("params")
    @classmethod
    def _validate_params(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > 20:
            raise ValueError("at most 20 query parameters are allowed")
        return value


class EmptyNodeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


NODE_CONFIGS: dict[str, type[BaseModel]] = {
    "start": EmptyNodeConfig,
    "llm": LLMNodeConfig,
    "kb_search": KbSearchNodeConfig,
    "tool": ToolNodeConfig,
    "agent": AgentNodeConfig,
    "condition": ConditionNodeConfig,
    "parallel": EmptyNodeConfig,
    "join": EmptyNodeConfig,
    "output": EmptyNodeConfig,
    "review": ReviewNodeConfig,
    "loop": LoopNodeConfig,
    "http": HttpNodeConfig,
    "mcp": McpNodeConfig,
    "mcp_resource": McpResourceNodeConfig,
    "mcp_prompt": McpPromptNodeConfig,
    "memory_read": MemoryReadNodeConfig,
    "memory_write": MemoryWriteNodeConfig,
    "code": CodeNodeConfig,
    "database": DatabaseNodeConfig,
}


class WorkflowNode(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,49}$")
    type: NodeType
    config: dict[str, object]
    ui: dict[str, float] | None = None


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_node: str = Field(alias="from")
    to: str
    when: Literal["true", "false"] | None = None


class WorkflowDefinition(BaseModel):
    nodes: list[WorkflowNode] = Field(min_length=1)
    edges: list[WorkflowEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph(self) -> "WorkflowDefinition":
        settings = get_settings()
        if len(self.nodes) > settings.workflow_max_nodes:
            raise ValueError(f"A workflow can contain at most {settings.workflow_max_nodes} nodes")
        ids = [node.id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("Node ids must be unique")
        known = set(ids)
        by_id = {node.id: node for node in self.nodes}
        for node in self.nodes:
            try:
                NODE_CONFIGS[node.type].model_validate(node.config)
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid config for node {node.id}: {exc.errors()[0]['msg']}"
                ) from None

        incoming: dict[str, list[WorkflowEdge]] = {node_id: [] for node_id in ids}
        outgoing: dict[str, list[WorkflowEdge]] = {node_id: [] for node_id in ids}
        seen_edges: set[tuple[str, str]] = set()
        for edge in self.edges:
            if edge.from_node not in known or edge.to not in known:
                raise ValueError(f"Edge references an unknown node: {edge.from_node}->{edge.to}")
            if edge.from_node == edge.to:
                raise ValueError("Self edges are not allowed")
            pair = (edge.from_node, edge.to)
            if pair in seen_edges:
                raise ValueError(f"Duplicate edge: {edge.from_node}->{edge.to}")
            seen_edges.add(pair)
            incoming[edge.to].append(edge)
            outgoing[edge.from_node].append(edge)
            source_type = by_id[edge.from_node].type
            if source_type == "condition":
                if edge.when is None:
                    raise ValueError("Edges from a condition node must set when=true/false")
            elif edge.when is not None:
                raise ValueError("Only condition nodes may label edges with when")

        for node in self.nodes:
            out_edges = outgoing[node.id]
            if node.type == "condition":
                labels = {edge.when for edge in out_edges}
                if labels != {"true", "false"} or len(out_edges) != 2:
                    raise ValueError(
                        f"Condition node {node.id} needs exactly one true and one false edge"
                    )
            elif node.type == "parallel":
                if len(out_edges) < 2:
                    raise ValueError(f"Parallel node {node.id} needs at least two outgoing edges")
            elif node.type == "join":
                if len(incoming[node.id]) < 2:
                    raise ValueError(f"Join node {node.id} needs at least two incoming edges")
            elif node.type == "start":
                if incoming[node.id]:
                    raise ValueError(f"Start node {node.id} cannot have incoming edges")
                if len(out_edges) > 1:
                    raise ValueError(f"Start node {node.id} can have at most one outgoing edge")
            elif node.type == "output":
                if out_edges:
                    raise ValueError(f"Output node {node.id} cannot have outgoing edges")
            elif len(out_edges) > 1:
                raise ValueError(f"Node {node.id} can have at most one outgoing edge")

        entries = [node_id for node_id in ids if not incoming[node_id]]
        if len(entries) != 1:
            raise ValueError("A workflow must have exactly one entry node")

        indegree = {node_id: len(incoming[node_id]) for node_id in ids}
        queue = [node_id for node_id in ids if indegree[node_id] == 0]
        visited = 0
        while queue:
            current = queue.pop()
            visited += 1
            for edge in outgoing[current]:
                indegree[edge.to] -= 1
                if indegree[edge.to] == 0:
                    queue.append(edge.to)
        if visited != len(ids):
            raise ValueError("Workflow contains a cycle")
        return self

    def node_map(self) -> dict[str, WorkflowNode]:
        return {node.id: node for node in self.nodes}

    def outgoing(self) -> dict[str, list[WorkflowEdge]]:
        result: dict[str, list[WorkflowEdge]] = {node.id: [] for node in self.nodes}
        for edge in self.edges:
            result[edge.from_node].append(edge)
        return result

    def incoming(self) -> dict[str, list[WorkflowEdge]]:
        result: dict[str, list[WorkflowEdge]] = {node.id: [] for node in self.nodes}
        for edge in self.edges:
            result[edge.to].append(edge)
        return result


class WorkflowValidationError(Exception):
    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages


def validate_definition(raw: object) -> WorkflowDefinition:
    try:
        return WorkflowDefinition.model_validate(raw)
    except ValidationError as exc:
        messages = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()[:5]
        ]
        raise WorkflowValidationError(messages) from None
