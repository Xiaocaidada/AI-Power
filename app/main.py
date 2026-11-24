from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.clients import close_redis
from app.config import get_settings
from app.db import init_db
from app.metrics import MetricsMiddleware
from app.observability import RequestContextMiddleware, configure_logging
from app.routers import (
    admin,
    agent_builder,
    agent_market,
    agents,
    api_keys,
    arena,
    attachments,
    auth,
    chat_modes,
    code_snippets,
    collaborations,
    content,
    conversations,
    dashboard,
    database_connections,
    documents,
    evaluations,
    files,
    health,
    knowledge_bases,
    market,
    mcp_servers,
    memories,
    model_eval,
    models,
    plugins,
    project_tasks,
    projects,
    prompt_lab,
    prompts,
    provider_configs,
    providers,
    reuse,
    search,
    search_providers,
    shares,
    study,
    traces,
    usage,
    webhooks,
    workflow_reviews,
    workflows,
    workspaces,
)
from app.routers import (
    metrics as metrics_router,
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
    {"name": "attachments", "description": "Chat file attachments with workspace isolation."},
    {"name": "arena", "description": "Parallel multi-model comparison rounds."},
    {"name": "prompt-lab", "description": "Prompt experiments with snapshot history."},
    {"name": "model-eval", "description": "Model evaluation datasets, runs, and reports."},
    {"name": "documents", "description": "Upload, list, retry, and delete documents."},
    {"name": "knowledge-bases", "description": "Workspace knowledge bases."},
    {
        "name": "evaluations",
        "description": "Retrieval and LLM-as-judge evaluation datasets and runs.",
    },
    {"name": "webhooks", "description": "Workspace webhook subscriptions and delivery logs."},
    {"name": "models", "description": "Model catalog, health, and comparison."},
    {"name": "market", "description": "Public model marketplace (unauthenticated)."},
    {
        "name": "content",
        "description": "Public home feed and announcements (unauthenticated).",
    },
    {"name": "notifications", "description": "Authenticated announcement read receipts."},
    {"name": "projects", "description": "Workspace projects and conversation defaults."},
    {"name": "agents", "description": "Agent marketplace and custom agents."},
    {"name": "plugins", "description": "Plugin marketplace, configuration, and calls."},
    {"name": "dashboard", "description": "Personal console aggregation."},
    {"name": "search", "description": "Workspace-wide search across resources."},
    {"name": "files", "description": "Cross-KB file center and downloads."},
    {"name": "prompt-templates", "description": "Versioned workspace prompt templates."},
    {"name": "usage", "description": "Quota, token usage, and cost summaries."},
    {"name": "traces", "description": "Per-request timing and routing metadata."},
    {"name": "workspaces", "description": "Workspace membership and switching."},
    {"name": "admin", "description": "Platform admin endpoints (admin role only)."},
    {"name": "workflows", "description": "Versioned workflow definitions and async runs."},
    {"name": "collaborations", "description": "Planner/worker/critic async collaboration runs."},
    {"name": "providers", "description": "Configured provider metadata."},
    {"name": "provider-configs", "description": "User-owned model provider configurations."},
    {"name": "health", "description": "Liveness and readiness probes."},
]

app = FastAPI(
    title="AI Power API",
    version="0.7.0",
    description=(
        "Multi-tenant AI platform: streaming chat, hybrid RAG knowledge bases, model catalog "
        "with auto routing, quotas, traces, multi-agent tools, workflows, prompt templates, "
        "retrieval/LLM-judge evaluation, webhooks, unified usage ledger, async runs, "
        "cost reporting, and an admin console. "
        "See docs/api/quickstart.md for examples."
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
app.add_middleware(MetricsMiddleware)
app.include_router(auth.router)
app.include_router(api_keys.router)
app.include_router(health.router)
app.include_router(usage.router)
app.include_router(workspaces.router)
app.include_router(traces.router)
app.include_router(providers.router)
app.include_router(provider_configs.router)
app.include_router(models.router)
app.include_router(chat_modes.router)
app.include_router(search_providers.router)
app.include_router(study.router)
app.include_router(reuse.router)
app.include_router(code_snippets.router)
app.include_router(project_tasks.router)
app.include_router(shares.router)
app.include_router(market.router)
app.include_router(market.admin_router)
app.include_router(content.router)
app.include_router(content.notifications_router)
app.include_router(content.admin_router)
app.include_router(projects.router)
app.include_router(agents.router)
app.include_router(agents.tool_router)
app.include_router(agent_market.router)
app.include_router(agent_market.admin_router)
app.include_router(agent_market.reports_router)
app.include_router(agent_market.reviews_admin_router)
app.include_router(agent_builder.router)
app.include_router(plugins.router)
app.include_router(plugins.admin_router)
app.include_router(database_connections.router)
app.include_router(database_connections.admin_router)
app.include_router(mcp_servers.router)
app.include_router(mcp_servers.admin_router)
app.include_router(memories.router)
app.include_router(dashboard.router)
app.include_router(search.router)
app.include_router(files.router)
app.include_router(conversations.router)
app.include_router(conversations.messages_router)
app.include_router(attachments.router)
app.include_router(arena.router)
app.include_router(prompt_lab.router)
app.include_router(model_eval.router)
app.include_router(documents.router)
app.include_router(knowledge_bases.router)
app.include_router(evaluations.router)
app.include_router(webhooks.router)
app.include_router(prompts.router)
app.include_router(prompts.admin_router)
app.include_router(admin.router)
app.include_router(workflow_reviews.router)
app.include_router(workflows.router)
app.include_router(collaborations.router)
app.include_router(metrics_router.router)
