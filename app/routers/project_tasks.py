from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import ProjectTask
from app.schemas import ProjectTaskCreate, ProjectTaskOut, ProjectTaskUpdate
from app.services.reuse import (
    ReuseError,
    create_tasks,
    delete_task,
    list_tasks,
    update_task,
)

router = APIRouter(prefix="/project-tasks", tags=["reuse"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


def _error(exc: ReuseError) -> HTTPException:
    if exc.code in {"project_not_found", "task_not_found"}:
        return HTTPException(status.HTTP_404_NOT_FOUND, {"code": exc.code, "message": exc.message})
    if exc.code == "forbidden":
        return HTTPException(status.HTTP_403_FORBIDDEN, {"code": exc.code, "message": exc.message})
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {"code": exc.code, "message": exc.message},
    )


@router.get("", response_model=list[ProjectTaskOut])
async def list_project_tasks(
    context: JwtContext,
    session: SessionDep,
    project_id: UUID | None = None,
) -> list[ProjectTaskOut]:
    rows = await list_tasks(session, context.workspace.id, project_id)
    return [ProjectTaskOut.model_validate(row) for row in rows]


@router.post("", response_model=list[ProjectTaskOut], status_code=status.HTTP_201_CREATED)
async def create_project_tasks(
    payload: ProjectTaskCreate,
    context: JwtContext,
    session: SessionDep,
) -> list[ProjectTaskOut]:
    try:
        rows = await create_tasks(
            session,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            project_id=payload.project_id,
            tasks=payload.tasks,
            conversation_id=payload.conversation_id,
            message_id=payload.message_id,
        )
    except ReuseError as exc:
        raise _error(exc) from None
    await session.commit()
    for row in rows:
        await session.refresh(row)
    return [ProjectTaskOut.model_validate(row) for row in rows]


@router.patch("/{task_id}", response_model=ProjectTaskOut)
async def patch_project_task(
    task_id: UUID,
    payload: ProjectTaskUpdate,
    context: JwtContext,
    session: SessionDep,
) -> ProjectTaskOut:
    task = await session.get(ProjectTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    try:
        task = await update_task(
            session,
            task,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            role=context.role,
            title=payload.title,
            status=payload.status,
            priority=payload.priority,
        )
    except ReuseError as exc:
        raise _error(exc) from None
    await session.commit()
    await session.refresh(task)
    return ProjectTaskOut.model_validate(task)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project_task(
    task_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> Response:
    task = await session.get(ProjectTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    try:
        await delete_task(
            session,
            task,
            context.workspace.id,
            context.user.id,
            context.role,
        )
    except ReuseError as exc:
        raise _error(exc) from None
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
