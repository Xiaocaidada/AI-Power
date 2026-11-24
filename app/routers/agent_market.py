from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, require_admin
from app.models import AgentReport, AgentReview, AuditLog, CustomAgent, User
from app.schemas import (
    AdminReviewOut,
    AgentFacetCount,
    AgentFeatureIn,
    AgentMarketDetail,
    AgentMarketFacetsOut,
    AgentMarketOut,
    AgentReportOut,
    AgentReportResolveIn,
    AgentReviewListOut,
    AgentReviewOut,
    ReviewVisibilityIn,
)
from app.services.agent_reviews import (
    AgentReviewError,
    list_admin_reviews,
    list_reports,
    list_reviews,
    mask_email,
    resolve_report,
    set_review_visibility,
)
from app.services.custom_agents import (
    CustomAgentError,
    get_published_agent,
    list_published_agents,
    public_agent_detail,
    public_agent_summary,
    published_agent_facets,
    set_agent_featured,
)

router = APIRouter(prefix="/market/agents", tags=["market"])
admin_router = APIRouter(prefix="/admin/agents", tags=["admin"])
reports_router = APIRouter(prefix="/admin/agent-reports", tags=["admin"])
reviews_admin_router = APIRouter(prefix="/admin/agent-reviews", tags=["admin"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
AdminContext = Annotated[AuthContext, Depends(require_admin)]


@router.get("", response_model=list[AgentMarketOut])
async def list_market_agents(
    session: SessionDep,
    search: str | None = None,
    category: str | None = None,
    publisher: str | None = None,
    sort: str = "newest",
    featured: bool = False,
    official: bool = False,
) -> list[AgentMarketOut]:
    rows = await list_published_agents(
        session,
        search=search,
        category=category,
        sort=sort,
        featured_only=featured,
        official_only=official,
        publisher=publisher,
    )
    return [
        AgentMarketOut(
            **public_agent_summary(agent, owner_email=email, owner_role=role)
        )
        for agent, email, role in rows
    ]


@router.get("/facets", response_model=AgentMarketFacetsOut)
async def get_market_agent_facets(session: SessionDep) -> AgentMarketFacetsOut:
    facets = await published_agent_facets(session)
    return AgentMarketFacetsOut(
        total=facets["total"],
        official=facets["official"],
        featured=facets["featured"],
        categories=[AgentFacetCount(**item) for item in facets["categories"]],
        publishers=[AgentFacetCount(**item) for item in facets["publishers"]],
    )


@router.get("/{slug}", response_model=AgentMarketDetail)
async def get_market_agent(slug: str, session: SessionDep) -> AgentMarketDetail:
    try:
        agent = await get_published_agent(session, slug)
    except CustomAgentError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    owner = await session.get(User, agent.owner_user_id)
    return AgentMarketDetail(
        **public_agent_detail(
            agent,
            owner_email=owner.email if owner is not None else "",
            owner_role=owner.role if owner is not None else "user",
        )
    )


@router.get("/{slug}/reviews", response_model=AgentReviewListOut)
async def list_market_agent_reviews(
    slug: str,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AgentReviewListOut:
    try:
        agent = await get_published_agent(session, slug)
    except CustomAgentError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    reviews = await list_reviews(session, agent.id, limit=limit)
    return AgentReviewListOut(
        rating_avg=agent.rating_avg,
        rating_count=agent.rating_count,
        reviews=[AgentReviewOut(**review) for review in reviews],
    )


@reports_router.get("", response_model=list[AgentReportOut])
async def list_agent_reports(
    context: AdminContext,
    session: SessionDep,
    status_filter: Annotated[str | None, Query(alias="status")] = "open",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[AgentReportOut]:
    rows = await list_reports(session, status=status_filter, limit=limit)
    return [
        AgentReportOut(
            id=report.id,
            agent_id=report.agent_id,
            agent_name=agent_name,
            reporter=mask_email(email),
            reason=report.reason,
            detail=report.detail,
            status=report.status,
            resolution=report.resolution,
            created_at=report.created_at,
            handled_at=report.handled_at,
        )
        for report, agent_name, email in rows
    ]


@reports_router.post("/{report_id}/resolve", response_model=AgentReportOut)
async def resolve_agent_report(
    report_id: UUID,
    payload: AgentReportResolveIn,
    context: AdminContext,
    session: SessionDep,
) -> AgentReportOut:
    report = await session.get(AgentReport, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    try:
        agent = await resolve_report(
            session,
            report,
            action=payload.action,
            resolution=payload.resolution,
            admin_user_id=context.user.id,
        )
    except AgentReviewError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": exc.code, "message": exc.message},
        ) from None
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="agent.report_resolve",
            target_type="agent_report",
            target_id=str(report.id),
            detail={"action": payload.action, "agent_id": str(agent.id)},
        )
    )
    await session.commit()
    await session.refresh(report)
    reporter = await session.get(User, report.reporter_user_id)
    return AgentReportOut(
        id=report.id,
        agent_id=report.agent_id,
        agent_name=agent.name,
        reporter=mask_email(reporter.email) if reporter is not None else "",
        reason=report.reason,
        detail=report.detail,
        status=report.status,
        resolution=report.resolution,
        created_at=report.created_at,
        handled_at=report.handled_at,
    )


@admin_router.get("", response_model=list[AgentMarketOut])
async def list_admin_agents(
    context: AdminContext, session: SessionDep
) -> list[AgentMarketOut]:
    rows = await list_published_agents(session, sort="newest")
    return [
        AgentMarketOut(
            **public_agent_summary(agent, owner_email=email, owner_role=role)
        )
        for agent, email, role in rows
    ]


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
    owner = await session.get(User, agent.owner_user_id)
    return AgentMarketOut(
        **public_agent_summary(
            agent,
            owner_email=owner.email if owner is not None else "",
            owner_role=owner.role if owner is not None else "user",
        )
    )


@reviews_admin_router.get("", response_model=list[AdminReviewOut])
async def list_admin_agent_reviews(
    context: AdminContext,
    session: SessionDep,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    agent_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[AdminReviewOut]:
    rows = await list_admin_reviews(
        session, status_filter=status_filter, agent_id=agent_id, limit=limit
    )
    return [
        AdminReviewOut(
            id=review.id,
            agent_id=review.agent_id,
            agent_name=agent_name,
            author=mask_email(email),
            rating=review.rating,
            content=review.content,
            status=review.status,
            created_at=review.created_at,
            updated_at=review.updated_at,
        )
        for review, agent_name, email in rows
    ]


@reviews_admin_router.post("/{review_id}/visibility", response_model=AdminReviewOut)
async def set_admin_agent_review_visibility(
    review_id: UUID,
    payload: ReviewVisibilityIn,
    context: AdminContext,
    session: SessionDep,
) -> AdminReviewOut:
    review = await session.get(AgentReview, review_id)
    if review is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
    await set_review_visibility(session, review, visible=payload.visible)
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="agent.review_visibility",
            target_type="agent_review",
            target_id=str(review.id),
            detail={"visible": payload.visible, "agent_id": str(review.agent_id)},
        )
    )
    await session.commit()
    await session.refresh(review)
    agent = await session.get(CustomAgent, review.agent_id)
    author = await session.get(User, review.user_id)
    return AdminReviewOut(
        id=review.id,
        agent_id=review.agent_id,
        agent_name=agent.name if agent is not None else "",
        author=mask_email(author.email) if author is not None else "",
        rating=review.rating,
        content=review.content,
        status=review.status,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )
