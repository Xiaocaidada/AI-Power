import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentSpec
from app.agents.registry import MATH_PROMPT, RETRIEVAL_PROMPT, SUPERVISOR_PROMPT
from app.models import (
    AgentFavorite,
    Conversation,
    CustomAgent,
    KnowledgeBase,
    Message,
    ModelCatalog,
    PluginDefinition,
    User,
    Workflow,
    WorkflowRun,
    WorkflowRunEvent,
    WorkflowVersion,
)
from app.services.agent_reviews import mask_email
from app.services.agent_tools import AgentToolError, validate_agent_tools
from app.services.generation import normalize_generation_settings
from app.services.memory_permissions import normalize_agent_permissions

AGENT_TOOL_NAMES = frozenset(
    {
        "kb_search",
        "current_time",
        "calculator",
        "memory_search",
        "memory_save",
        "project_files",
    }
)
AGENT_MODES = frozenset({"autonomous", "workflow", "hybrid"})
BUILTIN_AGENT_IDS = frozenset({"builtin:supervisor", "builtin:retrieval", "builtin:math"})
SLUG_PATTERN = re.compile(r"[^a-z0-9]+")

BUILTIN_AGENTS: dict[str, dict[str, Any]] = {
    "builtin:supervisor": {
        "name": "Supervisor",
        "description": "Decomposes tasks and delegates to retrieval and math specialists.",
        "category": "orchestration",
        "instructions": SUPERVISOR_PROMPT,
        "tools": ["delegate_to_agent"],
    },
    "builtin:retrieval": {
        "name": "Retrieval",
        "description": "Searches the workspace knowledge base and returns cited material.",
        "category": "research",
        "instructions": RETRIEVAL_PROMPT,
        "tools": ["kb_search", "current_time"],
    },
    "builtin:math": {
        "name": "Math",
        "description": "Performs arithmetic with the AST-whitelisted calculator.",
        "category": "analysis",
        "instructions": MATH_PROMPT,
        "tools": ["calculator"],
    },
}


class CustomAgentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def can_manage(agent: CustomAgent, user_id: UUID, workspace_role: str) -> bool:
    return agent.owner_user_id == user_id or workspace_role == "owner"


def _accessible(agent: CustomAgent, user_id: UUID) -> bool:
    return agent.owner_user_id == user_id or agent.visibility == "shared"


def custom_agent_name(agent_id: UUID) -> str:
    return f"custom-{agent_id}"


def build_agent_spec(agent: CustomAgent, extra_tools: tuple[str, ...] = ()) -> AgentSpec:
    tools = list(agent.tools)
    if (agent.default_kb_id is not None or agent.kb_ids) and "kb_search" not in tools:
        tools.append("kb_search")
    permissions = normalize_agent_permissions(
        agent.memory_permissions, agent.memory_enabled
    )
    if agent.memory_enabled and "memory_search" not in tools:
        tools.append("memory_search")
    if permissions["write"] and "memory_save" not in tools:
        tools.append("memory_save")
    tools = list(dict.fromkeys([*tools, *extra_tools]))
    return AgentSpec(
        name=custom_agent_name(agent.id),
        system_prompt=agent.instructions,
        tools=tuple(tools),
    )


