"""Seed the retrieval evaluation corpus into a knowledge base.

Creates deterministic user/KB/document IDs, ingests every document through the
real pipeline (parser -> chunks -> bge-m3), and writes the runtime question file.

Usage:
    python scripts/seed_eval.py
    python scripts/seed_eval.py --dataset eval/dataset.json --questions eval/questions.jsonl

Then evaluate with the printed user-id / kb-id:
    python scripts/eval_retrieval.py --dataset eval/questions.jsonl \
        --user-id <uuid> --kb-id <uuid> --top-k 5
"""

import argparse
import asyncio
import hashlib
from pathlib import Path
from uuid import uuid5

from sqlalchemy import delete, func, select

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.models import Chunk, ChunkEmbedding, Document, KnowledgeBase, User
from app.services.evaluation import (
    EVAL_NAMESPACE,
    document_id_for,
    load_eval_dataset,
    render_questions_jsonl,
)
from app.services.ingestion import ingest_document

EVAL_USER_ID = uuid5(EVAL_NAMESPACE, "user")
EVAL_KB_ID = uuid5(EVAL_NAMESPACE, "kb")
EVAL_USER_EMAIL = "retrieval-eval@ai-power.local"
EVAL_KB_NAME = "检索评测集"


async def _ensure_owner(session) -> None:
    if await session.get(User, EVAL_USER_ID) is None:
        session.add(
            User(
                id=EVAL_USER_ID,
                email=EVAL_USER_EMAIL,
                password_hash="!",
                role="user",
            )
        )
    if await session.get(KnowledgeBase, EVAL_KB_ID) is None:
        session.add(KnowledgeBase(id=EVAL_KB_ID, user_id=EVAL_USER_ID, name=EVAL_KB_NAME))
    await session.commit()


async def _clear(session) -> None:
    document_ids = select(Document.id).where(Document.kb_id == EVAL_KB_ID)
    chunk_ids = select(Chunk.id).where(Chunk.document_id.in_(document_ids))
    await session.execute(delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id.in_(chunk_ids)))
    await session.execute(delete(Chunk).where(Chunk.document_id.in_(document_ids)))
    await session.execute(delete(Document).where(Document.kb_id == EVAL_KB_ID))
    await session.commit()


async def _write_documents(session, documents, upload_dir: Path) -> None:
    for document in documents:
        document_id = document_id_for(document.filename)
        payload = document.text.encode("utf-8")
        path = upload_dir / f"{document_id}.md"
        path.write_text(document.text, encoding="utf-8")
        session.add(
            Document(
                id=document_id,
                kb_id=EVAL_KB_ID,
                user_id=EVAL_USER_ID,
                filename=document.filename,
                mime="text/markdown",
                size_bytes=len(payload),
                content_hash=hashlib.sha256(payload).hexdigest(),
                storage_path=path.name,
                status="uploaded",
            )
        )
    await session.commit()


async def seed(dataset_path: Path, questions_path: Path) -> int:
    documents, questions = load_eval_dataset(dataset_path)
    upload_dir = Path(get_settings().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    await init_db()

    async with SessionLocal() as session:
        await _ensure_owner(session)
        await _clear(session)
        await _write_documents(session, documents, upload_dir)

    for document in documents:
        await ingest_document(document_id_for(document.filename))

    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Document.status, func.count())
                .where(Document.kb_id == EVAL_KB_ID)
                .group_by(Document.status)
            )
        ).all()
        statuses = {status: count for status, count in rows}

    questions_path.parent.mkdir(parents=True, exist_ok=True)
    questions_path.write_text(render_questions_jsonl(questions), encoding="utf-8")

    print(f"documents: {len(documents)} statuses={statuses}")
    print(f"questions: {len(questions)} -> {questions_path}")
    print(f"user-id: {EVAL_USER_ID}")
    print(f"kb-id: {EVAL_KB_ID}")
    return 0 if statuses == {"ready": len(documents)} else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="eval/dataset.json")
    parser.add_argument("--questions", default="eval/questions.jsonl")
    args = parser.parse_args()
    return asyncio.run(seed(Path(args.dataset), Path(args.questions)))


if __name__ == "__main__":
    raise SystemExit(main())
