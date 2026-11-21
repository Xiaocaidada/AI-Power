import logging

from fastapi import HTTPException, Request, status

from app.clients import RedisLike
from app.config import get_settings

logger = logging.getLogger(__name__)

LOGIN_WINDOW_SECONDS = 60


async def enforce_login_rate_limit(request: Request, redis: RedisLike) -> None:
    """Fixed-window limit per client IP; fail open if Redis is unavailable."""
    settings = get_settings()
    client_host = request.client.host if request.client else "unknown"
    key = f"auth:login:{client_host}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, LOGIN_WINDOW_SECONDS)
        if count > settings.login_rate_limit_per_minute:
            ttl = await redis.ttl(key)
            retry_after = ttl if isinstance(ttl, int) and ttl > 0 else LOGIN_WINDOW_SECONDS
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "code": "login_rate_limited",
                    "message": "Too many login attempts, try again later",
                },
                headers={"Retry-After": str(retry_after)},
            )
    except HTTPException:
        raise
    except Exception:
        logger.warning("login rate limiter unavailable; allowing request", exc_info=True)
