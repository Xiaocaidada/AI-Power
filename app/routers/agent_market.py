from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, require_admin
from app.models import AuditLog, CustomAgent
from app.schemas import AgentFeatureIn, AgentMarketDetail, AgentMarketOut
from app.services.custom_agents import (
    CustomAgentError,
    get_published_agent,
    list_published_agents,
    public_agent_detail,
    public_agent_summary,
    set_agent_featured,
)

router = APIRouter(prefix="/market/agents", tags=["market"])
admin_router = APIRouter(prefix="/admin/agents", tags=["admin"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
AdminContext = Annotated[AuthContext, Depends(require_admin)]


@router.get("", response_model=list[AgentMarketOut])
async def list_market_agents(
    session: SessionDep,
    search: str | None = None,
    category: str | None = None,
    sort: str = "newest",
    featured: bool = False,
) -> list[AgentMarketOut]:
    agents = await list_published_agents(
        session,
        search=search,
        category=category,
        sort=sort,
        featured_only=featured,
    )
    return [AgentMarketOut(**public_agent_summary(agent)) for agent in agents]


@router.get("/{slug}", response_model=AgentMarketDetail)
async def get_market_agent(slug: str, session: SessionDep) -> AgentMarketDetail:
    try:
        agent = await get_published_agent(session, slug)
    except CustomAgentError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    return AgentMarketDetail(**public_agent_detail(agent))


@admin_router.get("", response_model=list[AgentMarketOut])
async def list_admin_agents(
    context: AdminContext, session: SessionDep
) -> list[AgentMarketOut]:
    agents = await list_published_agents(session, sort="newest")
    return [AgentMarketOut(**public_agent_summary(agent)) for agent in agents]


@admin_router.post("/{agent_id}/feature", response_model=AgentMarketOut)
async def feature_agent(
    agent_id: UUID,
    payload: AgentFeatureIn,
    context: AdminContext,
    session: SessionDep,
) -> AgentMarketOut:
    agent = await session.get(CustomAgent, agent_id)
    if agent is None or agent.archived_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")
    if payload.featured and not agent.published:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "agent_not_published", "message": "Publish the agent first"},
        )
    await set_agent_featured(session, agent, payload.featured)
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="agent.feature",
            target_type="custom_agent",
            target_id=str(agent.id),
            detail={"featured": payload.featured},
        )
    )
    await session.commit()
    await session.refresh(agent)
    return AgentMarketOut(**public_agent_summary(agent))