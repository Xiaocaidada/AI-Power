from pydantic import BaseModel, Field

from app.config import get_settings
from app.db import SessionLocal
from app.providers.base import ProviderError
from app.services.retrieval import Citation, RetrievedChunk, retrieve_chunks
from app.tools.base import ToolContext, ToolError, ToolSpec

ENTRY_TEXT_MAX_CHARS = 800
SNIPPET_MAX_CHARS = 240
SNIPPET_ELLIPSIS = "…"


class KnowledgeSearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=500)


async def knowledge_search(context: ToolContext, args: KnowledgeSearchArgs) -> str:
    if context.kb_id is None:
        raise ToolError("no_knowledge_base", "No knowledge base is attached to this conversation")
    async with SessionLocal() as session:
        try:
            chunks = await retrieve_chunks(
                session,
                workspace_id=context.workspace_id,
                kb_id=context.kb_id,
                query=args.query,
            )
        except ProviderError:
            raise ToolError("retrieval_failed", "Knowledge retrieval is unavailable") from None
    if not chunks:
        return "No matching material was found in the knowledge base."
    return _format_entries(chunks, context)


def _format_entries(chunks: list[RetrievedChunk], context: ToolContext) -> str:
    citations = context.citations if context.citations is not None else []
    indexes = {citation.chunk_id: citation.index for citation in citations}
    budget = get_settings().agent_tool_output_max_chars
    entries: list[str] = []
    for chunk in chunks:
        added = False
        index = indexes.get(chunk.chunk_id)
        if index is None:
            index = len(citations) + 1
            citations.append(
                Citation(
                    index=index,
                    document_id=chunk.document_id,
                    chunk_id=chunk.chunk_id,
                    page_no=chunk.page_no,
                    snippet=_snippet(chunk.text),
                )
            )
            indexes[chunk.chunk_id] = index
            added = True
        entry = _entry(index, chunk)
        if len(entry) > budget:
            if entries:
                if added:
                    citations.pop()
                    indexes.pop(chunk.chunk_id, None)
                break
            entry = entry[:budget]
        entries.append(entry)
        budget -= len(entry)
    if not entries:
        return "No matching material fit in the tool output budget."
    return "\n\n".join(entries)


def _entry(index: int, chunk: RetrievedChunk) -> str:
    text = chunk.text
    if len(text) > ENTRY_TEXT_MAX_CHARS:
        text = text[:ENTRY_TEXT_MAX_CHARS]
    location = f"{chunk.filename}, page {chunk.page_no}" if chunk.page_no else chunk.filename
    return f"[{index}] ({location})\n{text}"


def _snippet(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= SNIPPET_MAX_CHARS:
        return collapsed
    return collapsed[: SNIPPET_MAX_CHARS - 1] + SNIPPET_ELLIPSIS


def build_kb_search_tool() -> ToolSpec:
    return ToolSpec(
        name="kb_search",
        description=(
            "Search the conversation's knowledge base and return the most relevant "
            "passages, numbered for citation."
        ),
        args_model=KnowledgeSearchArgs,
        handler=knowledge_search,
    )
