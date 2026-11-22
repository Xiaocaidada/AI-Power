from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, get_scoped_registry
from app.models import AuditLog, PluginConfig, PluginDefinition
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas import CustomAgentCreate, CustomAgentOut, CustomAgentUpdate
from app.services.access import get_owned_knowledge_base
from app.services.custom_agents import (
    BUILTIN_AGENT_IDS,
    BUILTIN_AGENTS,
    CustomAgentError,
    agent_conversation_count,
    archive_custom_agent,
    can_manage,
    create_custom_agent,
    get_custom_agent,
    list_custom_agents,
    update_custom_agent,
)
from app.services.provider_configs import ProviderConfigError, ensure_model_capability

router = APIRouter(prefix="/agents", tags=["agents"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_scoped_registry)]


def _custom_out(agent, count: int, context: AuthContext) -> CustomAgentOut:
    return CustomAgentOut(
        id=str(agent.id),
        name=agent.name,
        description=agent.description,
        instructions=agent.instructions,
        category=agent.category,
        default_provider_id=agent.default_provider_id,
        default_model=agent.default_model,
        default_kb_id=agent.default_kb_id,
        tools=list(agent.tools),
        plugin_ids=[UUID(item) for item in agent.plugin_ids],
        visibility=agent.visibility,
        enabled=agent.enabled,
        archived=agent.archived_at is not None,
        owned=can_manage(agent, context.user.id, context.role),
        builtin=False,
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
        default_provider_id=None,
        default_model=None,
        default_kb_id=None,
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
) -> list[CustomAgentOut]:
    result = [_builtin_out(agent_id) for agent_id in _builtin_ids(q, category)]
    for agent in await list_custom_agents(
        session, context.workspace.id, context.user.id, search=q, category=category
    ):
        result.append(
            _custom_out(agent, await agent_conversation_count(session, agent.id), context)
        )
    return result


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
    return _custom_out(agent, await agent_conversation_count(session, agent.id), context)


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