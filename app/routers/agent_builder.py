from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, get_scoped_registry
from app.providers.registry import ProviderRegistry
from app.schemas import (
    AgentBuilderApplyIn,
    AgentBuilderIn,
    AgentBuilderMessageIn,
    AgentBuilderOut,
    AgentBuilderSessionCreate,
    AgentBuilderSessionOut,
    AgentBuilderTurnOut,
)
from app.services.agent_builder import (
    AgentBuilderError,
    AgentBuilderResult,
    append_builder_message,
    apply_builder_definition,
    build_run_context,
    create_builder_session,
    generate_agent_workflow,
    get_builder_session,
    list_builder_sessions,
    run_builder_turn,
)

router = APIRouter(prefix="/agent-builder", tags=["agent-builder"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_scoped_registry)]


def _http_error(exc: AgentBuilderError) -> HTTPException:
    code = (
        status.HTTP_404_NOT_FOUND
        if exc.code.endswith("_not_found")
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(code, {"code": exc.code, "message": exc.message})


def _session_out(row) -> AgentBuilderSessionOut:
    return AgentBuilderSessionOut(
        id=row.id,
        scope=row.scope,
        agent_id=row.agent_id,
        workflow_id=row.workflow_id,
        provider_id=row.provider_id,
        model=row.model,
        messages=list(row.messages or []),
        draft_definition=dict(row.draft_definition or {}),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _turn_out(
    session_id: UUID, result: AgentBuilderResult
) -> AgentBuilderTurnOut:
    return AgentBuilderTurnOut(
        session_id=session_id,
        message=result.message,
        definition=result.definition,
        diff=result.diff,
        missing_resources=result.missing_resources,
        suggestions=result.suggestions,
    )


@router.post("/generate", response_model=AgentBuilderOut)
async def generate_workflow(
    payload: AgentBuilderIn,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
) -> AgentBuilderOut:
    try:
        result = await generate_agent_workflow(
            session,
            registry,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            prompt=payload.prompt,
            provider_id=payload.provider_id,
            model=payload.model,
            current_definition=payload.current_definition,
            raw_agent_id=str(payload.agent_id) if payload.agent_id else None,
        )
    except AgentBuilderError as exc:
        raise _http_error(exc) from None
    if result.definition is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "invalid_generation", "message": "Model returned no definition"},
        )
    return AgentBuilderOut(
        definition=result.definition,
        summary=result.summary,
        missing_resources=result.missing_resources,
        provider_id=payload.provider_id,
        model=payload.model,
    )


@router.post(
    "/sessions",
    response_model=AgentBuilderSessionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    payload: AgentBuilderSessionCreate,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
) -> AgentBuilderSessionOut:
    try:
        registry.get(payload.provider_id)
    except Exception:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": "provider_not_found", "message": "Builder provider is not available"},
        ) from None
    try:
        row = await create_builder_session(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            agent_id=payload.agent_id,
            workflow_id=payload.workflow_id,
            provider_id=payload.provider_id,
            model=payload.model,
            draft_definition=payload.draft_definition,
            scope=payload.scope,
        )
    except AgentBuilderError as exc:
        raise _http_error(exc) from None
    await session.commit()
    await session.refresh(row)
    return _session_out(row)


@router.get("/sessions", response_model=list[AgentBuilderSessionOut])
async def list_sessions(
    context: JwtContext,
    session: SessionDep,
    agent_id: UUID | None = None,
    workflow_id: UUID | None = None,
    scope: str | None = None,
) -> list[AgentBuilderSessionOut]:
    rows = await list_builder_sessions(
        session,
        context.workspace.id,
        context.user.id,
        agent_id=agent_id,
        workflow_id=workflow_id,
        scope=scope,
    )
    return [_session_out(row) for row in rows]


@router.get(
    "/sessions/{session_id}", response_model=AgentBuilderSessionOut
)
async def get_session(
    session_id: UUID, context: JwtContext, session: SessionDep
) -> AgentBuilderSessionOut:
    try:
        row = await get_builder_session(
            session, session_id, context.workspace.id, context.user.id
        )
    except AgentBuilderError as exc:
        raise _http_error(exc) from None
    return _session_out(row)


@router.post(
    "/sessions/{session_id}/messages", response_model=AgentBuilderTurnOut
)
async def send_message(
    session_id: UUID,
    payload: AgentBuilderMessageIn,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
) -> AgentBuilderTurnOut:
    try:
        row = await get_builder_session(
            session, session_id, context.workspace.id, context.user.id
        )
    except AgentBuilderError as exc:
        raise _http_error(exc) from None
    current_definition = (
        payload.current_definition
        if payload.current_definition is not None
        else (dict(row.draft_definition) if row.draft_definition else None)
    )
    run_context = None
    if payload.run_id is not None:
        try:
            run_context = await build_run_context(
                session, payload.run_id, context.workspace.id
            )
        except AgentBuilderError as exc:
            raise _http_error(exc) from None
    try:
        result = await run_builder_turn(
            session,
            registry,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            kind=payload.kind,
            prompt=payload.prompt,
            provider_id=row.provider_id,
            model=row.model,
            current_definition=current_definition,
            raw_agent_id=str(row.agent_id) if row.agent_id else None,
            run_context=run_context,
            scope=row.scope,
        )
    except AgentBuilderError as exc:
        raise _http_error(exc) from None
    if current_definition is not None:
        row.draft_definition = current_definition
    append_builder_message(
        row,
        {
            "role": "user",
            "kind": payload.kind,
            "content": payload.prompt,
            "run_id": str(payload.run_id) if payload.run_id else None,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    append_builder_message(
        row,
        {
            "role": "assistant",
            "kind": payload.kind,
            "content": result.message,
            "summary": result.summary,
            "definition": result.definition,
            "diff": result.diff,
            "missing_resources": result.missing_resources,
            "suggestions": result.suggestions,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    await session.commit()
    return _turn_out(row.id, result)


@router.post(
    "/sessions/{session_id}/apply", response_model=AgentBuilderSessionOut
)
async def apply_definition(
    session_id: UUID,
    payload: AgentBuilderApplyIn,
    context: JwtContext,
    session: SessionDep,
) -> AgentBuilderSessionOut:
    try:
        row = await get_builder_session(
            session, session_id, context.workspace.id, context.user.id
        )
        await apply_builder_definition(session, row, payload.definition)
    except AgentBuilderError as exc:
        raise _http_error(exc) from None
    await session.commit()
    await session.refresh(row)
    return _session_out(row)