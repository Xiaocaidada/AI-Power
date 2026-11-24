"""Workspace Skills: prompt + tool bundles with recorded runs."""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentSpec
from app.agents.registry import AgentRegistry
from app.config import get_settings
from app.models import Skill, SkillRun
from app.providers.base import ChatMessage, ProviderError
from app.services.agent import AgentFailure, AgentRunner
from app.services.chat_tasks import ChatTaskError, resolve_task_model
from app.services.usage_ledger import SOURCE_SKILL, write_usage_event
from app.tools.base import ToolContext, ToolRegistry
from app.tools.registry import build_tool_registry

logger = logging.getLogger(__name__)

MAX_TOOLS = 20
ROOT_AGENT = "skill"


class SkillError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _accessible(skill: Skill, user_id: UUID) -> bool:
    return skill.owner_user_id == user_id or skill.shared


async def get_skill(
    session: AsyncSession,
    skill_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
    *,
    owner_only: bool = False,
) -> Skill:
    conditions = [
        Skill.id == skill_id,
        Skill.workspace_id == workspace_id,
        Skill.deleted_at.is_(None),
    ]
    if owner_only:
        conditions.append(Skill.owner_user_id == user_id)
    skill = (
        await session.execute(select(Skill).where(*conditions))
    ).scalar_one_or_none()
    if skill is None or (not owner_only and not _accessible(skill, user_id)):
        raise SkillError("not_found", "Skill not found")
    return skill


async def list_skills(session: AsyncSession, workspace_id: UUID, user_id: UUID) -> list[Skill]:
    return list(
        (
            await session.execute(
                select(Skill)
                .where(
                    Skill.workspace_id == workspace_id,
                    Skill.deleted_at.is_(None),
                    or_(Skill.owner_user_id == user_id, Skill.shared.is_(True)),
                )
                .order_by(Skill.updated_at.desc(), Skill.id.desc())
            )
        ).scalars()
    )


def _normalize_tools(names: list[str] | None, registry: ToolRegistry) -> list[str]:
    available = set(registry.names())
    result: list[str] = []
    for name in names or []:
        text = str(name).strip()
        if text in available and text not in result:
            result.append(text)
    return result[:MAX_TOOLS]


