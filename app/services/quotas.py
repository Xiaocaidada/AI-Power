import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike
from app.config import get_settings
from app.deps import AuthContext
from app.models import ApiKey, Document, KnowledgeBase

logger = logging.getLogger(__name__)

TOKEN_WINDOW_SECONDS = 2 * 24 * 3600
REQUEST_WINDOW_SECONDS = 120


@dataclass(frozen=True, slots=True)
class PlanLimits:
    requests_per_minute: int
    tokens_per_day: int
    max_keys: int
    daily_cost_usd: float
    max_kbs: int
    max_documents_per_kb: int
    max_kb_bytes: int


def plan_limits(plan: str) -> PlanLimits:
    settings = get_settings()
    if plan == "pro":
        return PlanLimits(
            requests_per_minute=settings.quota_pro_requests_per_minute,
            tokens_per_day=settings.quota_pro_tokens_per_day,
            max_keys=settings.quota_pro_max_keys,
            daily_cost_usd=settings.quota_pro_daily_cost_usd,
            max_kbs=settings.quota_pro_max_kbs,
            max_documents_per_kb=settings.quota_pro_max_documents_per_kb,
            max_kb_bytes=settings.quota_pro_max_kb_bytes,
        )
    return PlanLimits(
        requests_per_minute=settings.quota_free_requests_per_minute,
        tokens_per_day=settings.quota_free_tokens_per_day,
        max_keys=settings.quota_free_max_keys,
        daily_cost_usd=settings.quota_free_daily_cost_usd,
        max_kbs=settings.quota_free_max_kbs,
        max_documents_per_kb=settings.quota_free_max_documents_per_kb,
        max_kb_bytes=settings.quota_free_max_kb_bytes,
    )


def _request_key(scope: str, identifier: str) -> str:
    minute = int(time.time() // 60)
    return f"quota:req:{scope}:{identifier}:{minute}"


def _tokens_key(workspace_id: UUID) -> str:
    day = datetime.now(UTC).date().isoformat()
    return f"quota:tokens:ws:{workspace_id}:{day}"


def _minute_reset_seconds() -> int:
    return 60 - int(time.time()) % 60


def _day_reset_seconds() -> int:
    now = datetime.now(UTC)
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    return max(int((tomorrow - now).total_seconds()), 1)


def _quota_error(
    scope: str, metric: str, limit: int, remaining: int, reset_seconds: int
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "quota_exceeded",
            "scope": scope,
            "metric": metric,
            "message": f"Quota exceeded: {scope} {metric}",
        },
        headers={
            "Retry-After": str(reset_seconds),
            "X-Quota-Scope": scope,
            "X-Quota-Metric": metric,
            "X-Quota-Limit": str(limit),
            "X-Quota-Remaining": str(max(remaining, 0)),
            "X-Quota-Reset": str(reset_seconds),
        },
    )


async def enforce_quota(redis: RedisLike, context: AuthContext) -> None:
    limits = plan_limits(context.workspace.plan)
    try:
        workspace_key = _request_key("ws", str(context.workspace.id))
        count = await redis.incr(workspace_key)
        if count == 1:
            await redis.expire(workspace_key, REQUEST_WINDOW_SECONDS)
        if count > limits.requests_per_minute:
            raise _quota_error(
                "workspace",
                "requests_per_minute",
                limits.requests_per_minute,
                0,
                _minute_reset_seconds(),
            )

        if context.api_key_id is not None:
            key_limit = context.api_key_rate_limit or limits.requests_per_minute
            key_key = _request_key("key", str(context.api_key_id))
            key_count = await redis.incr(key_key)
            if key_count == 1:
                await redis.expire(key_key, REQUEST_WINDOW_SECONDS)
            if key_count > key_limit:
                raise _quota_error(
                    "api_key",
                    "requests_per_minute",
                    key_limit,
                    0,
                    _minute_reset_seconds(),
                )

        raw_tokens = await redis.get(_tokens_key(context.workspace.id))
        used_tokens = int(raw_tokens) if raw_tokens is not None else 0
        if used_tokens >= limits.tokens_per_day:
            raise _quota_error(
                "workspace",
                "tokens_per_day",
                limits.tokens_per_day,
                0,
                _day_reset_seconds(),
            )
    except HTTPException:
        raise
    except Exception:
        logger.warning("quota store unavailable; allowing request", exc_info=True)


async def add_token_usage(redis: RedisLike, workspace_id: UUID, tokens: int) -> None:
    if tokens <= 0:
        return
    try:
        key = _tokens_key(workspace_id)
        await redis.incrby(key, tokens)
        await redis.expire(key, TOKEN_WINDOW_SECONDS)
    except Exception:
        logger.warning("failed to record token usage", exc_info=True)


