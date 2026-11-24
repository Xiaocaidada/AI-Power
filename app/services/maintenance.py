import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import AuditLog, Document, MediaAsset, Trace

logger = logging.getLogger(__name__)

ORPHAN_MAX_AGE_SECONDS = 24 * 3600
TRACE_MAX_AGE_DAYS = 7


async def cleanup_traces(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    max_age_days: int = TRACE_MAX_AGE_DAYS,
) -> int:
    threshold = (now or datetime.now(UTC)) - timedelta(days=max_age_days)
    result = await session.execute(delete(Trace).where(Trace.created_at < threshold))
    await session.commit()
    return result.rowcount or 0


async def cleanup_audit_logs(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    max_age_days: int | None = None,
) -> int:
    days = max_age_days if max_age_days is not None else get_settings().audit_log_retention_days
    threshold = (now or datetime.now(UTC)) - timedelta(days=days)
    result = await session.execute(delete(AuditLog).where(AuditLog.created_at < threshold))
    await session.commit()
    return result.rowcount or 0


async def cleanup_media_assets(
    session: AsyncSession,
    upload_dir: Path,
    *,
    now: datetime | None = None,
    max_age_days: int | None = None,
) -> int:
    """Expire generated media rows and their files after the retention window."""
    days = (
        max_age_days
        if max_age_days is not None
        else get_settings().integration_media_retention_days
    )
    threshold = (now or datetime.now(UTC)) - timedelta(days=days)
    rows = list(
        (
            await session.execute(
                select(MediaAsset).where(MediaAsset.created_at < threshold)
            )
        ).scalars()
    )
    if not rows:
        return 0
    base = Path(upload_dir).resolve()
    removed = 0
    for asset in rows:
        path = Path(asset.storage_path).resolve()
        if path.is_relative_to(base):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logger.warning("failed to remove media file %s", asset.id)
        await session.delete(asset)
        removed += 1
    await session.commit()
    return removed


async def cleanup_orphan_files(
    session: AsyncSession,
    upload_dir: Path,
    *,
    now: datetime | None = None,
    max_age_seconds: int = ORPHAN_MAX_AGE_SECONDS,
) -> int:
    """Delete upload files with no Document row once they are old enough."""
    directory = Path(upload_dir)
    if not directory.is_dir():
        return 0

    known = set((await session.execute(select(Document.storage_path))).scalars())
    threshold = (now or datetime.now(UTC)) - timedelta(seconds=max_age_seconds)
    removed = 0
    for path in directory.iterdir():
        if not path.is_file() or path.name in known:
            continue
        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        except OSError:
            continue
        if modified_at > threshold:
            continue
        try:
            path.unlink()
        except OSError:
            logger.warning("failed to remove orphan file %s", path.name)
            continue
        removed += 1
    return removed