async def create_skill(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    name: str,
    description: str,
    instructions: str,
    tool_names: list[str],
    shared: bool,
    enabled: bool,
) -> Skill:
    clean_name = name.strip()
    existing = (
        await session.execute(
            select(Skill).where(
                Skill.workspace_id == workspace_id,
                Skill.owner_user_id == user_id,
                Skill.name == clean_name,
                Skill.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise SkillError("name_exists", "A skill with this name already exists")
    skill = Skill(
        workspace_id=workspace_id,
        owner_user_id=user_id,
        name=clean_name[:120],
        description=description.strip()[:500],
        instructions=instructions.strip()[:20000],
        tool_names=_normalize_tools(tool_names, build_tool_registry()),
        shared=shared,
        enabled=enabled,
    )
    session.add(skill)
    try:
        await session.flush()
    except IntegrityError:
        raise SkillError("name_exists", "A skill with this name already exists") from None
    return skill


async def update_skill(
    session: AsyncSession,
    skill: Skill,
    *,
    name: str | None = None,
    description: str | None = None,
    instructions: str | None = None,
    tool_names: list[str] | None = None,
    shared: bool | None = None,
    enabled: bool | None = None,
) -> Skill:
    if name is not None:
        clean = name.strip()
        duplicate = (
            await session.execute(
                select(Skill).where(
                    Skill.workspace_id == skill.workspace_id,
                    Skill.owner_user_id == skill.owner_user_id,
                    Skill.name == clean,
                    Skill.id != skill.id,
                    Skill.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise SkillError("name_exists", "A skill with this name already exists")
        skill.name = clean[:120]
    if description is not None:
        skill.description = description.strip()[:500]
    if instructions is not None:
        skill.instructions = instructions.strip()[:20000]
    if tool_names is not None:
        skill.tool_names = _normalize_tools(tool_names, build_tool_registry())
    if shared is not None:
        skill.shared = shared
    if enabled is not None:
        skill.enabled = enabled
    try:
        await session.flush()
    except IntegrityError:
        raise SkillError("name_exists", "A skill with this name already exists") from None
    return skill


async def delete_skill(session: AsyncSession, skill: Skill) -> None:
    skill.deleted_at = datetime.now(UTC)
    skill.enabled = False
    await session.flush()


async def match_skills(
    session: AsyncSession, workspace_id: UUID, user_id: UUID, query: str, limit: int = 5
) -> list[tuple[Skill, float]]:
    text = query.strip().casefold()
    if text == "":
        return []
    rows = [
        skill
        for skill in await list_skills(session, workspace_id, user_id)
        if skill.enabled
    ]
    scored: list[tuple[Skill, float]] = []
    for skill in rows:
        name = skill.name.casefold()
        description = skill.description.casefold()
        score = 0.0
        if name == text:
            score = 1.0
        elif text in name:
            score = 0.8
        elif text in description:
            score = 0.5
        else:
            tokens = [token for token in text.split() if token]
            if tokens and any(token in name or token in description for token in tokens):
                score = 0.3
        if score > 0:
            scored.append((skill, score))
    scored.sort(key=lambda item: (-item[1], item[0].name))
    return scored[: max(1, min(limit, 20))]


async def list_runs(
    session: AsyncSession, skill_id: UUID, workspace_id: UUID, limit: int = 50
) -> list[SkillRun]:
    return list(
        (
            await session.execute(
                select(SkillRun)
                .where(
                    SkillRun.skill_id == skill_id,
                    SkillRun.workspace_id == workspace_id,
                )
                .order_by(SkillRun.created_at.desc(), SkillRun.id.desc())
                .limit(max(1, min(limit, 100)))
            )
        ).scalars()
    )


async def run_skill(
    session: AsyncSession,
    *,
    skill: Skill,
    workspace_id: UUID,
    user_id: UUID,
    content: str,
    provider_id: str,
    model: str,
    registry,
    redis,
) -> SkillRun:
    if not skill.enabled:
        raise SkillError("skill_disabled", "This skill is disabled")
    try:
        provider_id, model = await resolve_task_model(
            session,
            registry,
            redis,
            provider_id=provider_id,
            model=model,
            workspace_id=workspace_id,
            user_id=user_id,
        )
    except ChatTaskError as exc:
        raise SkillError(exc.code, exc.message) from None
    try:
        provider = registry.get(provider_id)
    except ProviderError:
        raise SkillError("provider_not_found", "Provider is not available") from None

    run = SkillRun(
        workspace_id=workspace_id,
        user_id=user_id,
        skill_id=skill.id,
        status="running",
        input=content[:20000],
        output="",
        provider_id=provider_id,
        model=model,
    )
    session.add(run)
    await session.flush()

    tool_registry = build_tool_registry()
    allowed = _normalize_tools(skill.tool_names, tool_registry)
    spec = AgentSpec(
        name=ROOT_AGENT,
        system_prompt=skill.instructions or "Follow the user's request precisely.",
        tools=tuple(allowed),
    )
    runner = AgentRunner(
        provider=provider,
        model=model,
        tool_registry=tool_registry,
        agent_registry=AgentRegistry([spec]),
        context=ToolContext(workspace_id=workspace_id, user_id=user_id, citations=[]),
        root_agent=ROOT_AGENT,
        max_steps=get_settings().skill_run_max_steps,
    )
    output: list[str] = []
    tool_records: list[dict[str, Any]] = []
    error_code: str | None = None
    try:
        async for event in runner.run([ChatMessage(role="user", content=content)]):
            if event.kind == "delta":
                value = event.data.get("text")
                if isinstance(value, str):
                    output.append(value)
            elif event.kind == "tool_result":
                tool_records.append(
                    {
                        "tool": event.data.get("tool"),
                        "ok": event.data.get("ok"),
                        "output": str(event.data.get("output") or "")[:1000],
                        "error_code": event.data.get("error_code"),
                        "duration_ms": event.data.get("duration_ms"),
                    }
                )
    except AgentFailure as exc:
        error_code = exc.code
    except ProviderError as exc:
        error_code = exc.code
    except Exception:
        logger.exception("skill run failed")
        error_code = "skill_internal_error"

    text = "".join(output).strip()
    if error_code is None and text == "":
        error_code = "skill_empty_output"
    run.output = text
    run.tool_records = tool_records
    run.status = "failed" if error_code is not None else "completed"
    run.error_code = error_code
    run.finished_at = datetime.now(UTC)
    usage = runner.usage
    run.prompt_tokens = usage.prompt_tokens
    run.completion_tokens = usage.completion_tokens
    try:
        await write_usage_event(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            source=SOURCE_SKILL,
            provider_id=provider_id,
            model=model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            source_ref_id=run.id,
        )
    except Exception:
        logger.exception("failed to record skill usage for run %s", run.id)
    await session.flush()
    return run