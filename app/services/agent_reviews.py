"""Agent ratings, reviews and abuse reports."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentReport, AgentReview, CustomAgent, User

REPORT_REASONS = {"spam", "abuse", "copyright", "misleading", "other"}
REPORT_ACTIONS = {"dismiss", "unpublish"}


class AgentReviewError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not local or not domain:
        return "***"
    visible = local[:1]
    return f"{visible}***@{domain}"


async def require_published_agent(
    session: AsyncSession, agent_id: UUID
) -> CustomAgent:
    agent = await session.get(CustomAgent, agent_id)
    if (
        agent is None
        or not agent.published
        or agent.archived_at is not None
        or not agent.enabled
    ):
        raise AgentReviewError("not_found", "Published agent not found")
    return agent


async def recompute_agent_rating(session: AsyncSession, agent: CustomAgent) -> None:
    row = (
        await session.execute(
            select(func.avg(AgentReview.rating), func.count(AgentReview.id)).where(
                AgentReview.agent_id == agent.id,
                AgentReview.status == "visible",
            )
        )
    ).one()
    average, count = row
    agent.rating_avg = round(float(average or 0.0), 2)
    agent.rating_count = int(count or 0)
    await session.flush()


async def upsert_review(
    session: AsyncSession,
    agent: CustomAgent,
    *,
    workspace_id: UUID,
    user_id: UUID,
    rating: int,
    content: str,
) -> AgentReview:
    if rating < 1 or rating > 5:
        raise AgentReviewError("invalid_rating", "Rating must be between 1 and 5")
    existing = (
        await session.execute(
            select(AgentReview).where(
                AgentReview.agent_id == agent.id,
                AgentReview.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        review = AgentReview(
            agent_id=agent.id,
            workspace_id=workspace_id,
            user_id=user_id,
            rating=rating,
            content=content.strip(),
            status="visible",
        )
        session.add(review)
    else:
        review = existing
        review.rating = rating
        review.content = content.strip()
        # A moderation-hidden review stays hidden when its author edits it.
        review.updated_at = datetime.now(UTC)
    await session.flush()
    await recompute_agent_rating(session, agent)
    return review


async def delete_review(
    session: AsyncSession, agent: CustomAgent, user_id: UUID
) -> None:
    review = (
        await session.execute(
            select(AgentReview).where(
                AgentReview.agent_id == agent.id,
                AgentReview.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if review is None:
        raise AgentReviewError("not_found", "Review not found")
    await session.delete(review)
    await session.flush()
    await recompute_agent_rating(session, agent)


async def list_reviews(
    session: AsyncSession, agent_id: UUID, *, limit: int = 20
) -> list[dict[str, object]]:
    rows = await session.execute(
        select(AgentReview, User.email)
        .join(User, User.id == AgentReview.user_id)
        .where(AgentReview.agent_id == agent_id, AgentReview.status == "visible")
        .order_by(AgentReview.updated_at.desc())
        .limit(max(1, min(limit, 100)))
    )
    return [
        {
            "id": review.id,
            "rating": review.rating,
            "content": review.content,
            "author": mask_email(email),
            "created_at": review.created_at,
            "updated_at": review.updated_at,
        }
        for review, email in rows.all()
    ]


async def get_review(
    session: AsyncSession, agent_id: UUID, user_id: UUID
) -> AgentReview | None:
    return (
        await session.execute(
            select(AgentReview).where(
                AgentReview.agent_id == agent_id,
                AgentReview.user_id == user_id,
            )
        )
    ).scalar_one_or_none()


async def create_report(
    session: AsyncSession,
    agent: CustomAgent,
    *,
    reporter_user_id: UUID,
    reason: str,
    detail: str,
) -> AgentReport:
    if reason not in REPORT_REASONS:
        raise AgentReviewError("invalid_reason", "Invalid report reason")
    existing = (
        await session.execute(
            select(AgentReport.id).where(
                AgentReport.agent_id == agent.id,
                AgentReport.reporter_user_id == reporter_user_id,
                AgentReport.status == "open",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AgentReviewError("duplicate_report", "You already have an open report")
    report = AgentReport(
        agent_id=agent.id,
        reporter_user_id=reporter_user_id,
        reason=reason,
        detail=detail.strip(),
        status="open",
    )
    session.add(report)
    await session.flush()
    return report


async def list_reports(
    session: AsyncSession, *, status: str | None = None, limit: int = 100
) -> list[tuple[AgentReport, str, str]]:
    statement = (
        select(AgentReport, CustomAgent.name, User.email)
        .join(CustomAgent, CustomAgent.id == AgentReport.agent_id)
        .join(User, User.id == AgentReport.reporter_user_id)
        .order_by(AgentReport.created_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    if status is not None:
        statement = statement.where(AgentReport.status == status)
    rows = await session.execute(statement)
    return [(report, name, email) for report, name, email in rows.all()]


async def resolve_report(
    session: AsyncSession,
    report: AgentReport,
    *,
    action: str,
    resolution: str,
    admin_user_id: UUID,
) -> CustomAgent:
    if action not in REPORT_ACTIONS:
        raise AgentReviewError("invalid_action", "Invalid report action")
    agent = await session.get(CustomAgent, report.agent_id)
    if agent is None:
        raise AgentReviewError("not_found", "Agent not found")
    report.status = "dismissed" if action == "dismiss" else "resolved"
    report.resolution = resolution[:500]
    report.handled_by = admin_user_id
    report.handled_at = datetime.now(UTC)
    if action == "unpublish":
        agent.published = False
        agent.featured = False
        agent.published_at = None
    await session.flush()
    return agent

async def list_admin_reviews(
    session: AsyncSession,
    *,
    status_filter: str | None = None,
    agent_id: UUID | None = None,
    limit: int = 100,
) -> list[tuple[AgentReview, str, str]]:
    statement = (
        select(AgentReview, CustomAgent.name, User.email)
        .join(CustomAgent, CustomAgent.id == AgentReview.agent_id)
        .join(User, User.id == AgentReview.user_id)
        .order_by(AgentReview.updated_at.desc())
        .limit(max(1, min(limit, 200)))
    )
    if status_filter is not None:
        statement = statement.where(AgentReview.status == status_filter)
    if agent_id is not None:
        statement = statement.where(AgentReview.agent_id == agent_id)
    rows = await session.execute(statement)
    return [(review, name, email) for review, name, email in rows.all()]


async def set_review_visibility(
    session: AsyncSession, review: AgentReview, *, visible: bool
) -> AgentReview:
    review.status = "visible" if visible else "hidden"
    review.updated_at = datetime.now(UTC)
    agent = await session.get(CustomAgent, review.agent_id)
    if agent is not None:
        await recompute_agent_rating(session, agent)
    else:
        await session.flush()
    return review
