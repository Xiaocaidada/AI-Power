import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Document,
    KnowledgeBase,
    KnowledgeChunkDraft,
    WorkflowArtifact,
    WorkflowNodeRun,
    WorkflowRun,
)
from app.services.kb_models import build_kb_embedder
from app.services.knowledge.chunkers import (
    chunk_fixed,
    chunk_markdown,
    chunk_recursive,
)
from app.services.knowledge.schema import (
    ChunkTextConfig,
    CleanTextConfig,
    EmbedChunksConfig,
    IndexKnowledgeConfig,
    KnowledgeNode,
    KnowledgeProcessDefinition,
    ParseDocumentConfig,
)
from app.services.knowledge_settings import KnowledgeBaseSettings, resolve_kb_settings
from app.services.parsing import ParsedPage, parser_for_mime

logger = logging.getLogger(__name__)

SUMMARY_MAX_CHARS = 500
PREVIEW_TEXT_CHARS = 120000
PREVIEW_PAGES = 40
PREVIEW_CHUNKS = 300
PREVIEW_CHUNK_CHARS = 4000
MAX_DRAFTS = 5000


class KnowledgePipelineError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class KnowledgeCancelled(Exception):
    pass


@dataclass(frozen=True, slots=True)
class PipelineEvent:
    kind: str
    data: dict[str, object]


@dataclass(slots=True)
class PipelineState:
    pages: list[ParsedPage]
    text: str = ""
    chunks: list[dict[str, object]] | None = None
    page_count: int = 0
    draft_count: int = 0
    embedded_count: int = 0


