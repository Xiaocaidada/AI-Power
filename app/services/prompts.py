import re
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PromptTemplate, PromptVersion

VARIABLE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class MissingPromptVariables(Exception):
    def __init__(self, missing: list[str]) -> None:
        super().__init__("Missing prompt variables: " + ", ".join(missing))
        self.missing = missing


def extract_variables(system_prompt: str) -> list[str]:
    variables: list[str] = []
    for match in VARIABLE_PATTERN.finditer(system_prompt):
        name = match.group(1)
        if name not in variables:
            variables.append(name)
    return variables


def render_prompt(system_prompt: str, variables: dict[str, str]) -> tuple[str, list[str]]:
    declared = extract_variables(system_prompt)
    missing = [name for name in declared if name not in variables]
    if missing:
        raise MissingPromptVariables(missing)

    def replace(match: re.Match[str]) -> str:
        return str(variables[match.group(1)])

    return VARIABLE_PATTERN.sub(replace, system_prompt), declared


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Prompt template not found")


def _version_not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Prompt version not found")


def _missing_variables(exc: MissingPromptVariables) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        {
            "code": "missing_variables",
            "message": "Missing prompt variables",
            "missing": exc.missing,
        },
    )


async def get_owned_template(
    template_id: UUID, workspace_id: UUID, session: AsyncSession
) -> PromptTemplate:
    template = (
        await session.execute(
            select(PromptTemplate).where(
                PromptTemplate.id == template_id,
                PromptTemplate.workspace_id == workspace_id,
                PromptTemplate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise _not_found()
    return template


async def list_versions(session: AsyncSession, template_id: UUID) -> list[PromptVersion]:
    result = await session.execute(
        select(PromptVersion)
        .where(PromptVersion.template_id == template_id)
        .order_by(PromptVersion.version.desc())
    )
    return list(result.scalars())


async def list_templates(session: AsyncSession, workspace_id: UUID) -> list[PromptTemplate]:
    result = await session.execute(
        select(PromptTemplate)
        .where(
            PromptTemplate.workspace_id == workspace_id,
            PromptTemplate.deleted_at.is_(None),
        )
        .order_by(PromptTemplate.created_at.desc(), PromptTemplate.id.desc())
    )
    return list(result.scalars())


async def create_template(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    name: str,
    description: str,
    system_prompt: str,
) -> tuple[PromptTemplate, PromptVersion]:
    template = PromptTemplate(
        workspace_id=workspace_id,
        name=name,
        description=description,
        created_by=user_id,
    )
    session.add(template)
    await session.flush()
    version = PromptVersion(
        template_id=template.id,
        version=1,
        system_prompt=system_prompt,
        variables=extract_variables(system_prompt),
    )
    session.add(version)
    await session.commit()
    await session.refresh(template)
    await session.refresh(version)
    return template, version


async def create_version(
    session: AsyncSession, template: PromptTemplate, system_prompt: str
) -> PromptVersion:
    latest = (
        await session.execute(
            select(func.max(PromptVersion.version)).where(PromptVersion.template_id == template.id)
        )
    ).scalar_one()
    version = PromptVersion(
        template_id=template.id,
        version=(latest or 0) + 1,
        system_prompt=system_prompt,
        variables=extract_variables(system_prompt),
    )
    session.add(version)
    await session.commit()
    await session.refresh(version)
    return version


async def pick_version(
    session: AsyncSession, template_id: UUID, version: int | None
) -> PromptVersion:
    if version is None:
        row = (
            await session.execute(
                select(PromptVersion)
                .where(PromptVersion.template_id == template_id)
                .order_by(PromptVersion.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    else:
        row = (
            await session.execute(
                select(PromptVersion).where(
                    PromptVersion.template_id == template_id,
                    PromptVersion.version == version,
                )
            )
        ).scalar_one_or_none()
    if row is None:
        raise _version_not_found()
    return row


async def resolve_conversation_prompt(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    version_id: UUID,
    variables: dict[str, str],
) -> tuple[PromptVersion, str]:
    row = (
        await session.execute(
            select(PromptVersion)
            .join(PromptTemplate, PromptTemplate.id == PromptVersion.template_id)
            .where(
                PromptVersion.id == version_id,
                PromptTemplate.workspace_id == workspace_id,
                PromptTemplate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise _version_not_found()
    try:
        rendered, _ = render_prompt(row.system_prompt, variables)
    except MissingPromptVariables as exc:
        raise _missing_variables(exc) from None
    return row, rendered


async def soft_delete_template(session: AsyncSession, template: PromptTemplate) -> None:
    template.deleted_at = datetime.now(UTC)
    await session.commit()
