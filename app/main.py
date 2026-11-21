from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.clients import close_redis
from app.db import init_db
from app.routers import auth, conversations, documents, health, knowledge_bases, providers
from app.services.queue import close_queue


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()
    yield
    await close_queue()
    await close_redis()


app = FastAPI(title="ai_power", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(health.router)
app.include_router(providers.router)
app.include_router(conversations.router)
app.include_router(documents.router)
app.include_router(knowledge_bases.router)
