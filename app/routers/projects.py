import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, get_scoped_registry
from app.models import AuditLog, CustomAgent, Project
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas import (
    ProjectAgentIn,
    ProjectAgentOut,
    ProjectCreate,
    ProjectFileIn,
    ProjectFileOut,
    ProjectOut,
    ProjectUpdate,
)
from app.services.access import get_owned_knowledge_base
from app.services.memory_extraction import create_project_memory_candidate
from app.services.memory_permissions import normalize_project_permissions
from app.services.project_resources import (
    ProjectResourceError,
    add_project_agent,
    add_project_document,
    list_project_agents,
    list_project_documents,
    remove_project_agent,
    remove_project_document,
)
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
logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_scoped_registry)]


def _project_out(project: Project, count: int, context: AuthContext) -> ProjectOut:
    permissions = normalize_project_permissions(project.memory_permissions)
    return ProjectOut(
        id=project.id,
        name=project.name,
        description=project.description,
        instructions=project.instructions,
        default_provider_id=project.default_provider_id,
        default_model=project.default_model,
        default_kb_id=project.default_kb_id,
        kb_ids=[UUID(item) for item in project.kb_ids],
        default_custom_agent_id=project.default_custom_agent_id,
        default_agent=project.default_agent,
        memory_enabled=permissions["enabled"],
        allow_global_memory=bool(permissions["allow_global"]),
        allow_agent_writes=bool(permissions["allow_agent_writes"]),
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


def _resource_error(exc: ProjectResourceError) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND
        if exc.code.endswith("_not_found")
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
    kb_ids: list[UUID] | None = None,
    custom_agent_id: UUID | None = None,
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
    for item in kb_ids or []:
        await get_owned_knowledge_base(item, context.workspace.id, session)
    if custom_agent_id is not None:
        custom_agent = await session.get(CustomAgent, custom_agent_id)
        if (
            custom_agent is None
            or custom_agent.workspace_id != context.workspace.id
            or custom_agent.archived_at is not None
            or (
                custom_agent.owner_user_id != context.user.id
                and custom_agent.visibility != "shared"
                and context.role != "owner"
            )
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Agent not found")


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
        kb_ids=payload.kb_ids,
        custom_agent_id=payload.default_custom_agent_id,
    )
    values = payload.model_dump()
    values["default_provider_id"] = provider_id
    values["default_model"] = model
    values["kb_ids"] = [str(item) for item in dict.fromkeys(payload.kb_ids)]
    values["memory_permissions"] = normalize_project_permissions(
        {
            "enabled": values.pop("memory_enabled", None),
            "allow_global": values.pop("allow_global_memory", True),
            "allow_agent_writes": values.pop("allow_agent_writes", False),
        }
    )
    project = await create_project(
        session,
        workspace_id=context.workspace.id,
        owner_user_id=context.user.id,
        values=values,
    )
    if project.default_custom_agent_id is not None:
        await add_project_agent(
            session,
            project,
            agent_id=project.default_custom_agent_id,
            user_id=context.user.id,
            workspace_role=context.role,
            set_default=True,
        )
    await session.commit()
    await session.refresh(project)
    try:
        await create_project_memory_candidate(session, project, context.user.id)
        await session.commit()
    except Exception:
        logger.warning("project memory candidate failed", exc_info=True)
        await session.rollback()
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
    memory_keys = ("memory_enabled", "allow_global_memory", "allow_agent_writes")
    if any(key in data for key in memory_keys):
        current = normalize_project_permissions(project.memory_permissions)
        data["memory_permissions"] = normalize_project_permissions(
            {
                "enabled": data.pop("memory_enabled", current["enabled"]),
                "allow_global": data.pop(
                    "allow_global_memory", current["allow_global"]
                ),
                "allow_agent_writes": data.pop(
                    "allow_agent_writes", current["allow_agent_writes"]
                ),
            }
        )
    provider_id = data.get("default_provider_id", project.default_provider_id)
    model = data.get("default_model", project.default_model)
    agent = data.get("default_agent", project.default_agent)
    kb_id = data.get("default_kb_id", project.default_kb_id)
    custom_agent_id = data.get(
        "default_custom_agent_id", project.default_custom_agent_id
    )
    if "kb_ids" in data:
        kb_ids = list(dict.fromkeys(data["kb_ids"] or []))
    else:
        kb_ids = [UUID(item) for item in project.kb_ids]
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
        kb_ids=kb_ids,
        custom_agent_id=custom_agent_id,
    )
    data["default_provider_id"] = provider_id
    data["default_model"] = model
    if "kb_ids" in data:
        data["kb_ids"] = [str(item) for item in kb_ids]
    project = await update_project(session, project, data)
    if project.default_custom_agent_id is not None:
        await add_project_agent(
            session,
            project,
            agent_id=project.default_custom_agent_id,
            user_id=context.user.id,
            workspace_role=context.role,
            set_default=True,
        )
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
    try:
        await create_project_memory_candidate(session, project, context.user.id)
        await session.commit()
    except Exception:
        logger.warning("project memory candidate failed", exc_info=True)
        await session.rollback()
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


