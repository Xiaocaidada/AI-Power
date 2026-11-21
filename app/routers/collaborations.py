import asyncio
import json
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.registry import AgentRegistry
from app.clients import RedisLike, get_redis
from app.db import get_session
from app.deps import (
    AuthContext,
    get_agent_registry,
    get_jwt_context,
    get_registry,
    get_tool_registry,
    require_scope,
)
from app.metrics import track_sse_stream
from app.models import CollaborationRun, CollaborationStep
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas import (
    CollaborationRunCreate,
    CollaborationRunOut,
    CollaborationStepOut,
)
from app.services.access import get_owned_knowledge_base
from app.services.collaboration import CollaborationRunner
from app.services.quotas import enforce_quota
from app.tools.base import ToolRegistry

router = APIRouter(prefix="/collaborations", tags=["collaborations"])
logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ChatContext = Annotated[AuthContext, Depends(require_scope("chat:write"))]
RedisDep = Annotated[RedisLike, Depends(get_redis)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_registry)]
ToolRegistryDep = Annotated[ToolRegistry, Depends(get_tool_registry)]
AgentRegistryDep = Annotated[AgentRegistry, Depends(get_agent_registry)]


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/runs")
async def create_collaboration_run(
    payload: CollaborationRunCreate,
    context: ChatContext,
    session: SessionDep,
    registry: RegistryDep,
    tool_registry: ToolRegistryDep,
    agent_registry: AgentRegistryDep,
    redis: RedisDep,
) -> StreamingResponse:
    try:
        registry.get(payload.provider_id)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    if payload.kb_id is not None:
        await get_owned_knowledge_base(payload.kb_id, context.workspace.id, session)
    await enforce_quota(redis, context)

    run = CollaborationRun(
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        provider_id=payload.provider_id,
        model=payload.model,
        kb_id=payload.kb_id,
        status="running",
        input_text=payload.input,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    run_id = run.id
    await session.close()

    runner = CollaborationRunner(
        run_id=run_id,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        provider_id=payload.provider_id,
        model=payload.model,
        kb_id=payload.kb_id,
        redis=redis,
        input_text=payload.input,
        provider_registry=registry,
        tool_registry=tool_registry,
        agent_registry=agent_registry,
        quota_guard=lambda: enforce_quota(redis, context),
    )

    async def stream():
        try:
            async for event in runner.run():
                yield _sse(event.kind, event.data)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("collaboration stream failed for run %s", run_id)
            yield _sse(
                "collaboration_end",
                {
                    "run_id": str(run_id),
                    "status": "failed",
                    "error_code": "internal_error",
                },
            )

    return StreamingResponse(
        track_sse_stream(stream()),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}", response_model=CollaborationRunOut)
async def get_collaboration_run(
    run_id: UUID,
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
) -> CollaborationRunOut:
    run = (
        await session.execute(
            select(CollaborationRun).where(
                CollaborationRun.id == run_id,
                CollaborationRun.workspace_id == context.workspace.id,
            )
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Collaboration run not found")
    steps = (
        await session.execute(
            select(CollaborationStep)
            .where(CollaborationStep.run_id == run.id)
            .order_by(CollaborationStep.created_at, CollaborationStep.id)
        )
    ).scalars()
    return CollaborationRunOut(
        **CollaborationRunOut.model_validate(run).model_dump(exclude={"steps"}),
        steps=[CollaborationStepOut.model_validate(step) for step in steps],
    )


@router.get("/runs", response_model=list[CollaborationRunOut])
async def list_collaboration_runs(
    context: Annotated[AuthContext, Depends(get_jwt_context)],
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: UUID | None = None,
) -> list[CollaborationRunOut]:
    conditions = [CollaborationRun.workspace_id == context.workspace.id]
    if before is not None:
        conditions.append(CollaborationRun.id < before)
    runs = (
        await session.execute(
            select(CollaborationRun)
            .where(*conditions)
            .order_by(CollaborationRun.id.desc())
            .limit(limit)
        )
    ).scalars()
    return [CollaborationRunOut.model_validate(run) for run in runs]
