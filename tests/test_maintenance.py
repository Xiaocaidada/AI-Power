import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.db import SessionLocal
from app.models import Document, KnowledgeBase, User, Workspace


async def _seed_document(storage_path: str):
    async with SessionLocal() as session:
        user = User(email=f"{uuid4()}@maint.local", password_hash="x")
        session.add(user)
        await session.flush()
        workspace = Workspace(name="KB", plan="free", is_personal=False)
        session.add(workspace)
        await session.flush()
        kb = KnowledgeBase(workspace_id=workspace.id, user_id=user.id, name="KB")
        session.add(kb)
        await session.flush()
        session.add(
            Document(
                workspace_id=workspace.id,
                kb_id=kb.id,
                user_id=user.id,
                filename="known.txt",
                mime="text/plain",
                size_bytes=1,
                content_hash=str(uuid4()),
                storage_path=storage_path,
                status="ready",
            )
        )
        await session.commit()


async def test_cleanup_orphan_files_removes_only_old_unreferenced_files(tmp_path):
    from app.services.maintenance import cleanup_orphan_files

    now = datetime.now(UTC)
    await _seed_document("known.txt")
    known = tmp_path / "known.txt"
    old_orphan = tmp_path / "old-orphan.txt"
    new_orphan = tmp_path / "new-orphan.txt"
    for path in (known, old_orphan, new_orphan):
        path.write_text("x", encoding="utf-8")

    old_time = (now - timedelta(days=2)).timestamp()
    os.utime(old_orphan, (old_time, old_time))
    os.utime(known, (old_time, old_time))

    async with SessionLocal() as session:
        removed = await cleanup_orphan_files(session, tmp_path, now=now)

    assert removed == 1
    assert known.exists()
    assert new_orphan.exists()
    assert not old_orphan.exists()
