from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.clients import close_redis
from app.config import get_settings
from app.db import init_db
from app.observability import RequestContextMiddleware, configure_logging
from app.routers import (
    api_keys,
    auth,
    conversations,
    documents,
    health,
    knowledge_bases,
    providers,
    usage,
)
from app.services.queue import close_queue


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()
    yield
    await close_queue()
    await close_redis()


configure_logging()

app = FastAPI(title="ai_power", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    expose_headers=["Retry-After"],
    max_age=600,
)
app.add_middleware(RequestContextMiddleware)
app.include_router(auth.router)
app.include_router(api_keys.router)
app.include_router(health.router)
app.include_router(usage.router)
app.include_router(providers.router)
app.include_router(conversations.router)
app.include_router(documents.router)
app.include_router(knowledge_bases.router)
