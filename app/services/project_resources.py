"""Project-scoped Agent and document associations."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CustomAgent, Document, Project, ProjectAgent, ProjectDocument


class ProjectResourceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _agent_accessible(agent: CustomAgent, user_id: UUID, workspace_role: str) -> bool:
    return (
        agent.owner_user_id == user_id
        or agent.visibility == "shared"
        or workspace_role == "owner"
    )


async def list_project_agents(
    session: AsyncSession, project: Project
) -> list[tuple[CustomAgent, bool]]:
    linked = {
        agent_id
        for agent_id in (
            await session.execute(
                select(ProjectAgent.agent_id).where(
                    ProjectAgent.project_id == project.id
                )
            )
        ).scalars()
    }
    if project.default_custom_agent_id is not None:
        linked.add(project.default_custom_agent_id)
    if not linked:
        return []
    rows = list(
        (
            await session.execute(
                select(CustomAgent).where(
                    CustomAgent.id.in_(linked),
                    CustomAgent.workspace_id == project.workspace_id,
                    CustomAgent.archived_at.is_(None),
                )
            )
        ).scalars()
    )
    return [
        (agent, agent.id == project.default_custom_agent_id)
        for agent in sorted(rows, key=lambda item: item.name.casefold())
    ]


async def add_project_agent(
    session: AsyncSession,
    project: Project,
    *,
    agent_id: UUID,
    user_id: UUID,
    workspace_role: str,
    set_default: bool = False,
) -> CustomAgent:
    agent = await session.get(CustomAgent, agent_id)
    if (
        agent is None
        or agent.workspace_id != project.workspace_id
        or agent.archived_at is not None
    ):
        raise ProjectResourceError("agent_not_found", "Agent not found")
    if not _agent_accessible(agent, user_id, workspace_role):
        raise ProjectResourceError("agent_not_found", "Agent not found")
    existing = (
        await session.execute(
            select(ProjectAgent).where(
                ProjectAgent.project_id == project.id,
                ProjectAgent.agent_id == agent.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            ProjectAgent(
                project_id=project.id,
                agent_id=agent.id,
                added_by_user_id=user_id,
            )
        )
    if set_default:
        project.default_custom_agent_id = agent.id
    await session.flush()
    return agent


async def remove_project_agent(
    session: AsyncSession, project: Project, agent_id: UUID
) -> None:
    row = (
        await session.execute(
            select(ProjectAgent).where(
                ProjectAgent.project_id == project.id,
                ProjectAgent.agent_id == agent_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ProjectResourceError("agent_not_found", "Agent not linked to project")
    await session.delete(row)
    if project.default_custom_agent_id == agent_id:
        project.default_custom_agent_id = None
    await session.flush()


async def list_project_documents(
    session: AsyncSession, project: Project
) -> list[Document]:
    return list(
        (
            await session.execute(
                select(Document)
                .join(ProjectDocument, ProjectDocument.document_id == Document.id)
                .where(
                    ProjectDocument.project_id == project.id,
                    Document.workspace_id == project.workspace_id,
                    Document.deleted_at.is_(None),
                )
                .order_by(Document.created_at.desc(), Document.id.desc())
            )
        ).scalars()
    )


async def add_project_document(
    session: AsyncSession,
    project: Project,
    *,
    document_id: UUID,
    user_id: UUID,
) -> Document:
    document = await session.get(Document, document_id)
    if (
        document is None
        or document.workspace_id != project.workspace_id
        or document.deleted_at is not None
    ):
        raise ProjectResourceError("document_not_found", "Document not found")
    existing = (
        await session.execute(
            select(ProjectDocument).where(
                ProjectDocument.project_id == project.id,
                ProjectDocument.document_id == document.id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        session.add(
            ProjectDocument(
                project_id=project.id,
                document_id=document.id,
                added_by_user_id=user_id,
            )
        )
        await session.flush()
    return document


async def remove_project_document(
    session: AsyncSession, project: Project, document_id: UUID
) -> None:
    row = (
        await session.execute(
            select(ProjectDocument).where(
                ProjectDocument.project_id == project.id,
                ProjectDocument.document_id == document_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise ProjectResourceError(
            "document_not_found", "Document not linked to project"
        )
    await session.delete(row)
    await session.flush()


async def project_agent_ids(session: AsyncSession, project_id: UUID) -> set[UUID]:
    return set(
        (
            await session.execute(
                select(ProjectAgent.agent_id).where(
                    ProjectAgent.project_id == project_id
                )
            )
        ).scalars()
    )