import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document

logger = logging.getLogger(__name__)

ORPHAN_MAX_AGE_SECONDS = 24 * 3600


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
