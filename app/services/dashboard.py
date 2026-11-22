from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Conversation,
    CustomAgent,
    KnowledgeBase,
    PluginConfig,
    Project,
    ProviderConfig,
    ProviderModel,
    UsageEvent,
)
from app.services.content import notification_feed

USAGE_WINDOW_DAYS = 30


async def dashboard_summary(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> dict[str, Any]:
    providers = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ProviderConfig)
                .where(
                    ProviderConfig.workspace_id == workspace_id,
                    ProviderConfig.deleted_at.is_(None),
                )
            )
        ).scalar_one()
    )
    models = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ProviderModel)
                .join(ProviderConfig, ProviderConfig.id == ProviderModel.config_id)
                .where(
                    ProviderConfig.workspace_id == workspace_id,
                    ProviderConfig.deleted_at.is_(None),
                    ProviderModel.enabled.is_(True),
                )
            )
        ).scalar_one()
    )
    conversations = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Conversation)
                .where(
                    Conversation.workspace_id == workspace_id,
                    Conversation.archived_at.is_(None),
                )
            )
        ).scalar_one()
    )
    projects = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Project)
                .where(
                    Project.workspace_id == workspace_id,
                    Project.archived_at.is_(None),
                )
            )
        ).scalar_one()
    )
    knowledge_bases = int(
        (
            await session.execute(
                select(func.count())
                .select_from(KnowledgeBase)
                .where(
                    KnowledgeBase.workspace_id == workspace_id,
                    KnowledgeBase.deleted_at.is_(None),
                )
            )
        ).scalar_one()
    )
    agents = int(
        (
            await session.execute(
                select(func.count())
                .select_from(CustomAgent)
                .where(
                    CustomAgent.workspace_id == workspace_id,
                    CustomAgent.archived_at.is_(None),
                    or_(
                        CustomAgent.owner_user_id == user_id,
                        CustomAgent.visibility == "shared",
                    ),
                )
            )
        ).scalar_one()
    )
    plugins = int(
        (
            await session.execute(
                select(func.count())
                .select_from(PluginConfig)
                .where(
                    PluginConfig.workspace_id == workspace_id,
                    PluginConfig.enabled.is_(True),
                )
            )
        ).scalar_one()
    )
    unread_notifications, _ = await notification_feed(session, user_id, limit=1)

    since = datetime.now(UTC) - timedelta(days=USAGE_WINDOW_DAYS)
    usage = (
        await session.execute(
            select(
                func.count(UsageEvent.id),
                func.coalesce(
                    func.sum(
                        func.coalesce(UsageEvent.prompt_tokens, 0)
                        + func.coalesce(UsageEvent.completion_tokens, 0)
                    ),
                    0,
                ),
                func.coalesce(func.sum(UsageEvent.cost), 0.0),
            ).where(
                UsageEvent.workspace_id == workspace_id,
                UsageEvent.created_at >= since,
            )
        )
    ).one()

    recent_conversations = list(
        (
            await session.execute(
                select(Conversation)
                .where(
                    Conversation.workspace_id == workspace_id,
                    Conversation.archived_at.is_(None),
                )
                .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
                .limit(5)
            )
        ).scalars()
    )
    recent_projects = list(
        (
            await session.execute(
                select(Project)
                .where(
                    Project.workspace_id == workspace_id,
                    Project.archived_at.is_(None),
                )
                .order_by(Project.updated_at.desc(), Project.id.desc())
                .limit(5)
            )
        ).scalars()
    )
    return {
        "counts": {
            "providers": providers,
            "models": models,
            "conversations": conversations,
            "projects": projects,
            "knowledge_bases": knowledge_bases,
            "agents": agents,
            "plugins": plugins,
            "unread_notifications": unread_notifications,
            "requests_30d": int(usage[0] or 0),
            "tokens_30d": int(usage[1] or 0),
            "cost_30d": float(usage[2] or 0.0),
        },
        "recent_conversations": recent_conversations,
        "recent_projects": recent_projects,
    }