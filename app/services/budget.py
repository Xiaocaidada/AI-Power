import logging
from datetime import UTC, datetime
from uuid import UUID

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike
from app.config import get_settings
from app.models import AuditLog, UsageEvent, Workspace
from app.services.quotas import plan_limits

logger = logging.getLogger(__name__)

ALERT_TTL_SECONDS = 24 * 3600


async def check_workspace_budget(
    session: AsyncSession, redis: RedisLike | None, workspace_id: UUID
) -> bool:
    """Write one audit alert per day when a workspace exceeds its daily cost budget."""
    workspace = await session.get(Workspace, workspace_id)
    if workspace is None:
        return False
    limit = plan_limits(workspace.plan).daily_cost_usd
    day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    total = (
        await session.execute(
            select(func.coalesce(func.sum(UsageEvent.cost), 0.0)).where(
                UsageEvent.workspace_id == workspace_id,
                UsageEvent.created_at >= day_start,
            )
        )
    ).scalar_one()
    cost = float(total)
    if cost <= limit:
        return False
    if redis is None:
        return False
    key = f"budget:alert:{workspace_id}:{day_start.date().isoformat()}"
    try:
        first = await redis.incr(key)
        if first == 1:
            await redis.expire(key, ALERT_TTL_SECONDS)
    except Exception:
        logger.warning("budget alert store unavailable", exc_info=True)
        return False
    if first != 1:
        return False
    session.add(
        AuditLog(
            actor_user_id=None,
            action="budget.exceeded",
            target_type="workspace",
            target_id=str(workspace_id),
            detail={
                "plan": workspace.plan,
                "cost_usd": round(cost, 6),
                "limit_usd": limit,
                "date": day_start.date().isoformat(),
            },
        )
    )
    await session.flush()
    await _send_webhook(workspace, cost, limit, day_start)
    return True


async def _send_webhook(
    workspace: Workspace, cost: float, limit: float, day_start: datetime
) -> None:
    url = get_settings().budget_webhook_url.strip()
    if not url:
        return
    payload = {
        "workspace_id": str(workspace.id),
        "workspace_name": workspace.name,
        "plan": workspace.plan,
        "cost_usd": round(cost, 6),
        "limit_usd": limit,
        "date": day_start.date().isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(url, json=payload)
    except Exception:
        logger.warning("budget webhook failed", exc_info=True)
