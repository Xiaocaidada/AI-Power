from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import RedisLike, get_redis
from app.db import get_session
from app.deps import AuthContext, get_jwt_context, get_scoped_registry
from app.models import Conversation, StudyAttempt
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas import (
    StudyAnswerIn,
    StudyAnswerOut,
    StudyAttemptOut,
    StudyQuizCreate,
    StudySessionCreate,
    StudySessionDetailOut,
    StudySessionOut,
    StudySessionUpdate,
)
from app.services.routing import route_candidates
from app.services.study import (
    DEFAULT_QUESTION_COUNT,
    StudyError,
    create_session,
    generate_quiz,
    grade_attempt,
    list_attempts,
    list_sessions,
    public_attempt,
    update_session,
)
from app.services.study import (
    get_session as get_study_session,
)

router = APIRouter(prefix="/study/sessions", tags=["study"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_scoped_registry)]
RedisDep = Annotated[RedisLike, Depends(get_redis)]


def _error(exc: StudyError) -> HTTPException:
    if exc.code in {
        "study_session_not_found",
        "conversation_not_found",
        "knowledge_base_not_found",
        "attempt_not_found",
    }:
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    if exc.code == "attempt_already_graded":
        return HTTPException(status.HTTP_409_CONFLICT, {"code": exc.code, "message": exc.message})
    if exc.code in {"quiz_generation_failed", "no_provider_available"}:
        return HTTPException(
            status.HTTP_502_BAD_GATEWAY, {"code": exc.code, "message": exc.message}
        )
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"code": exc.code, "message": exc.message},
    )


def _out(study) -> StudySessionOut:
    return StudySessionOut(
        id=study.id,
        conversation_id=study.conversation_id,
        topic=study.topic,
        level=study.level,
        mode=study.mode,
        goals=study.goals,
        kb_ids=list(study.kb_ids or []),
        status=study.status,
        mastery=study.mastery or {},
        created_at=study.created_at,
        updated_at=study.updated_at,
    )


@router.get("", response_model=list[StudySessionOut])
async def list_study_sessions(
    context: JwtContext,
    session: SessionDep,
    conversation_id: UUID | None = None,
    status_filter: str | None = None,
) -> list[StudySessionOut]:
    try:
        rows = await list_sessions(
            session,
            context.workspace.id,
            context.user.id,
            conversation_id=conversation_id,
            status=status_filter,
        )
    except StudyError as exc:
        raise _error(exc) from None
    return [_out(row) for row in rows]


@router.post("", response_model=StudySessionOut, status_code=status.HTTP_201_CREATED)
async def create_study_session(
    payload: StudySessionCreate,
    context: JwtContext,
    session: SessionDep,
) -> StudySessionOut:
    try:
        study = await create_session(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            topic=payload.topic,
            conversation_id=payload.conversation_id,
            level=payload.level,
            mode=payload.mode,
            goals=payload.goals,
            kb_ids=payload.kb_ids,
        )
    except StudyError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(study)
    return _out(study)


@router.get("/{session_id}", response_model=StudySessionDetailOut)
async def read_study_session(
    session_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> StudySessionDetailOut:
    try:
        study = await get_study_session(session, session_id, context.workspace.id, context.user.id)
        attempts = await list_attempts(session, study)
    except StudyError as exc:
        raise _error(exc) from None
    base = _out(study)
    return StudySessionDetailOut(
        **base.model_dump(),
        attempts=[StudyAttemptOut(**public_attempt(item)) for item in attempts],
    )


@router.patch("/{session_id}", response_model=StudySessionOut)
async def patch_study_session(
    session_id: UUID,
    payload: StudySessionUpdate,
    context: JwtContext,
    session: SessionDep,
) -> StudySessionOut:
    try:
        study = await get_study_session(session, session_id, context.workspace.id, context.user.id)
        study = await update_session(session, study, **payload.model_dump(exclude_unset=True))
    except StudyError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(study)
    return _out(study)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_study_session(
    session_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> Response:
    try:
        study = await get_study_session(session, session_id, context.workspace.id, context.user.id)
        study.status = "archived"
        await session.flush()
    except StudyError as exc:
        raise _error(exc) from None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _quiz_provider(
    session: AsyncSession,
    registry: ProviderRegistry,
    redis: RedisLike,
    context: AuthContext,
    study,
    payload: StudyQuizCreate,
) -> tuple[object, str]:
    provider_id = payload.provider_id
    model = payload.model
    if study.conversation_id is not None:
        conversation = await session.get(Conversation, study.conversation_id)
        if conversation is not None:
            provider_id = provider_id or conversation.provider_id
            model = model or conversation.model
    if provider_id is None or model is None:
        raise StudyError("model_required", "provider_id and model are required to generate a quiz")
    if provider_id == "auto" or model == "auto":
        for candidate_provider, candidate_model in await route_candidates(session, registry, redis):
            try:
                return registry.get(candidate_provider), candidate_model
            except ProviderError:
                continue
        raise StudyError("no_provider_available", "No provider is currently available")
    try:
        return registry.get(provider_id), model
    except ProviderError as exc:
        raise StudyError("provider_not_found", exc.message) from None


@router.post("/{session_id}/quiz", response_model=StudySessionDetailOut)
async def create_study_quiz(
    session_id: UUID,
    payload: StudyQuizCreate,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
    redis: RedisDep,
) -> StudySessionDetailOut:
    try:
        study = await get_study_session(session, session_id, context.workspace.id, context.user.id)
        provider, model = await _quiz_provider(session, registry, redis, context, study, payload)
        await generate_quiz(
            session,
            study,
            provider=provider,
            model=model,
            count=payload.count or DEFAULT_QUESTION_COUNT,
            types=list(payload.types) if payload.types else None,
        )
        attempts = await list_attempts(session, study)
    except StudyError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(study)
    base = _out(study)
    return StudySessionDetailOut(
        **base.model_dump(),
        attempts=[StudyAttemptOut(**public_attempt(item)) for item in attempts],
    )


@router.post("/{session_id}/attempts/{attempt_id}/answer", response_model=StudyAnswerOut)
async def answer_study_attempt(
    session_id: UUID,
    attempt_id: UUID,
    payload: StudyAnswerIn,
    context: JwtContext,
    session: SessionDep,
) -> StudyAnswerOut:
    try:
        study = await get_study_session(session, session_id, context.workspace.id, context.user.id)
        attempt = await session.get(StudyAttempt, attempt_id)
        if attempt is None or attempt.session_id != study.id:
            raise StudyError("attempt_not_found", "Study attempt not found")
        attempt = await grade_attempt(session, study, attempt, payload.answer)
    except StudyError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(study)
    await session.refresh(attempt)
    return StudyAnswerOut(
        attempt=StudyAttemptOut(**public_attempt(attempt)),
        mastery=study.mastery or {},
    )
