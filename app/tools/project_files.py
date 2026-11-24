"""Read-only access to documents explicitly attached to the current project."""

from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Chunk, Document, ProjectDocument
from app.tools.base import ToolContext, ToolError, ToolSpec

MAX_OUTPUT_CHARS = 3500
MAX_CHUNKS = 8


class ProjectFilesArgs(BaseModel):
    query: str = Field(default="", max_length=300)
    document_id: UUID | None = None
    limit: int = Field(default=5, ge=1, le=10)


async def project_files(context: ToolContext, args: ProjectFilesArgs) -> str:
    if context.project_id is None:
        raise ToolError(
            "project_context_required",
            "This conversation or Agent node is not bound to a project",
        )
    async with SessionLocal() as session:
        if args.document_id is not None:
            link = (
                await session.execute(
                    select(ProjectDocument.id).where(
                        ProjectDocument.project_id == context.project_id,
                        ProjectDocument.document_id == args.document_id,
                    )
                )
            ).scalar_one_or_none()
            if link is None:
                raise ToolError(
                    "document_not_found", "Document is not attached to this project"
                )
            document = await session.get(Document, args.document_id)
            if (
                document is None
                or document.workspace_id != context.workspace_id
                or document.deleted_at is not None
            ):
                raise ToolError("document_not_found", "Document not found")
            texts = list(
                (
                    await session.execute(
                        select(Chunk.text)
                        .where(Chunk.document_id == document.id)
                        .order_by(Chunk.chunk_index)
                        .limit(MAX_CHUNKS)
                    )
                ).scalars()
            )
            body = "\n\n".join(texts)
            if not body:
                return f"{document.filename}\n\n(No indexed text is available yet.)"
            return f"{document.filename}\n\n{body[:MAX_OUTPUT_CHARS]}"

        conditions = [
            ProjectDocument.project_id == context.project_id,
            Document.workspace_id == context.workspace_id,
            Document.deleted_at.is_(None),
        ]
        if args.query.strip():
            conditions.append(Document.filename.ilike(f"%{args.query.strip()}%"))
        rows = list(
            (
                await session.execute(
                    select(Document)
                    .join(ProjectDocument, ProjectDocument.document_id == Document.id)
                    .where(*conditions)
                    .order_by(Document.created_at.desc(), Document.id.desc())
                    .limit(args.limit)
                )
            ).scalars()
        )
    if not rows:
        return "No project documents matched. Ask the project owner to attach files."
    lines = ["Project documents:"]
    for document in rows:
        lines.append(
            f"- {document.filename} (id={document.id}, status={document.status}, "
            f"size={document.size_bytes} bytes)"
        )
    lines.append(
        "Call again with document_id to read the beginning of one document."
    )
    return "\n".join(lines)


def build_project_files_tool() -> ToolSpec:
    return ToolSpec(
        name="project_files",
        description=(
            "List documents attached to the current project, or read the beginning "
            "of one attached document by document_id. Use this only when a project "
            "is bound to the conversation or Agent node."
        ),
        args_model=ProjectFilesArgs,
        handler=project_files,
    )