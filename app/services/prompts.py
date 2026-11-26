import difflib
import re
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PromptFavorite, PromptTemplate, PromptVersion

VARIABLE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


class MissingPromptVariables(Exception):
    def __init__(self, missing: list[str]) -> None:
        super().__init__("Missing prompt variables: " + ", ".join(missing))
        self.missing = missing


def extract_variables(*prompts: str) -> list[str]:
    variables: list[str] = []
    for prompt in prompts:
        for match in VARIABLE_PATTERN.finditer(prompt):
            name = match.group(1)
            if name not in variables:
                variables.append(name)
    return variables


def _render_one(text: str, variables: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        return str(variables[match.group(1)])

    return VARIABLE_PATTERN.sub(replace, text)


def apply_user_template(template: str, content: str) -> str:
    """Wrap a typed chat message with a template's user prompt.

    ``{{input}}`` receives the typed content; other declared variables render
    empty. A single non-``input`` variable also receives the content. Templates
    without variables are prepended to the content so the text is not lost.
    """
    if template.strip() == "":
        return content
    declared = extract_variables(template)
    if not declared:
        return f"{template.rstrip()}\n\n{content}"
    if "input" in declared:
        filled = {name: (content if name == "input" else "") for name in declared}
        return _render_one(template, filled)
    if len(declared) == 1:
        return _render_one(template, {declared[0]: content})
    rendered = _render_one(template, dict.fromkeys(declared, "")).rstrip()
    return f"{rendered}\n\n{content}"


def render_prompt(system_prompt: str, variables: dict[str, str]) -> tuple[str, list[str]]:
    declared = extract_variables(system_prompt)
    missing = [name for name in declared if name not in variables]
    if missing:
        raise MissingPromptVariables(missing)
    return _render_one(system_prompt, variables), declared


def render_prompt_both(
    system_prompt: str,
    user_prompt: str,
    variables: dict[str, str],
    definitions: list[dict] | None = None,
) -> tuple[str, str, list[str]]:
    declared = extract_variables(system_prompt, user_prompt)
    filled = dict(variables)
    for item in definitions or []:
        name = str(item.get("name", ""))
        if name and name not in filled and item.get("default"):
            filled[name] = str(item["default"])
    required = {
        str(item.get("name"))
        for item in definitions or []
        if item.get("required", True)
    }
    missing = [
        name
        for name in declared
        if name not in filled and (not definitions or name in required)
    ]
    if missing:
        raise MissingPromptVariables(missing)
    return (
        _render_one(system_prompt, filled),
        _render_one(user_prompt, filled),
        declared,
    )


def diff_prompt_lines(old_text: str, new_text: str) -> list[dict[str, object]]:
    """Line-level diff with old/new line numbers for the Prompt Lab view."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    rows: list[dict[str, object]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                rows.append(
                    {
                        "type": "equal",
                        "old_line": i1 + offset + 1,
                        "new_line": j1 + offset + 1,
                        "text": old_lines[i1 + offset],
                    }
                )
        elif tag == "delete":
            for index in range(i1, i2):
                rows.append(
                    {
                        "type": "delete",
                        "old_line": index + 1,
                        "new_line": None,
                        "text": old_lines[index],
                    }
                )
        elif tag == "insert":
            for index in range(j1, j2):
                rows.append(
                    {
                        "type": "insert",
                        "old_line": None,
                        "new_line": index + 1,
                        "text": new_lines[index],
                    }
                )
        else:
            for index in range(i1, i2):
                rows.append(
                    {
                        "type": "delete",
                        "old_line": index + 1,
                        "new_line": None,
                        "text": old_lines[index],
                    }
                )
            for index in range(j1, j2):
                rows.append(
                    {
                        "type": "insert",
                        "old_line": None,
                        "new_line": index + 1,
                        "text": new_lines[index],
                    }
                )
    return rows


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
                PromptTemplate.scope == "workspace",
                PromptTemplate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise _not_found()
    return template


async def get_accessible_template(
    template_id: UUID, workspace_id: UUID, session: AsyncSession
) -> PromptTemplate:
    template = (
        await session.execute(
            select(PromptTemplate).where(
                PromptTemplate.id == template_id,
                PromptTemplate.deleted_at.is_(None),
                or_(
                    PromptTemplate.workspace_id == workspace_id,
                    PromptTemplate.scope == "platform",
                ),
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise _not_found()
    return template


async def get_platform_template(
    session: AsyncSession, template_id: UUID
) -> PromptTemplate:
    template = (
        await session.execute(
            select(PromptTemplate).where(
                PromptTemplate.id == template_id,
                PromptTemplate.scope == "platform",
                PromptTemplate.workspace_id.is_(None),
                PromptTemplate.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if template is None:
        raise _not_found()
    return template


async def list_platform_templates(session: AsyncSession) -> list[PromptTemplate]:
    result = await session.execute(
        select(PromptTemplate)
        .where(
            PromptTemplate.scope == "platform",
            PromptTemplate.workspace_id.is_(None),
            PromptTemplate.deleted_at.is_(None),
        )
        .order_by(PromptTemplate.created_at.desc(), PromptTemplate.id.desc())
    )
    return list(result.scalars())


async def list_versions(session: AsyncSession, template_id: UUID) -> list[PromptVersion]:
    result = await session.execute(
        select(PromptVersion)
        .where(PromptVersion.template_id == template_id)
        .order_by(PromptVersion.version.desc())
    )
    return list(result.scalars())


async def list_templates(
    session: AsyncSession,
    workspace_id: UUID,
    *,
    q: str | None = None,
    category: str | None = None,
    favorite_user_id: UUID | None = None,
    favorite_only: bool = False,
) -> list[PromptTemplate]:
    conditions = [
        PromptTemplate.deleted_at.is_(None),
        or_(
            PromptTemplate.workspace_id == workspace_id,
            PromptTemplate.scope == "platform",
        ),
    ]
    if category:
        conditions.append(PromptTemplate.category == category)
    if q and q.strip():
        term = f"%{q.strip()}%"
        conditions.append(
            or_(
                PromptTemplate.name.ilike(term),
                PromptTemplate.description.ilike(term),
                exists(
                    select(PromptVersion.id).where(
                        PromptVersion.template_id == PromptTemplate.id,
                        or_(
                            PromptVersion.system_prompt.ilike(term),
                            PromptVersion.user_prompt.ilike(term),
                        ),
                    )
                ),
            )
        )
    if favorite_only and favorite_user_id is not None:
        conditions.append(
            exists(
                select(PromptFavorite.id).where(
                    PromptFavorite.template_id == PromptTemplate.id,
                    PromptFavorite.user_id == favorite_user_id,
                )
            )
        )
    result = await session.execute(
        select(PromptTemplate)
        .where(*conditions)
        .order_by(PromptTemplate.created_at.desc(), PromptTemplate.id.desc())
    )
    return list(result.scalars())


async def favorite_ids(
    session: AsyncSession, user_id: UUID, template_ids: list[UUID]
) -> set[UUID]:
    if not template_ids:
        return set()
    rows = (
        await session.execute(
            select(PromptFavorite.template_id).where(
                PromptFavorite.user_id == user_id,
                PromptFavorite.template_id.in_(template_ids),
            )
        )
    ).scalars().all()
    return set(rows)


async def set_favorite(
    session: AsyncSession, template_id: UUID, user_id: UUID, favorite: bool
) -> bool:
    existing = (
        await session.execute(
            select(PromptFavorite).where(
                PromptFavorite.template_id == template_id,
                PromptFavorite.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if favorite and existing is None:
        session.add(PromptFavorite(template_id=template_id, user_id=user_id))
    elif not favorite and existing is not None:
        await session.execute(
            delete(PromptFavorite).where(
                PromptFavorite.template_id == template_id,
                PromptFavorite.user_id == user_id,
            )
        )
    await session.flush()
    return favorite


async def update_template(
    session: AsyncSession, template: PromptTemplate, values: dict[str, object]
) -> PromptTemplate:
    for key, value in values.items():
        setattr(template, key, value)
    await session.commit()
    await session.refresh(template)
    return template


async def create_template(
    session: AsyncSession,
    *,
    workspace_id: UUID | None,
    user_id: UUID,
    name: str,
    description: str,
    system_prompt: str,
    category: str = "general",
    user_prompt: str = "",
    variable_definitions: list[dict] | None = None,
    parameters: dict | None = None,
    scope: str = "workspace",
) -> tuple[PromptTemplate, PromptVersion]:
    template = PromptTemplate(
        workspace_id=workspace_id,
        scope=scope,
        name=name,
        description=description,
        category=category,
        created_by=user_id,
    )
    session.add(template)
    await session.flush()
    version = PromptVersion(
        template_id=template.id,
        version=1,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        variables=extract_variables(system_prompt, user_prompt),
        variable_definitions=variable_definitions or [],
        parameters=parameters or {},
    )
    session.add(version)
    await session.commit()
    await session.refresh(template)
    await session.refresh(version)
    return template, version


async def create_version(
    session: AsyncSession,
    template: PromptTemplate,
    system_prompt: str,
    user_prompt: str = "",
    variable_definitions: list[dict] | None = None,
    parameters: dict | None = None,
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
        user_prompt=user_prompt,
        variables=extract_variables(system_prompt, user_prompt),
        variable_definitions=variable_definitions or [],
        parameters=parameters or {},
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
                PromptTemplate.deleted_at.is_(None),
                or_(
                    PromptTemplate.workspace_id == workspace_id,
                    PromptTemplate.scope == "platform",
                ),
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
