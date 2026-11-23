from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import AgentMarketDetail, AgentMarketOut
from app.services.custom_agents import (
    CustomAgentError,
    get_published_agent,
    list_published_agents,
    public_agent_detail,
    public_agent_summary,
)

router = APIRouter(prefix="/market/agents", tags=["market"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[AgentMarketOut])
async def list_market_agents(
    session: SessionDep,
    search: str | None = None,
    category: str | None = None,
    sort: str = "newest",
) -> list[AgentMarketOut]:
    agents = await list_published_agents(
        session, search=search, category=category, sort=sort
    )
    return [AgentMarketOut(**public_agent_summary(agent)) for agent in agents]


@router.get("/{slug}", response_model=AgentMarketDetail)
async def get_market_agent(slug: str, session: SessionDep) -> AgentMarketDetail:
    try:
        agent = await get_published_agent(session, slug)
    except CustomAgentError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    return AgentMarketDetail(**public_agent_detail(agent))