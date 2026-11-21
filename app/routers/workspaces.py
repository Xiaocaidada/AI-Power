from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import Workspace
from app.schemas import MemberCreate, MemberOut, WorkspaceCreate, WorkspaceOut
from app.services.workspaces import (
    add_member_by_email,
    create_workspace,
    list_members,
    list_workspaces,
    remove_member,
    require_owner,
    resolve_workspace,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


def _workspace_out(workspace: Workspace, role: str) -> WorkspaceOut:
    return WorkspaceOut(
        id=workspace.id,
        name=workspace.name,
        plan=workspace.plan,
        is_personal=workspace.is_personal,
        role=role,
        created_at=workspace.created_at,
    )


@router.get("", response_model=list[WorkspaceOut])
async def list_my_workspaces(context: JwtContext, session: SessionDep) -> list[WorkspaceOut]:
    rows = await list_workspaces(session, context.user)
    return [_workspace_out(workspace, role) for workspace, role in rows]


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
async def create_new_workspace(
    payload: WorkspaceCreate, context: JwtContext, session: SessionDep
) -> WorkspaceOut:
    workspace, role = await create_workspace(session, context.user, payload.name)
    return _workspace_out(workspace, role)


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
async def get_members(
    workspace_id: UUID, context: JwtContext, session: SessionDep
) -> list[MemberOut]:
    await resolve_workspace(session, context.user, workspace_id)
    rows = await list_members(session, workspace_id)
    return [
        MemberOut(
            user_id=user.id,
            email=user.email,
            role=member.role,
            created_at=member.created_at,
        )
        for member, user in rows
    ]


@router.post(
    "/{workspace_id}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    workspace_id: UUID,
    payload: MemberCreate,
    context: JwtContext,
    session: SessionDep,
) -> MemberOut:
    workspace = await require_owner(session, workspace_id, context.user)
    member, user = await add_member_by_email(session, workspace, str(payload.email))
    return MemberOut(
        user_id=user.id,
        email=user.email,
        role=member.role,
        created_at=member.created_at,
    )


@router.delete("/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_workspace_member(
    workspace_id: UUID,
    user_id: UUID,
    context: JwtContext,
    session: SessionDep,
) -> Response:
    await require_owner(session, workspace_id, context.user)
    await remove_member(session, workspace_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
