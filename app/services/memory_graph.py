"""Memory relation graph queries and manual relation target validation."""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentMemory, CustomAgent, Document, MemoryRelation, Project
from app.services.memory_linking import auto_link_memory

GRAPH_LIMIT = 300
REBUILD_LIMIT = 500
NODE_TYPES = {"memory", "project", "agent", "document"}


class GraphError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _node_id(node_type: str, node_id: UUID) -> str:
    return f"{node_type}:{node_id}"


async def validate_relation_target(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    to_type: str,
    to_id: UUID,
) -> None:
    if to_type not in NODE_TYPES:
        raise GraphError("invalid_relation", "Invalid relation target type")
    if to_type == "memory":
        row = await session.get(AgentMemory, to_id)
        if (
            row is None
            or row.workspace_id != workspace_id
            or row.user_id != user_id
        ):
            raise GraphError("not_found", "Memory not found")
        return
    if to_type == "project":
        row = await session.get(Project, to_id)
        if row is None or row.workspace_id != workspace_id or row.archived_at is not None:
            raise GraphError("not_found", "Project not found")
        return
    if to_type == "agent":
        row = await session.get(CustomAgent, to_id)
        if row is None or row.workspace_id != workspace_id or row.archived_at is not None:
            raise GraphError("not_found", "Agent not found")
        return
    row = await session.get(Document, to_id)
    if (
        row is None
        or row.workspace_id != workspace_id
        or row.deleted_at is not None
    ):
        raise GraphError("not_found", "Document not found")


def _memory_node(memory: AgentMemory) -> dict[str, object]:
    return {
        "id": _node_id("memory", memory.id),
        "type": "memory",
        "label": memory.title or memory.content[:60],
        "memory_id": memory.id,
        "ref_id": memory.id,
        "category": memory.category,
        "scope_type": memory.scope_type,
        "status": memory.status,
        "pinned": memory.pinned,
        "importance": memory.importance,
    }


