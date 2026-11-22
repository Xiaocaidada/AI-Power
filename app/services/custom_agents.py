from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentSpec
from app.agents.registry import MATH_PROMPT, RETRIEVAL_PROMPT, SUPERVISOR_PROMPT
from app.models import Conversation, CustomAgent

AGENT_TOOL_NAMES = frozenset({"kb_search", "current_time", "calculator"})
BUILTIN_AGENT_IDS = frozenset({"builtin:supervisor", "builtin:retrieval", "builtin:math"})

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
    if agent.default_kb_id is not None and "kb_search" not in tools:
        tools.append("kb_search")
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
) -> list[CustomAgent]:
    conditions = [
        CustomAgent.workspace_id == workspace_id,
        or_(CustomAgent.owner_user_id == user_id, CustomAgent.visibility == "shared"),
    ]
    if not include_archived:
        conditions.append(CustomAgent.archived_at.is_(None))
    if category:
        conditions.append(CustomAgent.category == category)
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


def validate_tools(tools: list[str]) -> list[str]:
    unknown = sorted(set(tools) - AGENT_TOOL_NAMES)
    if unknown:
        raise CustomAgentError("invalid_tools", f"Unknown tools: {', '.join(unknown)}")
    return list(dict.fromkeys(tools))


async def create_custom_agent(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    owner_user_id: UUID,
    values: dict[str, Any],
) -> CustomAgent:
    values["tools"] = validate_tools(list(values.get("tools", [])))
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
    if "tools" in values and values["tools"] is not None:
        values["tools"] = validate_tools(list(values["tools"]))
    for key, value in values.items():
        setattr(agent, key, value)
    await session.flush()
    return agent


async def archive_custom_agent(session: AsyncSession, agent: CustomAgent) -> None:
    agent.archived_at = datetime.now(UTC)
    await session.flush()