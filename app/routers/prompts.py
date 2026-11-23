from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import AuthContext, get_jwt_context, require_admin
from app.models import AuditLog, PromptTemplate, PromptVersion
from app.schemas import (
    PromptDiffOut,
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
    diff_prompt_lines,
    favorite_ids,
    get_accessible_template,
    get_owned_template,
    get_platform_template,
    list_platform_templates,
    list_templates,
    list_versions,
    pick_version,
    render_prompt_both,
    set_favorite,
    soft_delete_template,
    update_template,
)

router = APIRouter(prefix="/prompt-templates", tags=["prompt-templates"])
admin_router = APIRouter(prefix="/admin/prompt-templates", tags=["admin"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
JwtContext = Annotated[AuthContext, Depends(get_jwt_context)]
AdminContext = Annotated[AuthContext, Depends(require_admin)]


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
        scope=template.scope,
        favorite=favorite,
        created_at=template.created_at,
        versions=[PromptVersionOut.model_validate(version) for version in versions],
    )


def _audit(
    session: AsyncSession,
    context: AuthContext,
    action: str,
    template_id: UUID,
    detail: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_user_id=context.user.id,
            action=action,
            target_type="prompt_template",
            target_id=str(template_id),
            detail=detail,
        )
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
        user_prompt=payload.user_prompt,
        variable_definitions=[
            item.model_dump() for item in payload.variable_definitions
        ],
        parameters=payload.parameters.model_dump(exclude_none=True),
    )
    return _template_out(template, [version])


@router.get("/{template_id}", response_model=PromptTemplateOut)
async def get_prompt_template(
    template_id: UUID, context: JwtContext, session: SessionDep
) -> PromptTemplateOut:
    template = await get_accessible_template(template_id, context.workspace.id, session)
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
    template = await get_accessible_template(template_id, context.workspace.id, session)
    favorite = await set_favorite(session, template.id, context.user.id, True)
    await session.commit()
    return PromptFavoriteOut(favorite=favorite)


@router.delete("/{template_id}/favorite", response_model=PromptFavoriteOut)
async def unfavorite_prompt_template(
    template_id: UUID, context: JwtContext, session: SessionDep
) -> PromptFavoriteOut:
    template = await get_accessible_template(template_id, context.workspace.id, session)
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
    version = await create_version(
        session,
        template,
        payload.system_prompt,
        user_prompt=payload.user_prompt,
        variable_definitions=[
            item.model_dump() for item in payload.variable_definitions
        ],
        parameters=payload.parameters.model_dump(exclude_none=True),
    )
    return PromptVersionOut.model_validate(version)


@router.post("/{template_id}/render", response_model=PromptRenderOut)
async def render_prompt_template(
    template_id: UUID,
    payload: PromptRenderIn,
    context: JwtContext,
    session: SessionDep,
) -> PromptRenderOut:
    template = await get_accessible_template(template_id, context.workspace.id, session)
    version = await pick_version(session, template.id, payload.version)
    try:
        system_prompt, user_prompt, variables = render_prompt_both(
            version.system_prompt,
            version.user_prompt,
            payload.variables,
            version.variable_definitions,
        )
    except MissingPromptVariables as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            {
                "code": "missing_variables",
                "message": "Missing prompt variables",
                "missing": exc.missing,
            },
        ) from None
    return PromptRenderOut(
        rendered=user_prompt or system_prompt,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        version=version.version,
        variables=variables,
    )


@router.get("/{template_id}/diff", response_model=PromptDiffOut)
async def diff_prompt_template(
    template_id: UUID,
    context: JwtContext,
    session: SessionDep,
    from_version: Annotated[int, Query(ge=1)] = 1,
    to_version: Annotated[int | None, Query(ge=1)] = None,
) -> PromptDiffOut:
    template = await get_accessible_template(template_id, context.workspace.id, session)
    old = await pick_version(session, template.id, from_version)
    new = await pick_version(session, template.id, to_version)
    return PromptDiffOut(
        from_version=old.version,
        to_version=new.version,
        system=diff_prompt_lines(old.system_prompt, new.system_prompt),
        user=diff_prompt_lines(old.user_prompt, new.user_prompt),
    )


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt_template(
    template_id: UUID, context: JwtContext, session: SessionDep
) -> Response:
    template = await get_owned_template(template_id, context.workspace.id, session)
    await soft_delete_template(session, template)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@admin_router.get("", response_model=list[PromptTemplateOut])
async def list_admin_prompt_templates(
    context: AdminContext, session: SessionDep
) -> list[PromptTemplateOut]:
    templates = await list_platform_templates(session)
    return [
        _template_out(template, await list_versions(session, template.id))
        for template in templates
    ]


@admin_router.get("/{template_id}", response_model=PromptTemplateOut)
async def get_admin_prompt_template(
    template_id: UUID, context: AdminContext, session: SessionDep
) -> PromptTemplateOut:
    template = await get_platform_template(session, template_id)
    return _template_out(template, await list_versions(session, template.id))


@admin_router.post(
    "", response_model=PromptTemplateOut, status_code=status.HTTP_201_CREATED
)
async def create_admin_prompt_template(
    payload: PromptTemplateCreate, context: AdminContext, session: SessionDep
) -> PromptTemplateOut:
    template, version = await create_template(
        session,
        workspace_id=None,
        user_id=context.user.id,
        scope="platform",
        name=payload.name,
        description=payload.description,
        system_prompt=payload.system_prompt,
        category=payload.category,
        user_prompt=payload.user_prompt,
        variable_definitions=[
            item.model_dump() for item in payload.variable_definitions
        ],
        parameters=payload.parameters.model_dump(exclude_none=True),
    )
    _audit(session, context, "prompt.platform_create", template.id)
    await session.commit()
    return _template_out(template, [version])


@admin_router.patch("/{template_id}", response_model=PromptTemplateOut)
async def update_admin_prompt_template(
    template_id: UUID,
    payload: PromptTemplateUpdate,
    context: AdminContext,
    session: SessionDep,
) -> PromptTemplateOut:
    template = await get_platform_template(session, template_id)
    template = await update_template(
        session, template, payload.model_dump(exclude_unset=True)
    )
    _audit(session, context, "prompt.platform_update", template.id)
    await session.commit()
    return _template_out(template, await list_versions(session, template.id))


@admin_router.post(
    "/{template_id}/versions",
    response_model=PromptVersionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_prompt_version(
    template_id: UUID,
    payload: PromptVersionCreate,
    context: AdminContext,
    session: SessionDep,
) -> PromptVersionOut:
    template = await get_platform_template(session, template_id)
    version = await create_version(
        session,
        template,
        payload.system_prompt,
        user_prompt=payload.user_prompt,
        variable_definitions=[
            item.model_dump() for item in payload.variable_definitions
        ],
        parameters=payload.parameters.model_dump(exclude_none=True),
    )
    _audit(session, context, "prompt.platform_version", template.id)
    await session.commit()
    return PromptVersionOut.model_validate(version)


@admin_router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_admin_prompt_template(
    template_id: UUID, context: AdminContext, session: SessionDep
) -> Response:
    template = await get_platform_template(session, template_id)
    _audit(session, context, "prompt.platform_delete", template.id)
    await soft_delete_template(session, template)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
