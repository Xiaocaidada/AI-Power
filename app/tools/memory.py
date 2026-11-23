from uuid import UUID

from pydantic import BaseModel, Field

from app.db import SessionLocal
from app.models import Project
from app.services.memories import (
    MemoryError,
    create_memory,
    find_memory_by_title,
    record_memory_usage,
    select_memories,
    update_memory,
)
from app.services.memory_permissions import project_allows_agent_writes
from app.tools.base import ToolContext, ToolError, ToolSpec

MEMORY_OUTPUT_MAX_CHARS = 3000


class MemorySearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)


class MemorySaveArgs(BaseModel):
    title: str = Field(default="", max_length=120)
    content: str = Field(min_length=1, max_length=5000)
    category: str = Field(default="fact", max_length=30)


async def memory_search(context: ToolContext, args: MemorySearchArgs) -> str:
    access = context.memory_access
    if access is None or not access.read_scopes:
        raise ToolError(
            "memory_read_denied", "This agent is not allowed to read long-term memory"
        )
    async with SessionLocal() as session:
        selection = await select_memories(
            session,
            workspace_id=context.workspace_id,
            user_id=context.user_id,
            agent_id=context.agent_id,
            project_id=context.project_id,
            query=args.query,
            limit=args.limit,
            max_chars=MEMORY_OUTPUT_MAX_CHARS,
            allowed_scopes=access.read_scopes,
        )
        if selection.items:
            await record_memory_usage(
                session,
                workspace_id=context.workspace_id,
                user_id=context.user_id,
                memories=[
                    (item.memory, item.score, item.injected_chars)
                    for item in selection.items
                ],
                context_type="agent",
                context_id=(
                    str(context.conversation_id)
                    if context.conversation_id is not None
                    else None
                ),
                provider_id=None,
                model=None,
            )
        await session.commit()
    if not selection.items:
        return "No matching long-term memories were found."
    lines = []
    for item in selection.items:
        scope = item.memory.scope_type
        label = f"[{item.memory.category}/{scope}]"
        if item.memory.title:
            label += f" {item.memory.title}:"
        lines.append(f"- {label} {item.memory.content}")
    return "\n".join(lines)


async def memory_save(context: ToolContext, args: MemorySaveArgs) -> str:
    access = context.memory_access
    if access is None or not access.write:
        raise ToolError(
            "memory_write_denied", "This agent is not allowed to write long-term memory"
        )
    scope_type = access.write_scope
    project_id: UUID | None = None
    agent_id: UUID | None = None
    if scope_type == "project":
        project_id = context.project_id
        if project_id is None:
            raise ToolError(
                "memory_write_denied", "No project context is available for project memory"
            )
    elif scope_type == "agent":
        agent_id = context.agent_id
        if agent_id is None:
            raise ToolError(
                "memory_write_denied", "No agent context is available for agent memory"
            )
    status = "candidate" if access.write_mode == "candidate" else "active"
    async with SessionLocal() as session:
        if project_id is not None:
            project = await session.get(Project, project_id)
            if (
                project is None
                or project.workspace_id != context.workspace_id
                or project.archived_at is not None
                or not project_allows_agent_writes(project)
            ):
                raise ToolError(
                    "memory_write_denied",
                    "This project does not allow agent memory writes",
                )
        try:
            existing = None
            if access.write_mode == "upsert":
                existing = await find_memory_by_title(
                    session,
                    workspace_id=context.workspace_id,
                    user_id=context.user_id,
                    title=args.title,
                    scope_type=scope_type,
                    project_id=project_id,
                    agent_id=agent_id,
                )
            if existing is not None:
                memory = await update_memory(
                    session,
                    existing,
                    title=args.title or existing.title,
                    content=args.content,
                    status=status,
                    change_reason="agent update",
                    changed_by=context.user_id,
                )
                action = "updated"
            else:
                memory = await create_memory(
                    session,
                    workspace_id=context.workspace_id,
                    user_id=context.user_id,
                    content=args.content,
                    title=args.title,
                    category=args.category,
                    status=status,
                    scope_type=scope_type,
                    project_id=project_id,
                    agent_id=agent_id,
                    source="agent",
                    source_type="agent",
                    source_id=(
                        str(context.conversation_id)
                        if context.conversation_id is not None
                        else None
                    ),
                    confidence=0.8,
                )
                action = "saved"
        except MemoryError as exc:
            raise ToolError(exc.code, exc.message) from None
        saved_title = memory.title
        await session.commit()
    if status == "candidate":
        return f"memory candidate {action}: {saved_title} (waiting for user confirmation)"
    return f"memory {action}: {saved_title}"


def build_memory_search_tool() -> ToolSpec:
    return ToolSpec(
        name="memory_search",
        description=(
            "Search the user's long-term memories that this agent is allowed to read "
            "and return the most relevant notes."
        ),
        args_model=MemorySearchArgs,
        handler=memory_search,
    )


def build_memory_save_tool() -> ToolSpec:
    return ToolSpec(
        name="memory_save",
        description=(
            "Save a durable user preference, project fact or lesson to long-term "
            "memory. Writes follow the agent's configured permission scope."
        ),
        args_model=MemorySaveArgs,
        handler=memory_save,
    )