from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import init_db
from app.routers import auth, conversations, knowledge_bases, providers


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()
    yield


app = FastAPI(title="ai_power", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(providers.router)
app.include_router(conversations.router)
app.include_router(knowledge_bases.router)
