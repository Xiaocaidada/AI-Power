from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.db import get_session
from app.deps import AuthContext, get_jwt_context, get_scoped_registry
from app.models import Skill, SkillRun
from app.providers.registry import ProviderRegistry
from app.schemas import (
    SkillCreate,
    SkillMatchOut,
    SkillOut,
    SkillRunIn,
    SkillRunOut,
    SkillUpdate,
)
from app.services.quotas import add_token_usage, enforce_quota
from app.services.skills import (
    SkillError,
    create_skill,
    delete_skill,
    get_skill,
    list_runs,
    list_skills,
    match_skills,
    run_skill,
    update_skill,
)

router = APIRouter(prefix="/skills", tags=["skills"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_scoped_registry)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]


def _error(exc: SkillError) -> HTTPException:
    if exc.code == "not_found":
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    if exc.code in {"name_exists", "skill_disabled"}:
        return HTTPException(status.HTTP_409_CONFLICT, {"code": exc.code, "message": exc.message})
    if exc.code in {
        "provider_not_found",
        "no_provider_available",
        "provider_unreachable",
        "provider_http_error",
    }:
        return HTTPException(
            status.HTTP_502_BAD_GATEWAY, {"code": exc.code, "message": exc.message}
        )
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"code": exc.code, "message": exc.message},
    )


def _out(skill: Skill, user_id: UUID) -> SkillOut:
    return SkillOut(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        instructions=skill.instructions,
        tool_names=list(skill.tool_names or []),
        shared=skill.shared,
        enabled=skill.enabled,
        owned=skill.owner_user_id == user_id,
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


def _run_out(run: SkillRun) -> SkillRunOut:
    return SkillRunOut(
        id=run.id,
        skill_id=run.skill_id,
        status=run.status,
        input=run.input,
        output=run.output,
        provider_id=run.provider_id,
        model=run.model,
        error_code=run.error_code,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        tool_records=list(run.tool_records or []),
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


@router.get("", response_model=list[SkillOut])
async def list_skill_rows(context: JwtContext, session: SessionDep) -> list[SkillOut]:
    return [
        _out(skill, context.user.id)
        for skill in await list_skills(session, context.workspace.id, context.user.id)
    ]


@router.get("/match", response_model=list[SkillMatchOut])
async def match_skill_rows(
    context: JwtContext, session: SessionDep, q: str = "", limit: int = 5
) -> list[SkillMatchOut]:
    rows = await match_skills(
        session, context.workspace.id, context.user.id, q, limit=limit
    )
    return [
        SkillMatchOut(id=skill.id, name=skill.name, description=skill.description, score=score)
        for skill, score in rows
    ]


@router.get("/runs/{run_id}", response_model=SkillRunOut)
async def read_skill_run(
    run_id: UUID, context: JwtContext, session: SessionDep
) -> SkillRunOut:
    run = await session.get(SkillRun, run_id)
    if run is None or run.workspace_id != context.workspace.id:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, {"code": "not_found", "message": "Skill run not found"}
        )
    return _run_out(run)


@router.post("", response_model=SkillOut, status_code=status.HTTP_201_CREATED)
async def create_skill_row(
    payload: SkillCreate, context: JwtContext, session: SessionDep
) -> SkillOut:
    try:
        skill = await create_skill(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            name=payload.name,
            description=payload.description,
            instructions=payload.instructions,
            tool_names=payload.tool_names,
            shared=payload.shared,
            enabled=payload.enabled,
        )
    except SkillError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(skill)
    return _out(skill, context.user.id)


@router.get("/{skill_id}", response_model=SkillOut)
async def read_skill_row(
    skill_id: UUID, context: JwtContext, session: SessionDep
) -> SkillOut:
    try:
        skill = await get_skill(session, skill_id, context.workspace.id, context.user.id)
    except SkillError as exc:
        raise _error(exc) from None
    return _out(skill, context.user.id)


@router.patch("/{skill_id}", response_model=SkillOut)
async def patch_skill_row(
    skill_id: UUID,
    payload: SkillUpdate,
    context: JwtContext,
    session: SessionDep,
) -> SkillOut:
    try:
        skill = await get_skill(
            session, skill_id, context.workspace.id, context.user.id, owner_only=True
        )
        skill = await update_skill(
            session,
            skill,
            name=payload.name,
            description=payload.description,
            instructions=payload.instructions,
            tool_names=payload.tool_names,
            shared=payload.shared,
            enabled=payload.enabled,
        )
    except SkillError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(skill)
    return _out(skill, context.user.id)


@router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill_row(
    skill_id: UUID, context: JwtContext, session: SessionDep
) -> None:
    try:
        skill = await get_skill(
            session, skill_id, context.workspace.id, context.user.id, owner_only=True
        )
        await delete_skill(session, skill)
    except SkillError as exc:
        raise _error(exc) from None
    await session.commit()


@router.get("/{skill_id}/runs", response_model=list[SkillRunOut])
async def list_skill_runs(
    skill_id: UUID, context: JwtContext, session: SessionDep, limit: int = 50
) -> list[SkillRunOut]:
    try:
        await get_skill(session, skill_id, context.workspace.id, context.user.id)
    except SkillError as exc:
        raise _error(exc) from None
    return [
        _run_out(run)
        for run in await list_runs(session, skill_id, context.workspace.id, limit=limit)
    ]


@router.post("/{skill_id}/run", response_model=SkillRunOut)
async def run_skill_row(
    skill_id: UUID,
    payload: SkillRunIn,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
    redis: RedisDep,
) -> SkillRunOut:
    try:
        skill = await get_skill(session, skill_id, context.workspace.id, context.user.id)
    except SkillError as exc:
        raise _error(exc) from None
    await enforce_quota(redis, context)
    try:
        run = await run_skill(
            session,
            skill=skill,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            content=payload.input,
            provider_id=payload.provider_id,
            model=payload.model,
            registry=registry,
            redis=redis,
        )
    except SkillError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(run)
    await add_token_usage(
        redis,
        context.workspace.id,
        (run.prompt_tokens or 0) + (run.completion_tokens or 0),
    )
    return _run_out(run)