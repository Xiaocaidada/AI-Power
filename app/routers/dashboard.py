from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.schemas import (
    ConversationOut,
    DashboardCountsOut,
    DashboardOut,
    DashboardRecentProjectOut,
)
from app.services.dashboard import dashboard_summary

router = APIRouter(tags=["dashboard"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


@router.get("/dashboard", response_model=DashboardOut)
async def get_dashboard(context: JwtContext, session: SessionDep) -> DashboardOut:
    summary = await dashboard_summary(
        session, context.workspace.id, context.user.id
    )
    return DashboardOut(
        counts=DashboardCountsOut(**summary["counts"]),
        recent_conversations=[
            ConversationOut.model_validate(conversation)
            for conversation in summary["recent_conversations"]
        ],
        recent_projects=[
            DashboardRecentProjectOut(
                id=project.id, name=project.name, updated_at=project.updated_at
            )
            for project in summary["recent_projects"]
        ],
    )