class KnowledgeProcessRunner:
    def __init__(
        self,
        *,
        run_id: UUID,
        workflow_id: UUID,
        version: int,
        definition: KnowledgeProcessDefinition,
        document: Document,
        kb: KnowledgeBase,
    ) -> None:
        self._run_id = run_id
        self._workflow_id = workflow_id
        self._version = version
        self._definition = definition
        self._document = document
        self._kb = kb
        self._settings = get_settings()
        self._kb_settings: KnowledgeBaseSettings = resolve_kb_settings(kb)

    async def run(self) -> AsyncIterator[PipelineEvent]:
        started = time.perf_counter()
        yield PipelineEvent(
            "workflow_start",
            {
                "run_id": str(self._run_id),
                "workflow_id": str(self._workflow_id),
                "version": self._version,
                "kind": "knowledge_process",
                "document_id": str(self._document.id),
                "filename": self._document.filename,
            },
        )
        state = PipelineState(pages=[], page_count=0)
        try:
            for node in self._definition.ordered_nodes():
                await self._check_cancel()
                yield PipelineEvent(
                    "node_start",
                    {
                        "run_id": str(self._run_id),
                        "node_id": node.id,
                        "node_type": node.type,
                    },
                )
                node_run_id = await self._start_node_run(node)
                node_started = time.perf_counter()
                try:
                    summary, preview_kind, preview = await self._execute_node(
                        node, state
                    )
                except KnowledgePipelineError as exc:
                    duration = _elapsed_ms(node_started)
                    await self._finish_node_run(
                        node_run_id, "failed", duration, "", exc.code
                    )
                    yield _node_end(self._run_id, node.id, "failed", duration, exc.code)
                    raise
                duration = _elapsed_ms(node_started)
                await self._finish_node_run(
                    node_run_id, "completed", duration, summary, None
                )
                if preview is not None:
                    await self._save_artifact(node.id, preview_kind, preview)
                yield _node_end(self._run_id, node.id, "completed", duration)
            total_ms = _elapsed_ms(started)
            await self._finish_run("completed", total_ms, None, state)
            yield PipelineEvent(
                "workflow_end",
                {
                    "run_id": str(self._run_id),
                    "status": "completed",
                    "total_ms": total_ms,
                    "page_count": state.page_count,
                    "chunk_count": len(state.chunks or []),
                    "draft_count": state.draft_count,
                    "embedded_count": state.embedded_count,
                    "output": _truncate(
                        f"{state.page_count} pages / {len(state.chunks or [])} chunks",
                        SUMMARY_MAX_CHARS,
                    ),
                },
            )
        except KnowledgeCancelled:
            total_ms = _elapsed_ms(started)
            await self._finish_run("cancelled", total_ms, "cancelled", state)
            yield PipelineEvent(
                "workflow_end",
                {
                    "run_id": str(self._run_id),
                    "status": "cancelled",
                    "error_code": "cancelled",
                    "total_ms": total_ms,
                },
            )
        except KnowledgePipelineError as exc:
            total_ms = _elapsed_ms(started)
            await self._finish_run("failed", total_ms, exc.code, state)
            yield PipelineEvent(
                "workflow_end",
                {
                    "run_id": str(self._run_id),
                    "status": "failed",
                    "error_code": exc.code,
                    "total_ms": total_ms,
                },
            )
        except Exception:
            logger.exception("knowledge process run %s failed", self._run_id)
            total_ms = _elapsed_ms(started)
            await self._finish_run("failed", total_ms, "internal_error", state)
            yield PipelineEvent(
                "workflow_end",
                {
                    "run_id": str(self._run_id),
                    "status": "failed",
                    "error_code": "internal_error",
                    "total_ms": total_ms,
                },
            )

    async def _check_cancel(self) -> None:
        async with SessionLocal() as session:
            requested = (
                await session.execute(
                    select(WorkflowRun.cancel_requested_at).where(
                        WorkflowRun.id == self._run_id
                    )
                )
            ).scalar_one_or_none()
        if requested is not None:
            raise KnowledgeCancelled()

    async def _execute_node(
        self, node: KnowledgeNode, state: PipelineState
    ) -> tuple[str, str, dict[str, object] | None]:
        if node.type == "start":
            path = self._document_path()
            state.text = ""
            return (
                f"{self._document.filename} ({path.suffix or self._document.mime})",
                "document",
                {
                    "document_id": str(self._document.id),
                    "filename": self._document.filename,
                    "mime": self._document.mime,
                },
            )
        if node.type == "parse_document":
            config = ParseDocumentConfig.model_validate(node.config)
            pages = self._parse_pages()
            if not config.keep_blank_pages:
                pages = [page for page in pages if page.text.strip()]
            if len(pages) > self._settings.max_document_pages:
                raise KnowledgePipelineError(
                    "too_many_pages",
                    f"Document has {len(pages)} pages "
                    f"(limit {self._settings.max_document_pages})",
                )
            state.pages = pages
            state.page_count = len(pages)
            state.text = "\n\n".join(page.text for page in pages)
            if not state.text.strip():
                raise KnowledgePipelineError("empty_document", "Document produced no text")
            return (
                f"{len(pages)} pages / {len(state.text)} chars",
                "parsed",
                _preview_pages(pages, state.text),
            )
        if node.type == "clean_text":
            config = CleanTextConfig.model_validate(node.config)
            state.pages = [
                ParsedPage(page_no=page.page_no, text=_clean(page.text, config))
                for page in state.pages
            ]
            state.text = "\n\n".join(page.text for page in state.pages)
            return (
                f"{len(state.text)} chars",
                "cleaned",
                _preview_pages(state.pages, state.text),
            )
        if node.type == "chunk_text":
            if not state.pages:
                raise KnowledgePipelineError("missing_pages", "Parse the document first")
            config = ChunkTextConfig.model_validate(node.config)
            state.chunks = self._chunk(state.pages, config)
            if not state.chunks:
                raise KnowledgePipelineError("empty_document", "No chunks produced")
            return (
                f"{len(state.chunks)} chunks",
                "chunks",
                _preview_chunks(state.chunks),
            )
        if node.type == "embed_chunks":
            config = EmbedChunksConfig.model_validate(node.config)
            if not state.chunks:
                raise KnowledgePipelineError("missing_chunks", "Chunk the document first")
            embedded = await self._embed(state.chunks, config)
            state.embedded_count = embedded
            return (
                f"{embedded} vectors",
                "embeddings",
                {"embedded_count": embedded, "dimensions": self._kb_settings.embedding.dimensions},
            )
        if node.type == "index_knowledge":
            config = IndexKnowledgeConfig.model_validate(node.config)
            if not state.chunks:
                raise KnowledgePipelineError("missing_chunks", "Chunk the document first")
            if config.require_embeddings and any(
                not chunk.get("embedding") for chunk in state.chunks
            ):
                raise KnowledgePipelineError(
                    "embeddings_required",
                    "All chunks must be embedded before indexing",
                )
            if len(state.chunks) > MAX_DRAFTS:
                raise KnowledgePipelineError(
                    "too_many_chunks", f"At most {MAX_DRAFTS} chunks are allowed"
                )
            state.draft_count = await self._write_drafts(state.chunks)
            return (
                f"{state.draft_count} drafts staged",
                "index",
                {"draft_count": state.draft_count},
            )
        if node.type == "output":
            return (
                f"{len(state.chunks or [])} chunks / {state.draft_count} drafts",
                "summary",
                {
                    "page_count": state.page_count,
                    "chunk_count": len(state.chunks or []),
                    "draft_count": state.draft_count,
                    "embedded_count": state.embedded_count,
                },
            )
        raise KnowledgePipelineError(
            "unsupported_node_type", f"Unsupported node type: {node.type}"
        )

    def _document_path(self) -> Path:
        root = Path(self._settings.upload_dir).resolve()
        stored = Path(self._document.storage_path)
        path = (stored if stored.is_absolute() else root / stored).resolve()
        if not path.is_relative_to(root):
            raise KnowledgePipelineError("invalid_path", "Document path is outside uploads")
        if not path.exists():
            raise KnowledgePipelineError("file_missing", "Document file is missing")
        return path

    def _parse_pages(self) -> list[ParsedPage]:
        path = self._document_path()
        try:
            parser = parser_for_mime(self._document.mime)
        except Exception:
            raise KnowledgePipelineError(
                "unsupported_document_type",
                f"Unsupported document type: {self._document.mime}",
            ) from None
        try:
            parsed = parser.parse(path, self._document.mime)
        except Exception as exc:
            raise KnowledgePipelineError(
                "parse_failed", f"Document parsing failed: {type(exc).__name__}"
            ) from None
        return list(parsed.pages)

    def _chunk(
        self, pages: list[ParsedPage], config: ChunkTextConfig
    ) -> list[dict[str, object]]:
        if config.strategy == "markdown":
            return chunk_markdown(
                pages,
                chunk_size=config.chunk_size,
                chunk_overlap=config.chunk_overlap,
                min_chars=config.min_chars,
                keep_heading=config.keep_heading,
            )
        if config.strategy == "recursive":
            return chunk_recursive(
                pages,
                chunk_size=config.chunk_size,
                chunk_overlap=config.chunk_overlap,
                min_chars=config.min_chars,
            )
        return chunk_fixed(
            pages,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            min_chars=config.min_chars,
        )

    async def _embed(
        self, chunks: list[dict[str, object]], config: EmbedChunksConfig
    ) -> int:
        batch_size = config.batch_size or self._settings.embedding_batch_size
        expected = self._kb_settings.embedding.dimensions
        embedded = 0
        async with SessionLocal() as session:
            try:
                embedder = await build_kb_embedder(session, self._kb, self._kb_settings)
            except Exception as exc:
                raise KnowledgePipelineError(
                    "embedding_unavailable",
                    f"Embedding model is unavailable: {type(exc).__name__}",
                ) from None
            for start in range(0, len(chunks), batch_size):
                batch = chunks[start : start + batch_size]
                try:
                    vectors = await embedder.embed([str(chunk["text"]) for chunk in batch])
                except Exception as exc:
                    raise KnowledgePipelineError(
                        "embedding_failed",
                        f"Embedding failed: {type(exc).__name__}",
                    ) from None
                if len(vectors) != len(batch):
                    raise KnowledgePipelineError(
                        "embedding_count_mismatch",
                        "Embedding count does not match chunk count",
                    )
                for chunk, vector in zip(batch, vectors, strict=True):
                    if len(vector) != expected:
                        raise KnowledgePipelineError(
                            "embedding_dimension_mismatch",
                            f"Expected {expected} dimensions, got {len(vector)}",
                        )
                    chunk["embedding"] = [float(value) for value in vector]
                    embedded += 1
        return embedded

    async def _write_drafts(self, chunks: list[dict[str, object]]) -> int:
        async with SessionLocal() as session:
            await session.execute(
                delete(KnowledgeChunkDraft).where(
                    KnowledgeChunkDraft.run_id == self._run_id
                )
            )
            for chunk in chunks:
                session.add(
                    KnowledgeChunkDraft(
                        run_id=self._run_id,
                        workspace_id=self._document.workspace_id,
                        kb_id=self._document.kb_id,
                        document_id=self._document.id,
                        chunk_index=int(chunk["chunk_index"]),
                        page_no=(
                            chunk.get("page_no")
                            if isinstance(chunk.get("page_no"), int)
                            else None
                        ),
                        text=str(chunk["text"]),
                        chunk_meta=dict(chunk.get("meta") or {}),
                        embedding=chunk.get("embedding"),
                    )
                )
            await session.commit()
        return len(chunks)

    async def _start_node_run(self, node: KnowledgeNode) -> UUID:
        try:
            async with SessionLocal() as session:
                record = WorkflowNodeRun(
                    run_id=self._run_id,
                    node_id=node.id,
                    node_type=node.type,
                    status="running",
                )
                session.add(record)
                await session.commit()
                await session.refresh(record)
                return record.id
        except Exception:
            logger.exception("failed to create knowledge node run")
            return UUID(int=0)

    async def _finish_node_run(
        self,
        node_run_id: UUID,
        status: str,
        duration_ms: float,
        output: str,
        error_code: str | None,
    ) -> None:
        if node_run_id == UUID(int=0):
            return
        try:
            async with SessionLocal() as session:
                record = await session.get(WorkflowNodeRun, node_run_id)
                if record is None:
                    return
                record.status = status
                record.duration_ms = duration_ms
                record.output_summary = output[:SUMMARY_MAX_CHARS]
                record.error_code = error_code
                await session.commit()
        except Exception:
            logger.exception("failed to finalize knowledge node run")

    async def _save_artifact(
        self, node_id: str, kind: str, payload: dict[str, object]
    ) -> None:
        try:
            async with SessionLocal() as session:
                await session.execute(
                    delete(WorkflowArtifact).where(
                        WorkflowArtifact.run_id == self._run_id,
                        WorkflowArtifact.node_id == node_id,
                    )
                )
                session.add(
                    WorkflowArtifact(
                        run_id=self._run_id,
                        node_id=node_id,
                        kind=kind,
                        payload=payload,
                    )
                )
                await session.commit()
        except Exception:
            logger.warning("failed to store knowledge artifact", exc_info=True)

    async def _finish_run(
        self,
        status: str,
        total_ms: float,
        error_code: str | None,
        state: PipelineState,
    ) -> None:
        try:
            async with SessionLocal() as session:
                run = await session.get(WorkflowRun, self._run_id)
                if run is None:
                    return
                run.status = status
                run.error_code = error_code
                run.total_ms = total_ms
                run.finished_at = datetime.now(UTC)
                if status == "completed":
                    run.output_payload = {
                        "page_count": state.page_count,
                        "chunk_count": len(state.chunks or []),
                        "draft_count": state.draft_count,
                        "embedded_count": state.embedded_count,
                        "applied": False,
                    }
                await session.commit()
        except Exception:
            logger.exception("failed to finalize knowledge process run")