async def list_custom_agents(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    *,
    search: str | None = None,
    category: str | None = None,
    include_archived: bool = False,
    scope: str = "all",
) -> list[CustomAgent]:
    conditions = [
        CustomAgent.workspace_id == workspace_id,
        or_(CustomAgent.owner_user_id == user_id, CustomAgent.visibility == "shared"),
    ]
    if not include_archived:
        conditions.append(CustomAgent.archived_at.is_(None))
    if category:
        conditions.append(CustomAgent.category == category)
    if scope == "mine":
        conditions.append(CustomAgent.owner_user_id == user_id)
    elif scope == "created":
        conditions.extend(
            [
                CustomAgent.owner_user_id == user_id,
                CustomAgent.source_agent_id.is_(None),
            ]
        )
    elif scope == "copied":
        conditions.extend(
            [
                CustomAgent.owner_user_id == user_id,
                CustomAgent.source_agent_id.is_not(None),
            ]
        )
    elif scope == "published":
        conditions.extend(
            [
                CustomAgent.owner_user_id == user_id,
                CustomAgent.published.is_(True),
            ]
        )
    elif scope == "favorites":
        conditions.append(
            exists(
                select(AgentFavorite.id).where(
                    AgentFavorite.agent_id == CustomAgent.id,
                    AgentFavorite.user_id == user_id,
                )
            )
        )
    if search:
        term = f"%{search.strip()}%"
        conditions.append(
            or_(CustomAgent.name.ilike(term), CustomAgent.description.ilike(term))
        )
    result = await session.execute(
        select(CustomAgent)
        .where(*conditions)
        .order_by(CustomAgent.updated_at.desc(), CustomAgent.name)
    )
    return list(result.scalars())


async def increment_agent_usage(session: AsyncSession, agent: CustomAgent) -> int:
    agent.usage_count += 1
    await session.flush()
    return agent.usage_count


async def get_custom_agent(
    session: AsyncSession,
    workspace_id: UUID,
    agent_id: UUID,
    user_id: UUID,
    *,
    include_archived: bool = False,
) -> CustomAgent:
    conditions = [CustomAgent.id == agent_id, CustomAgent.workspace_id == workspace_id]
    if not include_archived:
        conditions.append(CustomAgent.archived_at.is_(None))
    agent = (
        await session.execute(select(CustomAgent).where(*conditions))
    ).scalar_one_or_none()
    if agent is None or not _accessible(agent, user_id):
        raise CustomAgentError("not_found", "Agent not found")
    return agent


async def agent_conversation_count(session: AsyncSession, agent_id: UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Conversation)
                .where(
                    Conversation.custom_agent_id == agent_id,
                    Conversation.archived_at.is_(None),
                )
            )
        ).scalar_one()
    )


async def validate_tools(
    session: AsyncSession, tools: list[str]
) -> list[str]:
    try:
        return await validate_agent_tools(session, tools)
    except AgentToolError as exc:
        raise CustomAgentError(exc.code, exc.message) from None


