from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, get_scoped_registry
from app.models import AuditLog, CustomAgent, PluginConfig, PluginDefinition
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas import (
    AgentAnalyticsOut,
    AgentBuiltinToolOut,
    AgentFavoriteOut,
    AgentFromTemplateIn,
    AgentMcpServerOut,
    AgentMcpToolOut,
    AgentPublishIn,
    AgentReportIn,
    AgentReviewIn,
    AgentReviewOut,
    AgentRunOut,
    AgentToolCatalogOut,
    AgentToolTestIn,
    AgentToolTestOut,
    AgentUseOut,
    CustomAgentCreate,
    CustomAgentOut,
    CustomAgentUpdate,
)
from app.services.access import get_owned_knowledge_base
from app.services.agent_analytics import agent_analytics
from app.services.agent_reviews import (
    AgentReviewError,
    create_report,
    delete_review,
    get_review,
    mask_email,
    require_published_agent,
    upsert_review,
)
from app.services.agent_templates import (
    AgentTemplateError,
    create_agent_from_template,
)
from app.services.agent_tools import (
    AgentToolError,
    agent_tool_catalog,
    execute_agent_tool,
    list_server_mcp_tools,
)
from app.services.custom_agents import (
    BUILTIN_AGENT_IDS,
    BUILTIN_AGENTS,
    CustomAgentError,
    agent_conversation_count,
    archive_custom_agent,
    can_manage,
    copy_published_agent,
    create_custom_agent,
    favorite_agent_ids,
    get_custom_agent,
    increment_agent_usage,
    list_agent_runs,
    list_custom_agents,
    publish_custom_agent,
    set_agent_favorite,
    unpublish_custom_agent,
    update_custom_agent,
)
from app.services.memory_permissions import normalize_agent_permissions
from app.services.provider_configs import ProviderConfigError, ensure_model_capability

router = APIRouter(prefix="/agents", tags=["agents"])
tool_router = APIRouter(prefix="/agent-tools", tags=["agents"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_scoped_registry)]


