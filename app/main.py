from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import init_db
from app.routers import auth, knowledge_bases


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield


app = FastAPI(title="ai_power", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(knowledge_bases.router)
