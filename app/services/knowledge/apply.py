from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Chunk,
    ChunkEmbedding,
    Document,
    KnowledgeChunkDraft,
    WorkflowRun,
)


class KnowledgeApplyError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def apply_knowledge_run(
    session: AsyncSession,
    run: WorkflowRun,
    document: Document,
) -> dict[str, int]:
    if run.status != "completed":
        raise KnowledgeApplyError("run_not_completed", "Run is not completed")
    if run.applied_at is not None:
        raise KnowledgeApplyError("run_already_applied", "Run is already applied")
    if document.deleted_at is not None:
        raise KnowledgeApplyError("document_missing", "Document no longer exists")
    if run.kb_id != document.kb_id:
        raise KnowledgeApplyError("run_mismatch", "Run does not belong to this document")

    drafts = list(
        (
            await session.execute(
                select(KnowledgeChunkDraft)
                .where(KnowledgeChunkDraft.run_id == run.id)
                .order_by(KnowledgeChunkDraft.chunk_index)
            )
        ).scalars()
    )
    if not drafts:
        raise KnowledgeApplyError(
            "no_drafts", "This run has no staged chunks; add an index_knowledge node"
        )
    if any(draft.embedding is None for draft in drafts):
        raise KnowledgeApplyError(
            "embeddings_required", "All staged chunks must be embedded before applying"
        )

    await session.execute(delete(Chunk).where(Chunk.document_id == document.id))
    chunk_rows: list[Chunk] = []
    for draft in drafts:
        chunk_rows.append(
            Chunk(
                document_id=document.id,
                workspace_id=document.workspace_id,
                user_id=document.user_id,
                kb_id=document.kb_id,
                page_no=draft.page_no,
                chunk_index=draft.chunk_index,
                text=draft.text,
                token_count=draft.token_count,
            )
        )
    session.add_all(chunk_rows)
    await session.flush()
    session.add_all(
        [
            ChunkEmbedding(chunk_id=chunk.id, embedding=list(draft.embedding or []))
            for chunk, draft in zip(chunk_rows, drafts, strict=True)
        ]
    )

    output = dict(run.output_payload or {})
    document.status = "ready"
    document.error_code = None
    document.process_version_id = run.version_id
    document.page_count = int(output.get("page_count") or document.page_count or 0)
    run.applied_at = datetime.now(UTC)
    output["applied"] = True
    output["applied_chunks"] = len(chunk_rows)
    run.output_payload = output
    await session.execute(
        delete(KnowledgeChunkDraft).where(
            KnowledgeChunkDraft.document_id == document.id,
            KnowledgeChunkDraft.run_id != run.id,
        )
    )
    await session.commit()
    return {"chunks": len(chunk_rows), "document_id": str(document.id)}


def draft_preview(
    drafts: list[KnowledgeChunkDraft], limit: int = 20
) -> list[dict[str, object]]:
    return [
        {
            "chunk_index": draft.chunk_index,
            "page_no": draft.page_no,
            "text": draft.text[:2000],
            "meta": draft.chunk_meta or {},
            "embedded": draft.embedding is not None,
        }
        for draft in drafts[:limit]
    ]


def run_document_id(run: WorkflowRun) -> UUID | None:
    payload = run.input_payload or {}
    value = payload.get("document_id")
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None