def _dedupe_ids(values: list[object] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        normalized = str(value)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


async def _validate_kb_ids(
    session: AsyncSession, workspace_id: UUID, values: list[object] | None
) -> list[str]:
    ids = _dedupe_ids(values)
    if not ids:
        return []
    parsed: list[UUID] = []
    for value in ids:
        try:
            parsed.append(UUID(value))
        except ValueError:
            raise CustomAgentError("invalid_knowledge_base", "Invalid knowledge base") from None
    rows = (
        await session.execute(
            select(KnowledgeBase.id).where(
                KnowledgeBase.id.in_(parsed),
                KnowledgeBase.workspace_id == workspace_id,
                KnowledgeBase.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    if len(set(rows)) != len(set(parsed)):
        raise CustomAgentError("invalid_knowledge_base", "Knowledge base not found")
    return ids


async def _validate_workflow_id(
    session: AsyncSession, workspace_id: UUID, workflow_id: object | None
) -> UUID | None:
    if workflow_id is None:
        return None
    try:
        parsed = UUID(str(workflow_id))
    except ValueError:
        raise CustomAgentError("invalid_workflow", "Invalid workflow") from None
    row = (
        await session.execute(
            select(Workflow.id).where(
                Workflow.id == parsed,
                Workflow.workspace_id == workspace_id,
                Workflow.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise CustomAgentError("invalid_workflow", "Workflow not found")
    return row


def _validate_mode(mode: str, workflow_id: UUID | None) -> str:
    if mode not in AGENT_MODES:
        raise CustomAgentError("invalid_mode", "Unknown agent mode")
    if mode in {"workflow", "hybrid"} and workflow_id is None:
        raise CustomAgentError("workflow_required", "This mode requires a workflow")
    return mode


async def validate_agent_values(
    session: AsyncSession, workspace_id: UUID, values: dict[str, Any]
) -> dict[str, Any]:
    result = dict(values)
    if "tools" in result and result["tools"] is not None:
        result["tools"] = await validate_tools(session, list(result["tools"]))
    if (
        "generation_settings" in result
        and result["generation_settings"] is not None
    ):
        result["generation_settings"] = normalize_generation_settings(
            dict(result["generation_settings"])
        )
    if "kb_ids" in result:
        result["kb_ids"] = await _validate_kb_ids(session, workspace_id, result["kb_ids"])
    if "workflow_id" in result:
        result["workflow_id"] = await _validate_workflow_id(
            session, workspace_id, result["workflow_id"]
        )
    if "mode" in result or "workflow_id" in result:
        result["mode"] = _validate_mode(
            str(result.get("mode", "autonomous")),
            result.get("workflow_id"),
        )
    return result


async def create_custom_agent(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    owner_user_id: UUID,
    values: dict[str, Any],
) -> CustomAgent:
    values = await validate_agent_values(session, workspace_id, values)
    existing = (
        await session.execute(
            select(CustomAgent.id).where(
                CustomAgent.workspace_id == workspace_id,
                CustomAgent.name == values["name"],
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise CustomAgentError("duplicate", "Agent name already exists")
    agent = CustomAgent(workspace_id=workspace_id, owner_user_id=owner_user_id, **values)
    session.add(agent)
    await session.flush()
    return agent


async def update_custom_agent(
    session: AsyncSession, agent: CustomAgent, values: dict[str, Any]
) -> CustomAgent:
    merged = {
        "mode": agent.mode,
        "workflow_id": agent.workflow_id,
        "kb_ids": list(agent.kb_ids),
        **values,
    }
    validated = await validate_agent_values(session, agent.workspace_id, merged)
    for key in values:
        setattr(agent, key, validated.get(key, values[key]))
    await session.flush()
    return agent


async def archive_custom_agent(session: AsyncSession, agent: CustomAgent) -> None:
    agent.archived_at = datetime.now(UTC)
    await session.flush()


def _sanitize_workflow_definition(definition: dict[str, Any]) -> dict[str, Any]:
    copied = json.loads(json.dumps(definition))
    for node in copied.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_type = node.get("type")
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        if node_type == "kb_search":
            config["kb_ids"] = []
        elif node_type == "agent":
            config.pop("agent_id", None)
            config.pop("project_id", None)
            config["kb_ids"] = []
        elif node_type == "http":
            # Never publish outbound credentials or request payloads; copies must
            # reconfigure their own endpoint.
            config["url"] = ""
            config["headers"] = {}
            config["body"] = ""
        elif node_type == "mcp":
            config.pop("server_id", None)
            config["arguments"] = {}
        elif node_type == "memory_read":
            config["query"] = ""
            config.pop("project_id", None)
            config.pop("agent_id", None)
        elif node_type == "memory_write":
            config["title"] = ""
            config["content"] = ""
            config.pop("project_id", None)
            config.pop("agent_id", None)
    return copied


async def _default_model_pair(session: AsyncSession) -> tuple[str, str] | None:
    row = (
        await session.execute(
            select(ModelCatalog)
            .where(ModelCatalog.enabled.is_(True))
            .order_by(ModelCatalog.priority, ModelCatalog.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return row.provider_id, row.model_id


def _fill_agent_models(
    definition: dict[str, Any], pair: tuple[str, str] | None
) -> dict[str, Any]:
    if pair is None:
        return definition
    provider_id, model = pair
    for node in definition.get("nodes", []):
        if not isinstance(node, dict) or node.get("type") != "agent":
            continue
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        if not config.get("provider_id") or not config.get("model"):
            config["provider_id"] = provider_id
            config["model"] = model
    return definition


async def _latest_workflow_version(
    session: AsyncSession, workflow_id: UUID | None
) -> WorkflowVersion | None:
    if workflow_id is None:
        return None
    return (
        await session.execute(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _kb_names(session: AsyncSession, ids: list[str]) -> list[str]:
    parsed = [UUID(item) for item in ids if item]
    if not parsed:
        return []
    rows = (
        await session.execute(
            select(KnowledgeBase.name).where(KnowledgeBase.id.in_(parsed))
        )
    ).scalars().all()
    return list(rows)


async def _plugin_names(session: AsyncSession, ids: list[str]) -> list[str]:
    parsed = [UUID(item) for item in ids if item]
    if not parsed:
        return []
    rows = (
        await session.execute(
            select(PluginDefinition.name).where(PluginDefinition.id.in_(parsed))
        )
    ).scalars().all()
    return list(rows)


async def build_published_snapshot(
    session: AsyncSession, agent: CustomAgent
) -> dict[str, Any]:
    workflow_name = ""
    workflow_definition: dict[str, Any] | None = None
    if agent.workflow_id is not None:
        workflow = await session.get(Workflow, agent.workflow_id)
        if workflow is not None and workflow.deleted_at is None:
            workflow_name = workflow.name
            version = await _latest_workflow_version(session, workflow.id)
            if version is not None:
                workflow_definition = _sanitize_workflow_definition(version.definition)
    default_kb = [str(agent.default_kb_id)] if agent.default_kb_id else []
    kb_ids = list(dict.fromkeys([*agent.kb_ids, *default_kb]))
    return {
        "name": agent.name,
        "description": agent.description,
        "instructions": agent.instructions,
        "category": agent.category,
        "mode": agent.mode,
        "icon": agent.icon,
        "cover_url": agent.cover_url,
        "welcome_message": agent.welcome_message,
        "examples": list(agent.examples),
        "usage_instructions": agent.usage_instructions,
        "generation_settings": dict(agent.generation_settings),
        "tools": list(agent.tools),
        "model_hint": agent.default_model or "",
        "kb_requirements": await _kb_names(session, kb_ids),
        "plugin_requirements": await _plugin_names(session, list(agent.plugin_ids)),
        "workflow": (
            {"name": workflow_name, "definition": workflow_definition}
            if workflow_definition is not None
            else None
        ),
        "allow_copy": agent.allow_copy,
        "show_structure": agent.show_structure,
    }


def slugify_agent(name: str) -> str:
    base = SLUG_PATTERN.sub("-", name.casefold()).strip("-")[:60]
    return base or "agent"


async def publish_custom_agent(
    session: AsyncSession,
    agent: CustomAgent,
    *,
    slug: str,
    allow_copy: bool,
    show_structure: bool,
) -> CustomAgent:
    candidate = slugify_agent(slug or agent.name)
    other = (
        await session.execute(
            select(CustomAgent.id).where(
                CustomAgent.public_slug == candidate,
                CustomAgent.id != agent.id,
            )
        )
    ).scalar_one_or_none()
    if other is not None:
        raise CustomAgentError("slug_taken", "Public slug is already in use")
    agent.allow_copy = allow_copy
    agent.show_structure = show_structure
    agent.published_snapshot = await build_published_snapshot(session, agent)
    agent.public_slug = candidate
    agent.published = True
    agent.published_at = datetime.now(UTC)
    await session.flush()
    return agent


async def unpublish_custom_agent(session: AsyncSession, agent: CustomAgent) -> None:
    agent.published = False
    agent.published_at = None
    await session.flush()


def public_agent_summary(
    agent: CustomAgent,
    *,
    owner_email: str = "",
    owner_role: str = "user",
) -> dict[str, Any]:
    return {
        "id": agent.id,
        "slug": agent.public_slug or "",
        "name": agent.name,
        "description": agent.description,
        "icon": agent.icon,
        "cover_url": agent.cover_url,
        "category": agent.category,
        "mode": agent.mode,
        "featured": agent.featured,
        "official": owner_role == "admin",
        "publisher": mask_email(owner_email) if owner_email else "",
        "usage_count": agent.usage_count,
        "favorite_count": agent.favorite_count,
        "copy_count": agent.copy_count,
        "rating_avg": agent.rating_avg,
        "rating_count": agent.rating_count,
        "allow_copy": agent.allow_copy,
        "published_at": agent.published_at,
    }


def public_agent_detail(
    agent: CustomAgent,
    *,
    owner_email: str = "",
    owner_role: str = "user",
) -> dict[str, Any]:
    snapshot = agent.published_snapshot or {}
    result = public_agent_summary(
        agent, owner_email=owner_email, owner_role=owner_role
    )
    result.update(
        {
            "welcome_message": snapshot.get("welcome_message", ""),
            "examples": snapshot.get("examples", []),
            "usage_instructions": snapshot.get("usage_instructions", ""),
            "tools": snapshot.get("tools", []),
            "model_hint": snapshot.get("model_hint", ""),
            "kb_requirements": snapshot.get("kb_requirements", []),
            "plugin_requirements": snapshot.get("plugin_requirements", []),
        }
    )
    if agent.show_structure:
        result["instructions"] = snapshot.get("instructions", "")
        result["workflow"] = snapshot.get("workflow")
    return result


async def list_published_agents(
    session: AsyncSession,
    *,
    search: str | None = None,
    category: str | None = None,
    sort: str = "newest",
    featured_only: bool = False,
    official_only: bool = False,
    publisher: str | None = None,
) -> list[tuple[CustomAgent, str, str]]:
    conditions = [
        CustomAgent.published.is_(True),
        CustomAgent.archived_at.is_(None),
        CustomAgent.enabled.is_(True),
    ]
    if category:
        conditions.append(CustomAgent.category == category)
    if featured_only:
        conditions.append(CustomAgent.featured.is_(True))
    if official_only:
        conditions.append(User.role == "admin")
    if search and search.strip():
        term = f"%{search.strip()}%"
        conditions.append(
            or_(CustomAgent.name.ilike(term), CustomAgent.description.ilike(term))
        )
    if sort == "popular":
        order = (CustomAgent.usage_count.desc(), CustomAgent.published_at.desc())
    elif sort == "featured":
        order = (
            CustomAgent.featured.desc(),
            CustomAgent.published_at.desc(),
            CustomAgent.id.desc(),
        )
    else:
        order = (CustomAgent.published_at.desc(), CustomAgent.id.desc())
    statement = (
        select(CustomAgent, User.email, User.role)
        .join(User, User.id == CustomAgent.owner_user_id)
        .where(*conditions)
        .order_by(*order)
    )
    if not publisher:
        statement = statement.limit(100)
    rows = (await session.execute(statement)).all()
    result = [(row[0], row[1], row[2]) for row in rows]
    if publisher:
        result = [row for row in result if mask_email(row[1]) == publisher]
    return result[:100]


async def published_agent_facets(session: AsyncSession) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(
                CustomAgent.category,
                CustomAgent.featured,
                User.email,
                User.role,
            )
            .join(User, User.id == CustomAgent.owner_user_id)
            .where(
                CustomAgent.published.is_(True),
                CustomAgent.archived_at.is_(None),
                CustomAgent.enabled.is_(True),
            )
        )
    ).all()
    categories: dict[str, int] = {}
    publishers: dict[str, int] = {}
    official = 0
    featured = 0
    for category, is_featured, email, role in rows:
        categories[category] = categories.get(category, 0) + 1
        publisher = mask_email(email)
        publishers[publisher] = publishers.get(publisher, 0) + 1
        if role == "admin":
            official += 1
        if is_featured:
            featured += 1

    def _ranked(values: dict[str, int]) -> list[dict[str, Any]]:
        return [
            {"value": value, "count": count}
            for value, count in sorted(
                values.items(), key=lambda item: (-item[1], item[0])
            )
        ]

    return {
        "total": len(rows),
        "official": official,
        "featured": featured,
        "categories": _ranked(categories),
        "publishers": _ranked(publishers),
    }


async def get_published_agent(session: AsyncSession, slug: str) -> CustomAgent:
    agent = (
        await session.execute(
            select(CustomAgent).where(
                CustomAgent.public_slug == slug,
                CustomAgent.published.is_(True),
                CustomAgent.archived_at.is_(None),
                CustomAgent.enabled.is_(True),
            )
        )
    ).scalar_one_or_none()
    if agent is None:
        raise CustomAgentError("not_found", "Agent not found")
    return agent


async def _unique_copy_name(
    session: AsyncSession, workspace_id: UUID, source_name: str
) -> str:
    base = f"{source_name} (copy)"[:110]
    candidate = base
    index = 2
    while (
        await session.execute(
            select(CustomAgent.id).where(
                CustomAgent.workspace_id == workspace_id,
                CustomAgent.name == candidate,
            )
        )
    ).scalar_one_or_none() is not None:
        candidate = f"{base} {index}"[:110]
        index += 1
    return candidate


async def _create_workflow_copy(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    name: str,
    description: str,
    definition: dict[str, Any],
) -> UUID:
    cloned = Workflow(
        workspace_id=workspace_id,
        created_by=user_id,
        name=f"{name} (copy)"[:120],
        description=description,
    )
    session.add(cloned)
    await session.flush()
    pair = await _default_model_pair(session)
    session.add(
        WorkflowVersion(
            workflow_id=cloned.id,
            version=1,
            definition=_fill_agent_models(
                _sanitize_workflow_definition(definition), pair
            ),
        )
    )
    await session.flush()
    return cloned.id


async def _clone_workflow(
    session: AsyncSession,
    source_workflow_id: UUID,
    *,
    workspace_id: UUID,
    user_id: UUID,
) -> UUID | None:
    workflow = await session.get(Workflow, source_workflow_id)
    if workflow is None or workflow.deleted_at is not None:
        return None
    version = await _latest_workflow_version(session, workflow.id)
    if version is None:
        return None
    return await _create_workflow_copy(
        session,
        workspace_id=workspace_id,
        user_id=user_id,
        name=workflow.name,
        description=workflow.description,
        definition=version.definition,
    )


async def copy_published_agent(
    session: AsyncSession,
    source: CustomAgent,
    *,
    workspace_id: UUID,
    user_id: UUID,
    require_published: bool = True,
) -> CustomAgent:
    if require_published and (not source.published or not source.allow_copy):
        raise CustomAgentError("copy_disabled", "This agent does not allow copying")
    snapshot = source.published_snapshot if require_published else None
    workflow_id = None
    if snapshot is not None:
        workflow_snapshot = snapshot.get("workflow") or {}
        definition = (
            workflow_snapshot.get("definition")
            if isinstance(workflow_snapshot, dict)
            else None
        )
        if isinstance(definition, dict):
            workflow_id = await _create_workflow_copy(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
                name=str(workflow_snapshot.get("name") or source.name),
                description=source.description,
                definition=definition,
            )
    elif source.workflow_id is not None:
        workflow_id = await _clone_workflow(
            session,
            source.workflow_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
    values = snapshot or {}
    agent = CustomAgent(
        workspace_id=workspace_id,
        owner_user_id=user_id,
        name=await _unique_copy_name(session, workspace_id, source.name),
        description=str(values.get("description", source.description)),
        instructions=str(values.get("instructions", source.instructions)),
        category=str(values.get("category", source.category)),
        mode=str(values.get("mode", source.mode)),
        icon=str(values.get("icon", source.icon)),
        cover_url=str(values.get("cover_url", source.cover_url)),
        welcome_message=str(values.get("welcome_message", source.welcome_message)),
        examples=list(values.get("examples", source.examples) or []),
        usage_instructions=str(
            values.get("usage_instructions", source.usage_instructions)
        ),
        generation_settings=dict(
            values.get("generation_settings", source.generation_settings) or {}
        ),
        kb_ids=[],
        tools=list(values.get("tools", source.tools) or []),
        plugin_ids=[],
        workflow_id=workflow_id,
        visibility="private",
        memory_enabled=source.memory_enabled,
        memory_permissions=dict(source.memory_permissions or {}),
        source_agent_id=source.id,
        allow_copy=True,
        show_structure=source.show_structure,
    )
    session.add(agent)
    source.copy_count += 1
    await session.flush()
    return agent


async def set_agent_favorite(
    session: AsyncSession,
    agent: CustomAgent,
    user_id: UUID,
    favorite: bool,
) -> bool:
    existing = (
        await session.execute(
            select(AgentFavorite).where(
                AgentFavorite.agent_id == agent.id,
                AgentFavorite.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if favorite and existing is None:
        session.add(AgentFavorite(agent_id=agent.id, user_id=user_id))
        agent.favorite_count += 1
    elif not favorite and existing is not None:
        await session.delete(existing)
        agent.favorite_count = max(0, agent.favorite_count - 1)
    await session.flush()
    return favorite


async def set_agent_featured(
    session: AsyncSession, agent: CustomAgent, featured: bool
) -> CustomAgent:
    agent.featured = featured
    await session.flush()
    return agent


def _clip(text: str, limit: int = 500) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def list_agent_runs(
    session: AsyncSession,
    agent: CustomAgent,
    workspace_id: UUID,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    conversations = list(
        (
            await session.execute(
                select(Conversation)
                .where(
                    Conversation.custom_agent_id == agent.id,
                    Conversation.workspace_id == workspace_id,
                    Conversation.archived_at.is_(None),
                )
                .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
                .limit(limit)
            )
        ).scalars()
    )
    for conversation in conversations:
        first_user = (
            await session.execute(
                select(Message)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.role == "user",
                )
                .order_by(Message.created_at, Message.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        last_assistant = (
            await session.execute(
                select(Message)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.role == "assistant",
                )
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        items.append(
            {
                "id": conversation.id,
                "kind": "chat",
                "title": conversation.title or "Chat",
                "status": last_assistant.status if last_assistant is not None else "ready",
                "input": _clip(first_user.content if first_user is not None else ""),
                "output": _clip(
                    last_assistant.content if last_assistant is not None else ""
                ),
                "model": conversation.model,
                "duration_ms": None,
                "error_code": None,
                "created_at": conversation.updated_at or conversation.created_at,
                "href": f"/chat/{conversation.id}",
            }
        )

    if agent.workflow_id is not None:
        runs = list(
            (
                await session.execute(
                    select(WorkflowRun)
                    .where(
                        WorkflowRun.workflow_id == agent.workflow_id,
                        WorkflowRun.workspace_id == workspace_id,
                    )
                    .order_by(WorkflowRun.started_at.desc(), WorkflowRun.id.desc())
                    .limit(limit)
                )
            ).scalars()
        )
        for run in runs:
            end_event = (
                await session.execute(
                    select(WorkflowRunEvent)
                    .where(
                        WorkflowRunEvent.run_id == run.id,
                        WorkflowRunEvent.event == "workflow_end",
                    )
                    .order_by(WorkflowRunEvent.seq.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            output = ""
            if end_event is not None and isinstance(end_event.payload, dict):
                output = str(end_event.payload.get("output", ""))
            items.append(
                {
                    "id": run.id,
                    "kind": "workflow",
                    "title": agent.name,
                    "status": run.status,
                    "input": _clip(run.input_text),
                    "output": _clip(output),
                    "model": agent.default_model or "",
                    "duration_ms": run.total_ms,
                    "error_code": run.error_code,
                    "created_at": run.started_at,
                    "href": f"/workflows?run={run.id}",
                }
            )
    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items[:limit]


async def favorite_agent_ids(
    session: AsyncSession, user_id: UUID, agent_ids: list[UUID]
) -> set[UUID]:
    if not agent_ids:
        return set()
    rows = (
        await session.execute(
            select(AgentFavorite.agent_id).where(
                AgentFavorite.user_id == user_id,
                AgentFavorite.agent_id.in_(agent_ids),
            )
        )
    ).scalars().all()
    return set(rows)