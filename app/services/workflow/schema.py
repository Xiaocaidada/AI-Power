from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.config import get_settings

NodeType = Literal["llm", "kb_search"]


class LLMNodeConfig(BaseModel):
    provider_id: str = Field(min_length=1, max_length=50)
    model: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=20000)
    system_prompt: str | None = Field(default=None, max_length=20000)


class KbSearchNodeConfig(BaseModel):
    query: str = Field(min_length=1, max_length=2000)


NODE_CONFIGS: dict[str, type[BaseModel]] = {
    "llm": LLMNodeConfig,
    "kb_search": KbSearchNodeConfig,
}


class WorkflowNode(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,49}$")
    type: NodeType
    config: dict[str, object]


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_node: str = Field(alias="from")
    to: str


class WorkflowDefinition(BaseModel):
    nodes: list[WorkflowNode] = Field(min_length=1)
    edges: list[WorkflowEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_graph(self) -> "WorkflowDefinition":
        if len(self.nodes) > get_settings().workflow_max_nodes:
            raise ValueError(
                f"A workflow can contain at most {get_settings().workflow_max_nodes} nodes"
            )
        ids = [node.id for node in self.nodes]
        if len(set(ids)) != len(ids):
            raise ValueError("Node ids must be unique")
        known = set(ids)
        for node in self.nodes:
            config_model = NODE_CONFIGS[node.type]
            try:
                config_model.model_validate(node.config)
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid config for node {node.id}: {exc.errors()[0]['msg']}"
                ) from None

        predecessors: dict[str, list[str]] = {node_id: [] for node_id in ids}
        successors: dict[str, str] = {}
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
            predecessors[edge.to].append(edge.from_node)
            if edge.from_node in successors:
                raise ValueError("A node can have at most one outgoing edge in P4-S1")
            successors[edge.from_node] = edge.to

        for node_id, incoming in predecessors.items():
            if len(incoming) > 1:
                raise ValueError(
                    f"A node can have at most one incoming edge in P4-S1 (node {node_id})"
                )
        entries = [node_id for node_id in ids if not predecessors[node_id]]
        if len(entries) != 1:
            raise ValueError("A workflow must have exactly one entry node")

        current: str | None = entries[0]
        visited = 0
        while current is not None:
            visited += 1
            if visited > len(ids):
                raise ValueError("Workflow contains a cycle")
            current = successors.get(current)
        if visited != len(ids):
            raise ValueError("Every node must be reachable from the entry node")
        return self

    def ordered_nodes(self) -> list[WorkflowNode]:
        order: list[WorkflowNode] = []
        by_id = {node.id: node for node in self.nodes}
        successors = {edge.from_node: edge.to for edge in self.edges}
        entry = next(
            node.id for node in self.nodes if node.id not in {edge.to for edge in self.edges}
        )
        current: str | None = entry
        while current is not None:
            order.append(by_id[current])
            current = successors.get(current)
        return order


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
