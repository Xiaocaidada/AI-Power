from functools import lru_cache
from typing import Protocol

import redis.asyncio as redis_asyncio

from app.config import get_settings


class RedisLike(Protocol):
    async def incr(self, key: str) -> int: ...

    async def expire(self, key: str, seconds: int) -> bool: ...

    async def ttl(self, key: str) -> int: ...

    async def get(self, key: str) -> str | None: ...

    async def delete(self, key: str) -> int: ...

    async def ping(self) -> bool: ...

    async def aclose(self) -> None: ...


@lru_cache
def get_redis() -> RedisLike:
    settings = get_settings()
    return redis_asyncio.from_url(settings.redis_url, decode_responses=True)


async def close_redis() -> None:
    if get_redis.cache_info().currsize:
        await get_redis().aclose()
        get_redis.cache_clear()