def _custom_out(
    agent, count: int, context: AuthContext, *, favorite: bool = False
) -> CustomAgentOut:
    permissions = normalize_agent_permissions(
        agent.memory_permissions, agent.memory_enabled
    )
    return CustomAgentOut(
        id=str(agent.id),
        name=agent.name,
        description=agent.description,
        instructions=agent.instructions,
        category=agent.category,
        mode=agent.mode,
        icon=agent.icon,
        cover_url=agent.cover_url,
        welcome_message=agent.welcome_message,
        examples=list(agent.examples),
        usage_instructions=agent.usage_instructions,
        generation_settings=dict(agent.generation_settings),
        default_provider_id=agent.default_provider_id,
        default_model=agent.default_model,
        default_kb_id=agent.default_kb_id,
        kb_ids=[UUID(item) for item in agent.kb_ids],
        tools=list(agent.tools),
        plugin_ids=[UUID(item) for item in agent.plugin_ids],
        workflow_id=agent.workflow_id,
        visibility=agent.visibility,
        enabled=agent.enabled,
        memory_enabled=agent.memory_enabled,
        memory_read_global=bool(permissions["read_global"]),
        memory_read_project=bool(permissions["read_project"]),
        memory_read_agent=bool(permissions["read_agent"]),
        memory_write=bool(permissions["write"]),
        memory_write_scope=str(permissions["write_scope"]),
        memory_write_mode=str(permissions["write_mode"]),
        rating_avg=agent.rating_avg,
        rating_count=agent.rating_count,
        archived=agent.archived_at is not None,
        owned=can_manage(agent, context.user.id, context.role),
        builtin=False,
        published=agent.published,
        featured=agent.featured,
        public_slug=agent.public_slug,
        allow_copy=agent.allow_copy,
        show_structure=agent.show_structure,
        favorite=favorite,
        favorite_count=agent.favorite_count,
        usage_count=agent.usage_count,
        copy_count=agent.copy_count,
        conversation_count=count,
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def _builtin_out(agent_id: str) -> CustomAgentOut:
    item = BUILTIN_AGENTS[agent_id]
    return CustomAgentOut(
        id=agent_id,
        name=item["name"],
        description=item["description"],
        instructions=item["instructions"],
        category=item["category"],
        mode="autonomous",
        default_provider_id=None,
        default_model=None,
        default_kb_id=None,
        kb_ids=[],
        tools=list(item["tools"]),
        plugin_ids=[],
        visibility="shared",
        enabled=True,
        archived=False,
        owned=False,
        builtin=True,
        conversation_count=0,
        created_at=None,
        updated_at=None,
    )


def _builtin_ids(search: str | None, category: str | None) -> list[str]:
    result = []
    for agent_id, item in BUILTIN_AGENTS.items():
        if category is not None and item["category"] != category:
            continue
        if search:
            term = search.strip().lower()
            if term not in item["name"].lower() and term not in item["description"].lower():
                continue
        result.append(agent_id)
    return result


async def _validate_defaults(
    session: AsyncSession,
    registry: ProviderRegistry,
    context: AuthContext,
    *,
    provider_id: str | None,
    model: str | None,
    kb_id: UUID | None,
    plugin_ids: list[UUID],
) -> None:
    if provider_id is None:
        if model is not None:
            raise HTTPException(
                422, {"code": "invalid_defaults", "message": "model requires provider"}
            )
    elif provider_id != "auto":
        if not model:
            raise HTTPException(
                422, {"code": "invalid_defaults", "message": "model is required"}
            )
        try:
            registry.get(provider_id)
            await ensure_model_capability(
                session,
                workspace_id=context.workspace.id,
                user_id=context.user.id,
                provider_id=provider_id,
                model_id=model,
                capability="tools",
            )
        except ProviderError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
        except ProviderConfigError as exc:
            raise HTTPException(
                404 if exc.code in {"not_found", "model_not_found"} else 422,
                {"code": exc.code, "message": exc.message},
            ) from None
    if kb_id is not None:
        await get_owned_knowledge_base(kb_id, context.workspace.id, session)
    if plugin_ids:
        unique = list(dict.fromkeys(plugin_ids))
        definitions = (
            await session.execute(
                select(PluginDefinition.id).where(
                    PluginDefinition.id.in_(unique),
                    PluginDefinition.enabled.is_(True),
                )
            )
        ).scalars().all()
        configs = (
            await session.execute(
                select(PluginConfig.plugin_id).where(
                    PluginConfig.workspace_id == context.workspace.id,
                    PluginConfig.plugin_id.in_(unique),
                    PluginConfig.enabled.is_(True),
                )
            )
        ).scalars().all()
        if len(definitions) != len(unique) or len(configs) != len(unique):
            raise HTTPException(
                422, {"code": "plugin_not_configured", "message": "Plugin is not configured"}
            )


def _normalize_pair(provider_id: str | None, model: str | None) -> tuple[str | None, str | None]:
    if provider_id is None:
        return None, None
    if provider_id == "auto":
        return "auto", "auto"
    return provider_id, model


@router.get("", response_model=list[CustomAgentOut])
async def list_agents(
    context: JwtContext,
    session: SessionDep,
    q: str | None = None,
    category: str | None = None,
    scope: Literal[
        "all", "mine", "created", "copied", "favorites", "published"
    ] = "all",
) -> list[CustomAgentOut]:
    result = (
        [_builtin_out(agent_id) for agent_id in _builtin_ids(q, category)]
        if scope == "all"
        else []
    )
    custom = await list_custom_agents(
        session,
        context.workspace.id,
        context.user.id,
        search=q,
        category=category,
        scope=scope,
    )
    favorites = await favorite_agent_ids(
        session, context.user.id, [agent.id for agent in custom]
    )
    for agent in custom:
        result.append(
            _custom_out(
                agent,
                await agent_conversation_count(session, agent.id),
                context,
                favorite=agent.id in favorites,
            )
        )
    return result


@router.post(
    "/from-template",
    response_model=CustomAgentOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_from_template(
    payload: AgentFromTemplateIn,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
) -> CustomAgentOut:
    provider_id = payload.provider_id
    model = payload.model
    if provider_id == "auto":
        provider_id, model = None, None
    await _validate_defaults(
        session,
        registry,
        context,
        provider_id=provider_id,
        model=model,
        kb_id=None,
        plugin_ids=[],
    )
    try:
        agent = await create_agent_from_template(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            template_id=payload.template,
            name=payload.name,
            description=payload.description,
            category=payload.category,
            provider_id=provider_id,
            model=model,
        )
    except AgentTemplateError as exc:
        raise HTTPException(422, {"code": exc.code, "message": exc.message}) from None
    await session.commit()
    await session.refresh(agent)
    return _custom_out(agent, 0, context)


@router.get("/{agent_id}", response_model=CustomAgentOut)
async def get_agent(
    agent_id: str, context: JwtContext, session: SessionDep
) -> CustomAgentOut:
    if agent_id in BUILTIN_AGENT_IDS:
        return _builtin_out(agent_id)
    try:
        parsed = UUID(agent_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found") from None
    try:
        agent = await get_custom_agent(
            session, context.workspace.id, parsed, context.user.id
        )
    except CustomAgentError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    favorites = await favorite_agent_ids(session, context.user.id, [agent.id])
    return _custom_out(
        agent,
        await agent_conversation_count(session, agent.id),
        context,
        favorite=agent.id in favorites,
    )


@router.post("", response_model=CustomAgentOut, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: CustomAgentCreate,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
) -> CustomAgentOut:
    plugin_ids = list(dict.fromkeys(payload.plugin_ids))
    provider_id, model = _normalize_pair(payload.default_provider_id, payload.default_model)
    await _validate_defaults(
        session,
        registry,
        context,
        provider_id=provider_id,
        model=model,
        kb_id=payload.default_kb_id,
        plugin_ids=plugin_ids,
    )
    values = payload.model_dump()
    values["default_provider_id"] = provider_id
    values["default_model"] = model
    values["plugin_ids"] = [str(item) for item in plugin_ids]
    values["memory_permissions"] = normalize_agent_permissions(
        {
            "read_global": values.pop("memory_read_global", True),
            "read_project": values.pop("memory_read_project", True),
            "read_agent": values.pop("memory_read_agent", True),
            "write": values.pop("memory_write", False),
            "write_scope": values.pop("memory_write_scope", "agent"),
            "write_mode": values.pop("memory_write_mode", "candidate"),
        },
        bool(values.get("memory_enabled", False)),
    )
    try:
        agent = await create_custom_agent(
            session,
            workspace_id=context.workspace.id,
            owner_user_id=context.user.id,
            values=values,
        )
    except CustomAgentError as exc:
        raise HTTPException(422, {"code": exc.code, "message": exc.message}) from None
    await session.commit()
    await session.refresh(agent)
    return _custom_out(agent, 0, context)


@router.patch("/{agent_id}", response_model=CustomAgentOut)
async def update_agent(
    agent_id: str,
    payload: CustomAgentUpdate,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
) -> CustomAgentOut:
    try:
        parsed = UUID(agent_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found") from None
    try:
        agent = await get_custom_agent(
            session, context.workspace.id, parsed, context.user.id, include_archived=True
        )
    except CustomAgentError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    if not can_manage(agent, context.user.id, context.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the agent owner can edit")
    data = payload.model_dump(exclude_unset=True)
    memory_keys = (
        "memory_enabled",
        "memory_read_global",
        "memory_read_project",
        "memory_read_agent",
        "memory_write",
        "memory_write_scope",
        "memory_write_mode",
    )
    if any(key in data for key in memory_keys):
        current = normalize_agent_permissions(
            agent.memory_permissions, agent.memory_enabled
        )
        enabled = data.get("memory_enabled", agent.memory_enabled)
        data["memory_permissions"] = normalize_agent_permissions(
            {
                "read_global": data.pop(
                    "memory_read_global", current["read_global"]
                ),
                "read_project": data.pop(
                    "memory_read_project", current["read_project"]
                ),
                "read_agent": data.pop("memory_read_agent", current["read_agent"]),
                "write": data.pop("memory_write", current["write"]),
                "write_scope": data.pop(
                    "memory_write_scope", current["write_scope"]
                ),
                "write_mode": data.pop("memory_write_mode", current["write_mode"]),
            },
            bool(enabled),
        )
    provider_id = data.get("default_provider_id", agent.default_provider_id)
    model = data.get("default_model", agent.default_model)
    kb_id = data.get("default_kb_id", agent.default_kb_id)
    plugin_ids = data.get("plugin_ids", agent.plugin_ids)
    plugin_uuids = [item if isinstance(item, UUID) else UUID(str(item)) for item in plugin_ids]
    provider_id, model = _normalize_pair(provider_id, model)
    await _validate_defaults(
        session,
        registry,
        context,
        provider_id=provider_id,
        model=model,
        kb_id=kb_id,
        plugin_ids=plugin_uuids,
    )
    data["default_provider_id"] = provider_id
    data["default_model"] = model
    if "plugin_ids" in data:
        data["plugin_ids"] = [str(item) for item in plugin_uuids]
    try:
        agent = await update_custom_agent(session, agent, data)
    except CustomAgentError as exc:
        raise HTTPException(422, {"code": exc.code, "message": exc.message}) from None
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="agent.update",
            target_type="custom_agent",
            target_id=str(agent.id),
            detail={"visibility": agent.visibility},
        )
    )
    await session.commit()
    await session.refresh(agent)
    return _custom_out(agent, await agent_conversation_count(session, agent.id), context)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str, context: JwtContext, session: SessionDep
) -> Response:
    try:
        parsed = UUID(agent_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found") from None
    try:
        agent = await get_custom_agent(
            session, context.workspace.id, parsed, context.user.id, include_archived=True
        )
    except CustomAgentError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    if not can_manage(agent, context.user.id, context.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the agent owner can delete")
    await archive_custom_agent(session, agent)
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="agent.archive",
            target_type="custom_agent",
            target_id=str(agent.id),
            detail={},
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{agent_id}/publish", response_model=CustomAgentOut)
async def publish_agent(
    agent_id: str,
    payload: AgentPublishIn,
    context: JwtContext,
    session: SessionDep,
) -> CustomAgentOut:
    try:
        parsed = UUID(agent_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found") from None
    try:
        agent = await get_custom_agent(
            session, context.workspace.id, parsed, context.user.id, include_archived=True
        )
    except CustomAgentError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    if not can_manage(agent, context.user.id, context.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the agent owner can publish")
    try:
        agent = await publish_custom_agent(
            session,
            agent,
            slug=payload.slug,
            allow_copy=payload.allow_copy,
            show_structure=payload.show_structure,
        )
    except CustomAgentError as exc:
        raise HTTPException(422, {"code": exc.code, "message": exc.message}) from None
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="agent.publish",
            target_type="custom_agent",
            target_id=str(agent.id),
            detail={"slug": agent.public_slug},
        )
    )
    await session.commit()
    await session.refresh(agent)
    return _custom_out(agent, await agent_conversation_count(session, agent.id), context)


@router.delete("/{agent_id}/publish", response_model=CustomAgentOut)
async def unpublish_agent(
    agent_id: str, context: JwtContext, session: SessionDep
) -> CustomAgentOut:
    try:
        parsed = UUID(agent_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found") from None
    try:
        agent = await get_custom_agent(
            session, context.workspace.id, parsed, context.user.id, include_archived=True
        )
    except CustomAgentError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    if not can_manage(agent, context.user.id, context.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the agent owner can unpublish")
    await unpublish_custom_agent(session, agent)
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="agent.unpublish",
            target_type="custom_agent",
            target_id=str(agent.id),
            detail={},
        )
    )
    await session.commit()
    await session.refresh(agent)
    return _custom_out(agent, await agent_conversation_count(session, agent.id), context)


@router.post("/{agent_id}/use", response_model=AgentUseOut)
async def use_agent(
    agent_id: str, context: JwtContext, session: SessionDep
) -> AgentUseOut:
    try:
        parsed = UUID(agent_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found") from None
    try:
        agent = await get_custom_agent(
            session, context.workspace.id, parsed, context.user.id
        )
    except CustomAgentError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    count = await increment_agent_usage(session, agent)
    await session.commit()
    return AgentUseOut(usage_count=count)


@router.get("/{agent_id}/runs", response_model=list[AgentRunOut])
async def list_runs(
    agent_id: str,
    context: JwtContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[AgentRunOut]:
    try:
        parsed = UUID(agent_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found") from None
    try:
        agent = await get_custom_agent(
            session, context.workspace.id, parsed, context.user.id
        )
    except CustomAgentError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    rows = await list_agent_runs(
        session, agent, context.workspace.id, limit=limit
    )
    return [AgentRunOut(**row) for row in rows]


@router.get("/{agent_id}/analytics", response_model=AgentAnalyticsOut)
async def get_agent_analytics(
    agent_id: str,
    context: JwtContext,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> AgentAnalyticsOut:
    try:
        parsed = UUID(agent_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found") from None
    try:
        agent = await get_custom_agent(
            session, context.workspace.id, parsed, context.user.id
        )
    except CustomAgentError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    result = await agent_analytics(
        session, agent, context.workspace.id, days=days
    )
    return AgentAnalyticsOut.model_validate(result)


@router.post("/{agent_id}/tools/test", response_model=AgentToolTestOut)
async def test_agent_tool(
    agent_id: str,
    payload: AgentToolTestIn,
    context: JwtContext,
    session: SessionDep,
) -> AgentToolTestOut:
    try:
        parsed = UUID(agent_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found") from None
    try:
        agent = await get_custom_agent(
            session, context.workspace.id, parsed, context.user.id
        )
    except CustomAgentError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    if not can_manage(agent, context.user.id, context.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the agent owner can test tools")
    try:
        result = await execute_agent_tool(
            session,
            agent,
            payload.tool,
            payload.arguments,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
        )
    except AgentToolError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if exc.code == "not_found"
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(code, {"code": exc.code, "message": exc.message}) from None
    return AgentToolTestOut(**result)


@router.post("/{agent_id}/copy", response_model=CustomAgentOut, status_code=status.HTTP_201_CREATED)
async def copy_agent(
    agent_id: str, context: JwtContext, session: SessionDep
) -> CustomAgentOut:
    try:
        parsed = UUID(agent_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found") from None
    source = await session.get(CustomAgent, parsed)
    if source is None or source.archived_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    public_copy = source.published and source.allow_copy
    workspace_copy = source.workspace_id == context.workspace.id and (
        source.owner_user_id == context.user.id or source.visibility == "shared"
    )
    if not public_copy and not workspace_copy:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    try:
        agent = await copy_published_agent(
            session,
            source,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            require_published=not workspace_copy,
        )
    except CustomAgentError as exc:
        raise HTTPException(422, {"code": exc.code, "message": exc.message}) from None
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="agent.copy",
            target_type="custom_agent",
            target_id=str(agent.id),
            detail={"source_agent_id": str(source.id)},
        )
    )
    await session.commit()
    await session.refresh(agent)
    return _custom_out(agent, 0, context)


async def _favoritable_agent(
    session: AsyncSession, agent_id: str, context: AuthContext
):
    try:
        parsed = UUID(agent_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found") from None
    agent = await session.get(CustomAgent, parsed)
    if agent is None or agent.archived_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    public = agent.published
    workspace = agent.workspace_id == context.workspace.id and (
        agent.owner_user_id == context.user.id or agent.visibility == "shared"
    )
    if not public and not workspace:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    return agent


@router.put("/{agent_id}/favorite", response_model=AgentFavoriteOut)
async def favorite_agent(
    agent_id: str, context: JwtContext, session: SessionDep
) -> AgentFavoriteOut:
    agent = await _favoritable_agent(session, agent_id, context)
    favorite = await set_agent_favorite(session, agent, context.user.id, True)
    await session.commit()
    return AgentFavoriteOut(favorite=favorite)


@router.delete("/{agent_id}/favorite", response_model=AgentFavoriteOut)
async def unfavorite_agent(
    agent_id: str, context: JwtContext, session: SessionDep
) -> AgentFavoriteOut:
    agent = await _favoritable_agent(session, agent_id, context)
    favorite = await set_agent_favorite(session, agent, context.user.id, False)
    await session.commit()
    return AgentFavoriteOut(favorite=favorite)


def _review_error(exc: AgentReviewError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND
        if exc.code in {"not_found"}
        else status.HTTP_409_CONFLICT
        if exc.code in {"duplicate_report"}
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(code, {"code": exc.code, "message": exc.message})


@router.put("/{agent_id}/review", response_model=AgentReviewOut)
async def submit_agent_review(
    agent_id: UUID,
    payload: AgentReviewIn,
    context: JwtContext,
    session: SessionDep,
) -> AgentReviewOut:
    try:
        agent = await require_published_agent(session, agent_id)
        review = await upsert_review(
            session,
            agent,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            rating=payload.rating,
            content=payload.content,
        )
    except AgentReviewError as exc:
        raise _review_error(exc) from None
    await session.commit()
    await session.refresh(review)
    return AgentReviewOut(
        id=review.id,
        rating=review.rating,
        content=review.content,
        author=mask_email(context.user.email),
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


@router.delete("/{agent_id}/review", status_code=status.HTTP_204_NO_CONTENT)
async def remove_agent_review(
    agent_id: UUID, context: JwtContext, session: SessionDep
) -> Response:
    try:
        agent = await require_published_agent(session, agent_id)
        await delete_review(session, agent, context.user.id)
    except AgentReviewError as exc:
        raise _review_error(exc) from None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{agent_id}/review", response_model=AgentReviewOut | None)
async def get_my_agent_review(
    agent_id: UUID, context: JwtContext, session: SessionDep
) -> AgentReviewOut | None:
    review = await get_review(session, agent_id, context.user.id)
    if review is None or review.status != "visible":
        return None
    return AgentReviewOut(
        id=review.id,
        rating=review.rating,
        content=review.content,
        author=mask_email(context.user.email),
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


@tool_router.get("/catalog", response_model=AgentToolCatalogOut)
async def get_agent_tool_catalog(
    context: JwtContext, session: SessionDep
) -> AgentToolCatalogOut:
    catalog = await agent_tool_catalog(session)
    return AgentToolCatalogOut(
        builtin=[AgentBuiltinToolOut(**item) for item in catalog["builtin"]],
        mcp_servers=[AgentMcpServerOut(**item) for item in catalog["mcp_servers"]],
    )


@tool_router.get("/mcp", response_model=list[AgentMcpToolOut])
async def get_agent_mcp_tools(
    context: JwtContext,
    session: SessionDep,
    server_id: UUID,
) -> list[AgentMcpToolOut]:
    try:
        tools = await list_server_mcp_tools(session, server_id)
    except AgentToolError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if exc.code == "not_found"
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(code, {"code": exc.code, "message": exc.message}) from None
    return [AgentMcpToolOut(**item) for item in tools]


@router.post("/{agent_id}/report", status_code=status.HTTP_201_CREATED)
async def report_agent(
    agent_id: UUID,
    payload: AgentReportIn,
    context: JwtContext,
    session: SessionDep,
) -> dict[str, str]:
    try:
        agent = await require_published_agent(session, agent_id)
        report = await create_report(
            session,
            agent,
            reporter_user_id=context.user.id,
            reason=payload.reason,
            detail=payload.detail,
        )
    except AgentReviewError as exc:
        raise _review_error(exc) from None
    await session.commit()
    return {"id": str(report.id), "status": report.status}