from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Project


class ProjectError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def can_manage(project: Project, user_id: UUID, workspace_role: str) -> bool:
    return project.owner_user_id == user_id or workspace_role == "owner"


async def list_projects(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    include_archived: bool = False,
) -> list[tuple[Project, int]]:
    conditions = [Project.workspace_id == workspace_id]
    if not include_archived:
        conditions.append(Project.archived_at.is_(None))
    statement = (
        select(Project, func.count(Conversation.id))
        .outerjoin(
            Conversation,
            and_(
                Conversation.project_id == Project.id,
                Conversation.archived_at.is_(None),
            ),
        )
        .where(*conditions)
        .group_by(Project.id)
        .order_by(Project.archived_at.is_not(None), Project.updated_at.desc())
    )
    return [(row[0], int(row[1])) for row in (await session.execute(statement)).all()]


async def get_project(
    session: AsyncSession,
    workspace_id: UUID,
    project_id: UUID,
    *,
    include_archived: bool = False,
) -> Project:
    conditions = [Project.id == project_id, Project.workspace_id == workspace_id]
    if not include_archived:
        conditions.append(Project.archived_at.is_(None))
    project = (
        await session.execute(select(Project).where(*conditions))
    ).scalar_one_or_none()
    if project is None:
        raise ProjectError("not_found", "Project not found")
    return project


async def project_conversation_count(session: AsyncSession, project_id: UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Conversation)
                .where(
                    Conversation.project_id == project_id,
                    Conversation.archived_at.is_(None),
                )
            )
        ).scalar_one()
    )


async def create_project(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    owner_user_id: UUID,
    values: dict[str, Any],
) -> Project:
    project = Project(workspace_id=workspace_id, owner_user_id=owner_user_id, **values)
    session.add(project)
    await session.flush()
    return project


async def update_project(
    session: AsyncSession, project: Project, values: dict[str, Any]
) -> Project:
    archived = values.pop("archived", None)
    for key, value in values.items():
        setattr(project, key, value)
    if archived is not None:
        project.archived_at = datetime.now(UTC) if archived else None
    await session.flush()
    return project


async def archive_project(session: AsyncSession, project: Project) -> None:
    project.archived_at = datetime.now(UTC)
    await session.flush()