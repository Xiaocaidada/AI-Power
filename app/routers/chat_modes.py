from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, require_scope
from app.schemas import ChatCapabilitiesOut, ChatModeOptionOut, ChatModesOut
from app.services.chat_modes import (
    THINKING_LEVELS,
    mode_catalog,
    reasoning_levels_for,
    resolve_model_capabilities,
)

router = APIRouter(prefix="/chat", tags=["chat"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
ChatContext = Annotated[AuthContext, Depends(require_scope("chat:write"))]


@router.get("/modes", response_model=ChatModesOut)
async def get_chat_modes(_context: ChatContext) -> ChatModesOut:
    return ChatModesOut(
        modes=[ChatModeOptionOut(**item) for item in mode_catalog()],
        thinking_levels=list(THINKING_LEVELS),
    )


@router.get("/capabilities", response_model=ChatCapabilitiesOut)
async def get_chat_capabilities(
    context: ChatContext,
    session: SessionDep,
    provider_id: Annotated[str, Query(min_length=1, max_length=50)],
    model: Annotated[str, Query(min_length=1, max_length=200)],
) -> ChatCapabilitiesOut:
    resolved = await resolve_model_capabilities(
        session,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        provider_id=provider_id,
        model_id=model,
    )
    supported = set(resolved.reasoning_levels or reasoning_levels_for(resolved.capabilities, None))
    return ChatCapabilitiesOut(
        provider_id=provider_id,
        model_id=model,
        capabilities=resolved.capabilities or [],
        thinking_levels=[
            {"id": level, "supported": level in supported} for level in THINKING_LEVELS
        ],
    )