@dataclass(frozen=True, slots=True)
class QuotaSnapshot:
    plan: str
    request_limit: int
    request_used: int
    request_reset: int
    token_limit: int
    token_used: int
    token_reset: int
    max_keys: int
    active_keys: int
    max_kbs: int
    kb_count: int
    max_documents_per_kb: int
    max_kb_bytes: int
    kb_bytes: int


async def quota_snapshot(
    session: AsyncSession, redis: RedisLike, context: AuthContext
) -> QuotaSnapshot:
    limits = plan_limits(context.workspace.plan)
    try:
        raw_requests = await redis.get(_request_key("ws", str(context.workspace.id)))
        raw_tokens = await redis.get(_tokens_key(context.workspace.id))
        request_used = int(raw_requests) if raw_requests is not None else 0
        token_used = int(raw_tokens) if raw_tokens is not None else 0
    except Exception:
        logger.warning("quota store unavailable; reporting zero usage", exc_info=True)
        request_used = 0
        token_used = 0

    active_keys = (
        await session.execute(
            select(func.count())
            .select_from(ApiKey)
            .where(
                ApiKey.workspace_id == context.workspace.id,
                ApiKey.revoked_at.is_(None),
            )
        )
    ).scalar_one()
    kb_count = (
        await session.execute(
            select(func.count())
            .select_from(KnowledgeBase)
            .where(
                KnowledgeBase.workspace_id == context.workspace.id,
                KnowledgeBase.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    kb_bytes = (
        await session.execute(
            select(func.coalesce(func.sum(Document.size_bytes), 0)).where(
                Document.workspace_id == context.workspace.id,
                Document.deleted_at.is_(None),
            )
        )
    ).scalar_one()

    return QuotaSnapshot(
        plan=context.workspace.plan,
        request_limit=limits.requests_per_minute,
        request_used=request_used,
        request_reset=_minute_reset_seconds(),
        token_limit=limits.tokens_per_day,
        token_used=token_used,
        token_reset=_day_reset_seconds(),
        max_keys=limits.max_keys,
        active_keys=active_keys,
        max_kbs=limits.max_kbs,
        kb_count=int(kb_count),
        max_documents_per_kb=limits.max_documents_per_kb,
        max_kb_bytes=limits.max_kb_bytes,
        kb_bytes=int(kb_bytes),
    )


async def enforce_knowledge_base_creation(
    session: AsyncSession, context: AuthContext
) -> None:
    limits = plan_limits(context.workspace.plan)
    count = (
        await session.execute(
            select(func.count())
            .select_from(KnowledgeBase)
            .where(
                KnowledgeBase.workspace_id == context.workspace.id,
                KnowledgeBase.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    if count >= limits.max_kbs:
        raise _quota_error("workspace", "knowledge_bases", limits.max_kbs, 0, 3600)


async def enforce_kb_document_quota(
    session: AsyncSession,
    context: AuthContext,
    *,
    kb_id: UUID,
    additional_bytes: int = 0,
) -> None:
    limits = plan_limits(context.workspace.plan)
    count = (
        await session.execute(
            select(func.count())
            .select_from(Document)
            .where(
                Document.kb_id == kb_id,
                Document.workspace_id == context.workspace.id,
                Document.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    if count >= limits.max_documents_per_kb:
        raise _quota_error(
            "knowledge_base",
            "documents",
            limits.max_documents_per_kb,
            0,
            3600,
        )
    used = (
        await session.execute(
            select(func.coalesce(func.sum(Document.size_bytes), 0)).where(
                Document.kb_id == kb_id,
                Document.workspace_id == context.workspace.id,
                Document.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    if int(used) + max(additional_bytes, 0) > limits.max_kb_bytes:
        raise _quota_error(
            "knowledge_base",
            "bytes",
            limits.max_kb_bytes,
            max(limits.max_kb_bytes - int(used), 0),
            3600,
        )


async def enforce_key_creation(
    session: AsyncSession, context: AuthContext, redis: RedisLike
) -> None:
    limits = plan_limits(context.workspace.plan)
    active = (
        await session.execute(
            select(func.count())
            .select_from(ApiKey)
            .where(
                ApiKey.workspace_id == context.workspace.id,
                ApiKey.revoked_at.is_(None),
            )
        )
    ).scalar_one()
    if active >= limits.max_keys:
        raise _quota_error("workspace", "api_keys", limits.max_keys, 0, 60)
