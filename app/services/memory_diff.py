"""Diff snapshots for memory versions."""

import difflib
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentMemory, MemoryVersion

DIFF_FIELDS = (
    "title",
    "category",
    "scope_type",
    "project_id",
    "agent_id",
    "status",
    "importance",
    "enabled",
    "pinned",
    "favorite",
    "sensitivity",
    "confidence",
    "valid_until",
    "retention_days",
)
CONTENT_DIFF_LIMIT = 20000


class MemoryDiffError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _content_diff(before: str, after: str) -> str:
    lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="before",
            tofile="after",
            lineterm="",
        )
    )
    text = "\n".join(lines)
    return text[:CONTENT_DIFF_LIMIT]


def _risk_flags(
    before: dict[str, Any],
    after: dict[str, Any],
    changes: list[dict[str, Any]],
) -> list[str]:
    flags: list[str] = []
    before_content = str(before.get("content") or "")
    after_content = str(after.get("content") or "")
    if before_content and len(after_content) < len(before_content) * 0.5:
        flags.append("content_shrunk")
    if before.get("sensitivity") != "sensitive" and after.get("sensitivity") == "sensitive":
        flags.append("sensitivity_increased")
    if before.get("scope_type") != after.get("scope_type"):
        flags.append("scope_changed")
    if before.get("status") == "active" and after.get("status") != "active":
        flags.append("deactivated")
    try:
        if float(after.get("confidence") or 0) < float(before.get("confidence") or 0) - 0.2:
            flags.append("confidence_dropped")
    except (TypeError, ValueError):
        pass
    if before.get("project_id") != after.get("project_id") or before.get(
        "agent_id"
    ) != after.get("agent_id"):
        flags.append("binding_changed")
    before_tags = set(before.get("tags") or [])
    after_tags = set(after.get("tags") or [])
    if before_tags - after_tags:
        flags.append("tags_removed")
    if any(change["field"] == "content" for change in changes):
        flags.append("content_changed")
    return flags


async def diff_memory_versions(
    session: AsyncSession,
    memory: AgentMemory,
    *,
    from_version: int | None = None,
    to_version: int | None = None,
) -> dict[str, Any]:
    versions = list(
        (
            await session.execute(
                select(MemoryVersion)
                .where(MemoryVersion.memory_id == memory.id)
                .order_by(MemoryVersion.version.asc())
            )
        ).scalars()
    )
    if len(versions) < 2 and from_version is None and to_version is None:
        raise MemoryDiffError("not_enough_versions", "At least two versions are required")
    by_number = {row.version: row for row in versions}
    target = to_version if to_version is not None else versions[-1].version
    source = (
        from_version
        if from_version is not None
        else max(version for version in by_number if version < target)
        if any(version < target for version in by_number)
        else target
    )
    if source not in by_number or target not in by_number:
        raise MemoryDiffError("not_found", "Memory version not found")
    before_row = by_number[source]
    after_row = by_number[target]
    before = dict(before_row.snapshot or {})
    after = dict(after_row.snapshot or {})
    changes: list[dict[str, Any]] = []
    for field in DIFF_FIELDS:
        previous = before.get(field)
        current = after.get(field)
        if previous != current:
            changes.append(
                {"field": field, "before": previous, "after": current}
            )
    before_tags = list(before.get("tags") or [])
    after_tags = list(after.get("tags") or [])
    if before_tags != after_tags:
        changes.append(
            {"field": "tags", "before": before_tags, "after": after_tags}
        )
    before_content = str(before.get("content") or "")
    after_content = str(after.get("content") or "")
    content_diff = ""
    if before_content != after_content:
        changes.append(
            {
                "field": "content",
                "before": f"{len(before_content)} chars",
                "after": f"{len(after_content)} chars",
            }
        )
        content_diff = _content_diff(before_content, after_content)
    return {
        "from_version": source,
        "to_version": target,
        "from_created_at": before_row.created_at,
        "to_created_at": after_row.created_at,
        "from_reason": before_row.change_reason,
        "to_reason": after_row.change_reason,
        "changes": changes,
        "content_diff": content_diff,
        "risk_flags": _risk_flags(before, after, changes),
    }