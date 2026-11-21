import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.db import get_session

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(session: SessionDep, redis: RedisDep) -> JSONResponse:
    checks = {"database": "ok", "redis": "ok"}
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        checks["database"] = "error"
        logger.warning("readiness: database check failed", exc_info=True)
    try:
        await redis.ping()
    except Exception:
        checks["redis"] = "error"
        logger.warning("readiness: redis check failed", exc_info=True)

    ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ok" if ready else "degraded", "checks": checks},
    )