async def list_memory_graph(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    *,
    query: str = "",
    scope_type: str | None = None,
    project_id: UUID | None = None,
    agent_id: UUID | None = None,
    category: str | None = None,
    status: str = "active",
    limit: int = GRAPH_LIMIT,
    focus_id: UUID | None = None,
) -> dict[str, object]:
    conditions = [
        AgentMemory.workspace_id == workspace_id,
        AgentMemory.user_id == user_id,
    ]
    if status != "all":
        conditions.append(AgentMemory.status == status)
    if scope_type is not None:
        conditions.append(AgentMemory.scope_type == scope_type)
    if project_id is not None:
        conditions.append(AgentMemory.project_id == project_id)
    if agent_id is not None:
        conditions.append(AgentMemory.agent_id == agent_id)
    if category is not None:
        conditions.append(AgentMemory.category == category)
    if query.strip():
        term = f"%{query.strip()}%"
        conditions.append(
            or_(AgentMemory.title.ilike(term), AgentMemory.content.ilike(term))
        )
    memories = list(
        (
            await session.execute(
                select(AgentMemory)
                .where(*conditions)
                .order_by(
                    AgentMemory.pinned.desc(),
                    AgentMemory.importance.desc(),
                    AgentMemory.updated_at.desc(),
                )
                .limit(max(1, min(limit, GRAPH_LIMIT)))
            )
        ).scalars()
    )
    memory_by_id = {memory.id: memory for memory in memories}
    nodes: dict[str, dict[str, object]] = {
        _node_id("memory", memory.id): _memory_node(memory)
        for memory in memories
    }
    edges: list[dict[str, object]] = []
    if memories:
        relations = list(
            (
                await session.execute(
                    select(MemoryRelation).where(
                        MemoryRelation.workspace_id == workspace_id,
                        MemoryRelation.user_id == user_id,
                        or_(
                            (
                                (MemoryRelation.from_type == "memory")
                                & MemoryRelation.from_id.in_(memory_by_id)
                            ),
                            (
                                (MemoryRelation.to_type == "memory")
                                & MemoryRelation.to_id.in_(memory_by_id)
                            ),
                        ),
                    )
                )
            ).scalars()
        )
        project_ids = {
            relation.to_id
            for relation in relations
            if relation.to_type == "project"
        } | {
            relation.from_id
            for relation in relations
            if relation.from_type == "project"
        }
        agent_ids = {
            relation.to_id
            for relation in relations
            if relation.to_type == "agent"
        } | {
            relation.from_id
            for relation in relations
            if relation.from_type == "agent"
        }
        document_ids = {
            relation.to_id
            for relation in relations
            if relation.to_type == "document"
        } | {
            relation.from_id
            for relation in relations
            if relation.from_type == "document"
        }
        projects = {
            row.id: row
            for row in (
                await session.execute(
                    select(Project).where(
                        Project.id.in_(project_ids),
                        Project.workspace_id == workspace_id,
                    )
                )
            ).scalars()
        } if project_ids else {}
        agents = {
            row.id: row
            for row in (
                await session.execute(
                    select(CustomAgent).where(
                        CustomAgent.id.in_(agent_ids),
                        CustomAgent.workspace_id == workspace_id,
                    )
                )
            ).scalars()
        } if agent_ids else {}
        documents = {
            row.id: row
            for row in (
                await session.execute(
                    select(Document).where(
                        Document.id.in_(document_ids),
                        Document.workspace_id == workspace_id,
                        Document.deleted_at.is_(None),
                    )
                )
            ).scalars()
        } if document_ids else {}

        for project in projects.values():
            nodes[_node_id("project", project.id)] = {
                "id": _node_id("project", project.id),
                "type": "project",
                "label": project.name,
                "memory_id": None,
                "ref_id": project.id,
                "category": None,
                "scope_type": None,
                "status": None,
                "pinned": False,
                "importance": None,
            }
        for agent in agents.values():
            nodes[_node_id("agent", agent.id)] = {
                "id": _node_id("agent", agent.id),
                "type": "agent",
                "label": agent.name,
                "memory_id": None,
                "ref_id": agent.id,
                "category": None,
                "scope_type": None,
                "status": None,
                "pinned": False,
                "importance": None,
            }
        for document in documents.values():
            nodes[_node_id("document", document.id)] = {
                "id": _node_id("document", document.id),
                "type": "document",
                "label": document.filename,
                "memory_id": None,
                "ref_id": document.id,
                "category": None,
                "scope_type": None,
                "status": None,
                "pinned": False,
                "importance": None,
            }
        for relation in relations:
            source = _node_id(relation.from_type, relation.from_id)
            target = _node_id(relation.to_type, relation.to_id)
            if source not in nodes or target not in nodes:
                continue
            edges.append(
                {
                    "id": str(relation.id),
                    "source": source,
                    "target": target,
                    "relation_type": relation.relation_type,
                    "confidence": relation.confidence,
                    "basis": relation.basis,
                    "source_kind": relation.source,
                }
            )

    if focus_id is not None:
        focus_node = _node_id("memory", focus_id)
        if focus_node not in nodes:
            nodes = {}
            edges = []
        else:
            visible = {focus_node}
            for edge in edges:
                if edge["source"] == focus_node:
                    visible.add(str(edge["target"]))
                elif edge["target"] == focus_node:
                    visible.add(str(edge["source"]))
            nodes = {key: value for key, value in nodes.items() if key in visible}
            edges = [
                edge
                for edge in edges
                if edge["source"] in visible and edge["target"] in visible
            ]

    degree: dict[str, int] = {key: 0 for key in nodes}
    for edge in edges:
        degree[str(edge["source"])] = degree.get(str(edge["source"]), 0) + 1
        degree[str(edge["target"])] = degree.get(str(edge["target"]), 0) + 1
    memory_nodes = [node for node in nodes.values() if node["type"] == "memory"]
    external_nodes = [node for node in nodes.values() if node["type"] != "memory"]
    return {
        "nodes": sorted(nodes.values(), key=lambda node: str(node["id"])),
        "edges": sorted(edges, key=lambda edge: str(edge["id"])),
        "stats": {
            "memories": len(memory_nodes),
            "external": len(external_nodes),
            "relations": len(edges),
            "orphans": sum(
                1 for node in memory_nodes if degree.get(str(node["id"]), 0) == 0
            ),
        },
    }


async def rebuild_memory_graph(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> dict[str, int]:
    memories = list(
        (
            await session.execute(
                select(AgentMemory)
                .where(
                    AgentMemory.workspace_id == workspace_id,
                    AgentMemory.user_id == user_id,
                    AgentMemory.status.in_(("active", "candidate")),
                    AgentMemory.enabled.is_(True),
                )
                .order_by(AgentMemory.updated_at.desc())
                .limit(REBUILD_LIMIT)
            )
        ).scalars()
    )
    created = 0
    for memory in memories:
        created += await auto_link_memory(session, memory)
    await session.flush()
    return {"created": created, "memories": len(memories)}