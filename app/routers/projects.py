from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, get_scoped_registry
from app.models import AuditLog, Project
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas import ProjectCreate, ProjectOut, ProjectUpdate
from app.services.access import get_owned_knowledge_base
from app.services.projects import (
    ProjectError,
    archive_project,
    can_manage,
    create_project,
    get_project,
    list_projects,
    project_conversation_count,
    update_project,
)
from app.services.provider_configs import ProviderConfigError, ensure_model_capability

router = APIRouter(prefix="/projects", tags=["projects"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_scoped_registry)]


def _project_out(project: Project, count: int, context: AuthContext) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        instructions=project.instructions,
        default_provider_id=project.default_provider_id,
        default_model=project.default_model,
        default_kb_id=project.default_kb_id,
        default_agent=project.default_agent,
        archived=project.archived_at is not None,
        conversation_count=count,
        owned=can_manage(project, context.user.id, context.role),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _defaults_error(exc: ProviderConfigError) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND
        if exc.code in {"not_found", "model_not_found"}
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    return HTTPException(status_code, {"code": exc.code, "message": exc.message})


async def _validate_defaults(
    session: AsyncSession,
    registry: ProviderRegistry,
    context: AuthContext,
    *,
    provider_id: str | None,
    model: str | None,
    agent: bool,
    kb_id: UUID | None,
) -> None:
    if provider_id is None:
        if model is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "invalid_defaults", "message": "default_model requires a provider"},
            )
    elif provider_id != "auto":
        if not model:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "invalid_defaults", "message": "default_model is required"},
            )
        try:
            registry.get(provider_id)
            await ensure_model_capability(
                session,
                workspace_id=context.workspace.id,
                user_id=context.user.id,
                provider_id=provider_id,
                model_id=model,
                capability="tools" if agent else "chat",
            )
        except ProviderError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
        except ProviderConfigError as exc:
            raise _defaults_error(exc) from None
    if kb_id is not None:
        await get_owned_knowledge_base(kb_id, context.workspace.id, session)


def _normalize_pair(provider_id: str | None, model: str | None) -> tuple[str | None, str | None]:
    if provider_id is None:
        return None, None
    if provider_id == "auto":
        return "auto", "auto"
    return provider_id, model


@router.get("", response_model=list[ProjectOut])
async def list_workspace_projects(
    context: JwtContext,
    session: SessionDep,
    archived: bool = False,
) -> list[ProjectOut]:
    rows = await list_projects(session, context.workspace.id, include_archived=archived)
    return [_project_out(project, count, context) for project, count in rows]


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_workspace_project(
    payload: ProjectCreate,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
) -> ProjectOut:
    provider_id, model = _normalize_pair(payload.default_provider_id, payload.default_model)
    await _validate_defaults(
        session,
        registry,
        context,
        provider_id=provider_id,
        model=model,
        agent=payload.default_agent,
        kb_id=payload.default_kb_id,
    )
    values = payload.model_dump()
    values["default_provider_id"] = provider_id
    values["default_model"] = model
    project = await create_project(
        session,
        workspace_id=context.workspace.id,
        owner_user_id=context.user.id,
        values=values,
    )
    await session.commit()
    await session.refresh(project)
    return _project_out(project, 0, context)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_workspace_project(
    project_id: UUID, context: JwtContext, session: SessionDep
) -> ProjectOut:
    try:
        project = await get_project(
            session, context.workspace.id, project_id, include_archived=True
        )
    except ProjectError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    count = await project_conversation_count(session, project.id)
    return _project_out(project, count, context)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_workspace_project(
    project_id: UUID,
    payload: ProjectUpdate,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
) -> ProjectOut:
    try:
        project = await get_project(
            session, context.workspace.id, project_id, include_archived=True
        )
    except ProjectError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    if not can_manage(project, context.user.id, context.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the project owner can edit")

    data = payload.model_dump(exclude_unset=True)
    provider_id = data.get("default_provider_id", project.default_provider_id)
    model = data.get("default_model", project.default_model)
    agent = data.get("default_agent", project.default_agent)
    kb_id = data.get("default_kb_id", project.default_kb_id)
    if "default_provider_id" in data and provider_id not in (None, "auto"):
        if "default_model" not in data and project.default_provider_id != provider_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                {"code": "invalid_defaults", "message": "default_model is required"},
            )
    provider_id, model = _normalize_pair(provider_id, model)
    await _validate_defaults(
        session,
        registry,
        context,
        provider_id=provider_id,
        model=model,
        agent=agent,
        kb_id=kb_id,
    )
    data["default_provider_id"] = provider_id
    data["default_model"] = model
    project = await update_project(session, project, data)
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="project.update",
            target_type="project",
            target_id=str(project.id),
            detail={"archived": project.archived_at is not None},
        )
    )
    await session.commit()
    await session.refresh(project)
    count = await project_conversation_count(session, project.id)
    return _project_out(project, count, context)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_workspace_project(
    project_id: UUID, context: JwtContext, session: SessionDep
) -> Response:
    try:
        project = await get_project(
            session, context.workspace.id, project_id, include_archived=True
        )
    except ProjectError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None
    if not can_manage(project, context.user.id, context.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the project owner can archive")
    await archive_project(session, project)
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action="project.archive",
            target_type="project",
            target_id=str(project.id),
            detail={},
        )
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)