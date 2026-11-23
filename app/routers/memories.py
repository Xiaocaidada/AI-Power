from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.schemas import (
    MemoryBatchIn,
    MemoryBatchOut,
    MemoryCandidateAcceptIn,
    MemoryCandidateOut,
    MemoryIn,
    MemoryOut,
    MemoryRelationIn,
    MemoryRelationOut,
    MemorySettingsIn,
    MemorySettingsOut,
    MemoryStatsOut,
    MemoryUpdate,
    MemoryUsageOut,
    MemoryVersionOut,
)
from app.services.memories import (
    MemoryError,
    batch_update_memories,
    create_memory,
    create_memory_relation,
    delete_memory,
    delete_memory_relation,
    get_memory,
    get_memory_settings,
    list_memories,
    list_memory_relations,
    list_memory_usage,
    list_memory_versions,
    memory_stats,
    restore_memory_version,
    update_memory,
    update_memory_settings,
)
from app.services.memory_extraction import (
    accept_candidate,
    get_candidate,
    list_candidates,
    reject_candidate,
)

router = APIRouter(prefix="/memories", tags=["memories"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


def _error(exc: MemoryError) -> HTTPException:
    if exc.code in {"not_found", "project_not_found", "agent_not_found"}:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code == "secret_blocked":
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(code, {"code": exc.code, "message": exc.message})


def _memory_out(memory) -> MemoryOut:
    return MemoryOut.model_validate(memory)


@router.get("", response_model=list[MemoryOut])
async def list_workspace_memories(
    context: JwtContext,
    session: SessionDep,
    q: str = "",
    agent_id: UUID | None = None,
    project_id: UUID | None = None,
    scope: Literal["user", "workspace"] | None = None,
    scope_type: Literal["global", "project", "agent"] | None = None,
    category: str | None = None,
    status_filter: Annotated[
        Literal[
            "candidate", "active", "conflict", "expired", "archived", "rejected"
        ]
        | None,
        Query(alias="status"),
    ] = None,
    tag: str | None = None,
    favorite: bool | None = None,
    pinned: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MemoryOut]:
    try:
        rows = await list_memories(
            session,
            context.workspace.id,
            context.user.id,
            query=q,
            agent_id=agent_id,
            project_id=project_id,
            scope=scope,
            scope_type=scope_type,
            category=category,
            status=status_filter,
            tag=tag,
            favorite=favorite,
            pinned=pinned,
            limit=limit,
            offset=offset,
        )
    except MemoryError as exc:
        raise _error(exc) from None
    return [_memory_out(row) for row in rows]


@router.post("", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_workspace_memory(
    payload: MemoryIn, context: JwtContext, session: SessionDep
) -> MemoryOut:
    try:
        memory = await create_memory(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            content=payload.content,
            title=payload.title,
            scope=payload.scope,
            kind=payload.kind,
            agent_id=payload.agent_id,
            project_id=payload.project_id,
            scope_type=payload.scope_type,
            category=payload.category,
            status=payload.status,
            importance=payload.importance,
            source="manual",
            source_type=payload.source_type,
            source_id=payload.source_id,
            source_ref=payload.source_ref,
            confidence=payload.confidence,
            sensitivity=payload.sensitivity,
            tags=payload.tags,
            enabled=payload.enabled,
            pinned=payload.pinned,
            favorite=payload.favorite,
            valid_until=payload.valid_until,
            metadata=payload.metadata,
        )
    except MemoryError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(memory)
    return _memory_out(memory)


@router.get("/stats", response_model=MemoryStatsOut)
async def get_memory_stats(
    context: JwtContext, session: SessionDep
) -> MemoryStatsOut:
    stats = await memory_stats(session, context.workspace.id, context.user.id)
    return MemoryStatsOut.model_validate(stats)


@router.get("/settings", response_model=MemorySettingsOut)
async def get_memory_settings_endpoint(
    context: JwtContext, session: SessionDep
) -> MemorySettingsOut:
    row = await get_memory_settings(
        session, context.workspace.id, context.user.id
    )
    await session.commit()
    return MemorySettingsOut.model_validate(row)


@router.patch("/settings", response_model=MemorySettingsOut)
async def update_memory_settings_endpoint(
    payload: MemorySettingsIn, context: JwtContext, session: SessionDep
) -> MemorySettingsOut:
    row = await get_memory_settings(
        session, context.workspace.id, context.user.id
    )
    await update_memory_settings(
        session, row, **payload.model_dump(exclude_unset=True, exclude_none=True)
    )
    await session.commit()
    await session.refresh(row)
    return MemorySettingsOut.model_validate(row)


@router.get("/usage", response_model=list[MemoryUsageOut])
async def list_usage(
    context: JwtContext,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[MemoryUsageOut]:
    rows = await list_memory_usage(
        session, context.workspace.id, context.user.id, limit=limit
    )
    return [
        MemoryUsageOut(
            id=event.id,
            memory_id=event.memory_id,
            memory_title=title,
            context_type=event.context_type,
            context_id=event.context_id,
            provider_id=event.provider_id,
            model=event.model,
            relevance=event.relevance,
            injected_chars=event.injected_chars,
            created_at=event.created_at,
        )
        for event, title in rows
    ]


@router.post("/batch", response_model=MemoryBatchOut)
async def batch_update(
    payload: MemoryBatchIn, context: JwtContext, session: SessionDep
) -> MemoryBatchOut:
    try:
        updated = await batch_update_memories(
            session,
            context.workspace.id,
            context.user.id,
            payload.ids,
            status=payload.status,
            category=payload.category,
            scope_type=payload.scope_type,
            project_id=payload.project_id,
            agent_id=payload.agent_id,
            enabled=payload.enabled,
            tags=payload.tags,
        )
    except MemoryError as exc:
        raise _error(exc) from None
    await session.commit()
    return MemoryBatchOut(updated=updated)


@router.get("/candidates", response_model=list[MemoryCandidateOut])
async def list_memory_candidates(
    context: JwtContext,
    session: SessionDep,
    status_filter: Annotated[
        Literal["pending", "duplicate", "accepted", "rejected", "merged"]
        | None,
        Query(alias="status"),
    ] = "pending",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[MemoryCandidateOut]:
    rows = await list_candidates(
        session,
        context.workspace.id,
        context.user.id,
        status=status_filter or "pending",
        limit=limit,
    )
    return [MemoryCandidateOut.model_validate(row) for row in rows]


@router.post(
    "/candidates/{candidate_id}/accept", response_model=MemoryOut
)
async def accept_memory_candidate(
    candidate_id: UUID,
    payload: MemoryCandidateAcceptIn,
    context: JwtContext,
    session: SessionDep,
) -> MemoryOut:
    try:
        candidate = await get_candidate(
            session, context.workspace.id, context.user.id, candidate_id
        )
        if payload.title is not None:
            candidate.title = payload.title.strip()[:120]
        if payload.content is not None:
            candidate.content = payload.content.strip()
        if payload.category is not None:
            candidate.category = payload.category
        if payload.scope_type is not None:
            candidate.scope_type = payload.scope_type
        if payload.tags is not None:
            candidate.tags = payload.tags
        memory = await accept_candidate(
            session, candidate, user_id=context.user.id
        )
    except MemoryError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(memory)
    return _memory_out(memory)


@router.post(
    "/candidates/{candidate_id}/reject", response_model=MemoryCandidateOut
)
async def reject_memory_candidate(
    candidate_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> MemoryCandidateOut:
    try:
        candidate = await get_candidate(
            session, context.workspace.id, context.user.id, candidate_id
        )
        await reject_candidate(session, candidate)
    except MemoryError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(candidate)
    return MemoryCandidateOut.model_validate(candidate)


@router.get("/{memory_id}", response_model=MemoryOut)
async def get_memory_endpoint(
    memory_id: UUID, context: JwtContext, session: SessionDep
) -> MemoryOut:
    try:
        memory = await get_memory(
            session, context.workspace.id, context.user.id, memory_id
        )
    except MemoryError as exc:
        raise _error(exc) from None
    return _memory_out(memory)


@router.patch("/{memory_id}", response_model=MemoryOut)
async def update_workspace_memory(
    memory_id: UUID,
    payload: MemoryUpdate,
    context: JwtContext,
    session: SessionDep,
) -> MemoryOut:
    try:
        memory = await get_memory(
            session, context.workspace.id, context.user.id, memory_id
        )
        memory = await update_memory(
            session,
            memory,
            content=payload.content,
            title=payload.title,
            scope=payload.scope,
            kind=payload.kind,
            importance=payload.importance,
            scope_type=payload.scope_type,
            category=payload.category,
            status=payload.status,
            project_id=payload.project_id,
            agent_id=payload.agent_id,
            tags=payload.tags,
            enabled=payload.enabled,
            pinned=payload.pinned,
            favorite=payload.favorite,
            sensitivity=payload.sensitivity,
            confidence=payload.confidence,
            valid_until=payload.valid_until,
            metadata=payload.metadata,
            change_reason=payload.change_reason,
            changed_by=context.user.id,
        )
    except MemoryError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(memory)
    return _memory_out(memory)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace_memory(
    memory_id: UUID, context: JwtContext, session: SessionDep
) -> Response:
    try:
        memory = await get_memory(
            session, context.workspace.id, context.user.id, memory_id
        )
        await delete_memory(session, memory)
    except MemoryError as exc:
        raise _error(exc) from None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{memory_id}/versions", response_model=list[MemoryVersionOut])
async def list_versions(
    memory_id: UUID, context: JwtContext, session: SessionDep
) -> list[MemoryVersionOut]:
    try:
        memory = await get_memory(
            session, context.workspace.id, context.user.id, memory_id
        )
    except MemoryError as exc:
        raise _error(exc) from None
    rows = await list_memory_versions(session, memory)
    return [MemoryVersionOut.model_validate(row) for row in rows]


@router.post("/{memory_id}/versions/{version}/restore", response_model=MemoryOut)
async def restore_version(
    memory_id: UUID,
    version: int,
    context: JwtContext,
    session: SessionDep,
) -> MemoryOut:
    try:
        memory = await get_memory(
            session, context.workspace.id, context.user.id, memory_id
        )
        memory = await restore_memory_version(
            session, memory, version, changed_by=context.user.id
        )
    except MemoryError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(memory)
    return _memory_out(memory)


@router.get("/{memory_id}/relations", response_model=list[MemoryRelationOut])
async def list_relations(
    memory_id: UUID, context: JwtContext, session: SessionDep
) -> list[MemoryRelationOut]:
    try:
        await get_memory(session, context.workspace.id, context.user.id, memory_id)
    except MemoryError as exc:
        raise _error(exc) from None
    rows = await list_memory_relations(
        session, context.workspace.id, context.user.id, memory_id
    )
    return [MemoryRelationOut.model_validate(row) for row in rows]


@router.post("/{memory_id}/relations", response_model=MemoryRelationOut)
async def create_relation(
    memory_id: UUID,
    payload: MemoryRelationIn,
    context: JwtContext,
    session: SessionDep,
) -> MemoryRelationOut:
    try:
        await get_memory(session, context.workspace.id, context.user.id, memory_id)
        if payload.to_type == "memory":
            await get_memory(
                session, context.workspace.id, context.user.id, payload.to_id
            )
        relation = await create_memory_relation(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            from_type="memory",
            from_id=memory_id,
            to_type=payload.to_type,
            to_id=payload.to_id,
            relation_type=payload.relation_type,
            basis=payload.basis,
        )
    except MemoryError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(relation)
    return MemoryRelationOut.model_validate(relation)


@router.delete(
    "/{memory_id}/relations/{relation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_relation(
    memory_id: UUID,
    relation_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> Response:
    try:
        await get_memory(session, context.workspace.id, context.user.id, memory_id)
        await delete_memory_relation(
            session, context.workspace.id, context.user.id, relation_id
        )
    except MemoryError as exc:
        raise _error(exc) from None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)