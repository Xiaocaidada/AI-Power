from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Workspace, WorkspaceMember


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found")


async def create_personal_workspace(session: AsyncSession, user: User) -> Workspace:
    workspace = Workspace(
        name=f"{user.email} 的空间"[:120],
        plan="free",
        is_personal=True,
    )
    session.add(workspace)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    await session.commit()
    await session.refresh(workspace)
    return workspace


async def ensure_personal_workspace(session: AsyncSession, user: User) -> Workspace:
    result = await session.execute(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.role == "owner",
            Workspace.is_personal.is_(True),
        )
    )
    workspace = result.scalar_one_or_none()
    if workspace is None:
        workspace = await create_personal_workspace(session, user)
    return workspace


async def resolve_workspace(
    session: AsyncSession, user: User, workspace_id: UUID | None
) -> tuple[Workspace, str]:
    if workspace_id is None:
        workspace = await ensure_personal_workspace(session, user)
        return workspace, "owner"

    row = (
        await session.execute(
            select(Workspace, WorkspaceMember.role)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(Workspace.id == workspace_id, WorkspaceMember.user_id == user.id)
        )
    ).one_or_none()
    if row is None:
        raise _not_found()
    return row[0], row[1]


async def create_workspace(session: AsyncSession, user: User, name: str) -> tuple[Workspace, str]:
    workspace = Workspace(name=name, plan="free", is_personal=False)
    session.add(workspace)
    await session.flush()
    session.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    await session.commit()
    await session.refresh(workspace)
    return workspace, "owner"


async def list_workspaces(session: AsyncSession, user: User) -> list[tuple[Workspace, str]]:
    rows = (
        await session.execute(
            select(Workspace, WorkspaceMember.role)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(WorkspaceMember.user_id == user.id)
            .order_by(Workspace.is_personal.desc(), Workspace.created_at)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def require_owner(session: AsyncSession, workspace_id: UUID, user: User) -> Workspace:
    row = (
        await session.execute(
            select(Workspace)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .where(
                Workspace.id == workspace_id,
                WorkspaceMember.user_id == user.id,
                WorkspaceMember.role == "owner",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise _not_found()
    return row


async def list_members(
    session: AsyncSession, workspace_id: UUID
) -> list[tuple[WorkspaceMember, User]]:
    rows = (
        await session.execute(
            select(WorkspaceMember, User)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.created_at)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


async def add_member_by_email(
    session: AsyncSession, workspace: Workspace, email: str
) -> tuple[WorkspaceMember, User]:
    user = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    existing = await session.get(
        WorkspaceMember, {"workspace_id": workspace.id, "user_id": user.id}
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "User is already a member")
    member = WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="member")
    session.add(member)
    await session.commit()
    return member, user


async def remove_member(session: AsyncSession, workspace_id: UUID, user_id: UUID) -> None:
    member = await session.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id})
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    if member.role == "owner":
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot remove the workspace owner")
    await session.delete(member)
    await session.commit()