async def _load_project(
    project_id: UUID, context: AuthContext, session: AsyncSession
) -> Project:
    try:
        return await get_project(
            session, context.workspace.id, project_id, include_archived=True
        )
    except ProjectError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, exc.message) from None


@router.get("/{project_id}/agents", response_model=list[ProjectAgentOut])
async def list_workspace_project_agents(
    project_id: UUID, context: JwtContext, session: SessionDep
) -> list[ProjectAgentOut]:
    project = await _load_project(project_id, context, session)
    rows = await list_project_agents(session, project)
    return [
        ProjectAgentOut(
            agent_id=agent.id,
            name=agent.name,
            description=agent.description,
            icon=agent.icon,
            category=agent.category,
            mode=agent.mode,
            is_default=is_default,
        )
        for agent, is_default in rows
    ]


@router.post(
    "/{project_id}/agents",
    response_model=ProjectAgentOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_workspace_project_agent(
    project_id: UUID,
    payload: ProjectAgentIn,
    context: JwtContext,
    session: SessionDep,
) -> ProjectAgentOut:
    project = await _load_project(project_id, context, session)
    if not can_manage(project, context.user.id, context.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the project owner can edit")
    try:
        agent = await add_project_agent(
            session,
            project,
            agent_id=payload.agent_id,
            user_id=context.user.id,
            workspace_role=context.role,
            set_default=payload.set_default,
        )
    except ProjectResourceError as exc:
        raise _resource_error(exc) from None
    await session.commit()
    return ProjectAgentOut(
        agent_id=agent.id,
        name=agent.name,
        description=agent.description,
        icon=agent.icon,
        category=agent.category,
        mode=agent.mode,
        is_default=project.default_custom_agent_id == agent.id,
    )


@router.delete(
    "/{project_id}/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_workspace_project_agent(
    project_id: UUID, agent_id: UUID, context: JwtContext, session: SessionDep
) -> Response:
    project = await _load_project(project_id, context, session)
    if not can_manage(project, context.user.id, context.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the project owner can edit")
    try:
        await remove_project_agent(session, project, agent_id)
    except ProjectResourceError as exc:
        raise _resource_error(exc) from None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/files", response_model=list[ProjectFileOut])
async def list_workspace_project_files(
    project_id: UUID, context: JwtContext, session: SessionDep
) -> list[ProjectFileOut]:
    project = await _load_project(project_id, context, session)
    documents = await list_project_documents(session, project)
    return [
        ProjectFileOut(
            document_id=document.id,
            filename=document.filename,
            status=document.status,
            size_bytes=document.size_bytes,
            mime=document.mime,
            tags=list(document.tags or []),
            folder=document.folder,
            created_at=document.created_at,
        )
        for document in documents
    ]


@router.post(
    "/{project_id}/files",
    response_model=ProjectFileOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_workspace_project_file(
    project_id: UUID,
    payload: ProjectFileIn,
    context: JwtContext,
    session: SessionDep,
) -> ProjectFileOut:
    project = await _load_project(project_id, context, session)
    if not can_manage(project, context.user.id, context.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the project owner can edit")
    try:
        document = await add_project_document(
            session,
            project,
            document_id=payload.document_id,
            user_id=context.user.id,
        )
    except ProjectResourceError as exc:
        raise _resource_error(exc) from None
    await session.commit()
    return ProjectFileOut(
        document_id=document.id,
        filename=document.filename,
        status=document.status,
        size_bytes=document.size_bytes,
        mime=document.mime,
        tags=list(document.tags or []),
        folder=document.folder,
        created_at=document.created_at,
    )


@router.delete(
    "/{project_id}/files/{document_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_workspace_project_file(
    project_id: UUID,
    document_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> Response:
    project = await _load_project(project_id, context, session)
    if not can_manage(project, context.user.id, context.role):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the project owner can edit")
    try:
        await remove_project_document(session, project, document_id)
    except ProjectResourceError as exc:
        raise _resource_error(exc) from None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)