def _clean(text: str, config: CleanTextConfig) -> str:
    value = text
    if config.strip_control:
        value = "".join(
            char for char in value if char in "\n\t" or ord(char) >= 32
        )
    if config.strip_urls:
        value = re.sub(r"https?://\S+", "", value)
    if config.collapse_whitespace:
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _preview_pages(pages: list[ParsedPage], text: str) -> dict[str, object]:
    preview_pages = [
        {"page_no": page.page_no, "text": _truncate(page.text, PREVIEW_CHUNK_CHARS)}
        for page in pages[:PREVIEW_PAGES]
    ]
    return {
        "page_count": len(pages),
        "text": _truncate(text, PREVIEW_TEXT_CHARS),
        "pages": preview_pages,
    }


def _preview_chunks(chunks: list[dict[str, object]]) -> dict[str, object]:
    items = [
        {
            "chunk_index": chunk["chunk_index"],
            "page_no": chunk.get("page_no"),
            "text": _truncate(str(chunk["text"]), PREVIEW_CHUNK_CHARS),
            "meta": chunk.get("meta") or {},
        }
        for chunk in chunks[:PREVIEW_CHUNKS]
    ]
    return {"chunk_count": len(chunks), "chunks": items}


def _node_end(
    run_id: UUID, node_id: str, status: str, duration_ms: float, error_code: str | None = None
) -> PipelineEvent:
    data: dict[str, object] = {
        "run_id": str(run_id),
        "node_id": node_id,
        "status": status,
        "duration_ms": duration_ms,
    }
    if error_code is not None:
        data["error_code"] = error_code
    return PipelineEvent("node_end", data)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)