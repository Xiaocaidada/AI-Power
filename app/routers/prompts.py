from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context
from app.models import PromptTemplate, PromptVersion
from app.schemas import (
    PromptFavoriteOut,
    PromptRenderIn,
    PromptRenderOut,
    PromptTemplateCreate,
    PromptTemplateOut,
    PromptTemplateUpdate,
    PromptVersionCreate,
    PromptVersionOut,
)
from app.services.prompts import (
    MissingPromptVariables,
    create_template,
    create_version,
    favorite_ids,
    get_owned_template,
    list_templates,
    list_versions,
    pick_version,
    render_prompt,
    set_favorite,
    soft_delete_template,
    update_template,
)

router = APIRouter(prefix="/prompt-templates", tags=["prompt-templates"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]


def _template_out(
    template: PromptTemplate,
    versions: list[PromptVersion],
    favorite: bool = False,
) -> PromptTemplateOut:
    return PromptTemplateOut(
        id=template.id,
        name=template.name,
        description=template.description,
        category=template.category,
        favorite=favorite,
        created_at=template.created_at,
        versions=[PromptVersionOut.model_validate(version) for version in versions],
    )


@router.get("", response_model=list[PromptTemplateOut])
async def list_prompt_templates(
    context: JwtContext,
    session: SessionDep,
    q: str | None = None,
    category: str | None = None,
    favorite: bool = False,
) -> list[PromptTemplateOut]:
    templates = await list_templates(
        session,
        context.workspace.id,
        q=q,
        category=category,
        favorite_user_id=context.user.id,
        favorite_only=favorite,
    )
    favorites = await favorite_ids(
        session, context.user.id, [template.id for template in templates]
    )
    result: list[PromptTemplateOut] = []
    for template in templates:
        versions = await list_versions(session, template.id)
        result.append(_template_out(template, versions, template.id in favorites))
    return result


@router.post("", response_model=PromptTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_prompt_template(
    payload: PromptTemplateCreate, context: JwtContext, session: SessionDep
) -> PromptTemplateOut:
    template, version = await create_template(
        session,
        workspace_id=context.workspace.id,
        user_id=context.user.id,
        name=payload.name,
        description=payload.description,
        system_prompt=payload.system_prompt,
        category=payload.category,
    )
    return _template_out(template, [version])


@router.get("/{template_id}", response_model=PromptTemplateOut)
async def get_prompt_template(
    template_id: UUID, context: JwtContext, session: SessionDep
) -> PromptTemplateOut:
    template = await get_owned_template(template_id, context.workspace.id, session)
    favorites = await favorite_ids(session, context.user.id, [template.id])
    return _template_out(
        template, await list_versions(session, template.id), template.id in favorites
    )


@router.patch("/{template_id}", response_model=PromptTemplateOut)
async def update_prompt_template(
    template_id: UUID,
    payload: PromptTemplateUpdate,
    context: JwtContext,
    session: SessionDep,
) -> PromptTemplateOut:
    template = await get_owned_template(template_id, context.workspace.id, session)
    template = await update_template(
        session, template, payload.model_dump(exclude_unset=True)
    )
    favorites = await favorite_ids(session, context.user.id, [template.id])
    return _template_out(
        template, await list_versions(session, template.id), template.id in favorites
    )


@router.post("/{template_id}/favorite", response_model=PromptFavoriteOut)
async def favorite_prompt_template(
    template_id: UUID, context: JwtContext, session: SessionDep
) -> PromptFavoriteOut:
    template = await get_owned_template(template_id, context.workspace.id, session)
    favorite = await set_favorite(session, template.id, context.user.id, True)
    await session.commit()
    return PromptFavoriteOut(favorite=favorite)


@router.delete("/{template_id}/favorite", response_model=PromptFavoriteOut)
async def unfavorite_prompt_template(
    template_id: UUID, context: JwtContext, session: SessionDep
) -> PromptFavoriteOut:
    template = await get_owned_template(template_id, context.workspace.id, session)
    favorite = await set_favorite(session, template.id, context.user.id, False)
    await session.commit()
    return PromptFavoriteOut(favorite=favorite)


@router.post(
    "/{template_id}/versions",
    response_model=PromptVersionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_prompt_version(
    template_id: UUID,
    payload: PromptVersionCreate,
    context: JwtContext,
    session: SessionDep,
) -> PromptVersionOut:
    template = await get_owned_template(template_id, context.workspace.id, session)
    version = await create_version(session, template, payload.system_prompt)
    return PromptVersionOut.model_validate(version)


@router.post("/{template_id}/render", response_model=PromptRenderOut)
async def render_prompt_template(
    template_id: UUID,
    payload: PromptRenderIn,
    context: JwtContext,
    session: SessionDep,
) -> PromptRenderOut:
    template = await get_owned_template(template_id, context.workspace.id, session)
    version = await pick_version(session, template.id, payload.version)
    try:
        rendered, variables = render_prompt(version.system_prompt, payload.variables)
    except MissingPromptVariables as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "missing_variables",
                "message": "Missing prompt variables",
                "missing": exc.missing,
            },
        ) from None
    return PromptRenderOut(rendered=rendered, version=version.version, variables=variables)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt_template(
    template_id: UUID, context: JwtContext, session: SessionDep
) -> Response:
    template = await get_owned_template(template_id, context.workspace.id, session)
    await soft_delete_template(session, template)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
