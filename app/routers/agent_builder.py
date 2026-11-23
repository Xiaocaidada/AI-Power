from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, get_scoped_registry
from app.providers.registry import ProviderRegistry
from app.schemas import AgentBuilderIn, AgentBuilderOut
from app.services.agent_builder import AgentBuilderError, generate_agent_workflow

router = APIRouter(prefix="/agent-builder", tags=["agent-builder"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
RegistryDep = Annotated[ProviderRegistry, Depends(get_scoped_registry)]


@router.post("/generate", response_model=AgentBuilderOut)
async def generate_workflow(
    payload: AgentBuilderIn,
    context: JwtContext,
    session: SessionDep,
    registry: RegistryDep,
) -> AgentBuilderOut:
    try:
        result = await generate_agent_workflow(
            session,
            registry,
            workspace_id=context.workspace.id,
            user_id=context.user.id,
            prompt=payload.prompt,
            provider_id=payload.provider_id,
            model=payload.model,
            current_definition=payload.current_definition,
            raw_agent_id=str(payload.agent_id) if payload.agent_id else None,
        )
    except AgentBuilderError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"code": exc.code, "message": exc.message},
        ) from None
    return AgentBuilderOut(
        definition=result.definition,
        summary=result.summary,
        missing_resources=result.missing_resources,
        provider_id=payload.provider_id,
        model=payload.model,
    )