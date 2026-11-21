from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.clients import close_redis
from app.config import get_settings
from app.db import init_db
from app.observability import RequestContextMiddleware, configure_logging
from app.routers import (
    admin,
    api_keys,
    auth,
    collaborations,
    conversations,
    documents,
    health,
    knowledge_bases,
    models,
    prompts,
    providers,
    traces,
    usage,
    workflows,
    workspaces,
)
from app.services.queue import close_queue


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()
    yield
    await close_queue()
    await close_redis()


configure_logging()

OPENAPI_TAGS = [
    {"name": "auth", "description": "Registration, login, refresh, and account lookup."},
    {"name": "api-keys", "description": "Workspace API keys with chat/kb scopes."},
    {"name": "conversations", "description": "Chat sessions and SSE streaming messages."},
    {"name": "documents", "description": "Upload, list, retry, and delete documents."},
    {"name": "knowledge-bases", "description": "Workspace knowledge bases."},
    {"name": "models", "description": "Model catalog, health, and comparison."},
    {"name": "prompt-templates", "description": "Versioned workspace prompt templates."},
    {"name": "usage", "description": "Quota, token usage, and cost summaries."},
    {"name": "traces", "description": "Per-request timing and routing metadata."},
    {"name": "workspaces", "description": "Workspace membership and switching."},
    {"name": "admin", "description": "Platform admin endpoints (admin role only)."},
    {"name": "workflows", "description": "Versioned workflow definitions and runs."},
    {"name": "collaborations", "description": "Planner/worker/critic collaboration runs."},
    {"name": "providers", "description": "Configured provider metadata."},
    {"name": "health", "description": "Liveness and readiness probes."},
]

app = FastAPI(
    title="AI Power API",
    version="0.3.0",
    description=(
        "Multi-tenant AI platform: streaming chat, RAG knowledge bases, model catalog "
        "with auto routing, quotas, traces, multi-agent tools, prompt templates, cost "
        "reporting, and an admin console. See docs/api/quickstart.md for examples."
    ),
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    expose_headers=["Retry-After"],
    max_age=600,
)
app.add_middleware(RequestContextMiddleware)
app.include_router(auth.router)
app.include_router(api_keys.router)
app.include_router(health.router)
app.include_router(usage.router)
app.include_router(workspaces.router)
app.include_router(traces.router)
app.include_router(providers.router)
app.include_router(models.router)
app.include_router(conversations.router)
app.include_router(documents.router)
app.include_router(knowledge_bases.router)
app.include_router(prompts.router)
app.include_router(admin.router)
app.include_router(workflows.router)
app.include_router(collaborations.router)
