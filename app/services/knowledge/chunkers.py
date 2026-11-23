import re

from app.services.chunking import chunk_pages
from app.services.parsing import ParsedPage

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
RECURSIVE_SEPARATORS = ["\n\n", "\n", "。", "！", "？", ". ", "，", ",", " "]


def _chunk(
    text: str, page_no: int | None, index: int, meta: dict[str, object] | None = None
) -> dict[str, object]:
    return {
        "chunk_index": index,
        "page_no": page_no,
        "text": text,
        "meta": meta or {},
    }


def _merge_small(
    chunks: list[dict[str, object]], chunk_size: int, min_chars: int
) -> list[dict[str, object]]:
    if min_chars <= 0 or len(chunks) <= 1:
        return chunks
    merged: list[dict[str, object]] = []
    for chunk in chunks:
        if merged:
            previous = merged[-1]
            combined = f"{previous['text']}\n\n{chunk['text']}"
            if (
                len(str(previous["text"])) < min_chars
                and len(combined) <= chunk_size
            ):
                previous["text"] = combined
                if previous.get("page_no") != chunk.get("page_no"):
                    previous["page_no"] = None
                continue
        merged.append(chunk)
    for index, chunk in enumerate(merged):
        chunk["chunk_index"] = index
    return merged


def _fixed_page(
    page: ParsedPage, chunk_size: int, overlap: int, start_index: int
) -> list[dict[str, object]]:
    text_chunks = chunk_pages([page], chunk_size, overlap)
    return [
        _chunk(item.text, item.page_no, start_index + item.chunk_index)
        for item in text_chunks
    ]


def _merge_pages(pages: list[ParsedPage], keep_blank: bool) -> list[ParsedPage]:
    if keep_blank:
        return pages
    return [page for page in pages if page.text.strip()]


def chunk_fixed(
    pages: list[ParsedPage],
    *,
    chunk_size: int,
    chunk_overlap: int,
    min_chars: int,
    keep_blank_pages: bool = False,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for page in _merge_pages(pages, keep_blank_pages):
        result.extend(_fixed_page(page, chunk_size, chunk_overlap, len(result)))
    return _merge_small(result, chunk_size, min_chars)


def _split_recursive(text: str, chunk_size: int, separators: list[str]) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    separator = separators[0] if separators else ""
    rest = separators[1:] if separators else []
    if not separator:
        return [text[start : start + chunk_size] for start in range(0, len(text), chunk_size)]
    parts = text.split(separator)
    pieces: list[str] = []
    for index, part in enumerate(parts):
        if not part:
            continue
        suffix = separator if index < len(parts) - 1 else ""
        piece = f"{part}{suffix}"
        if len(piece) > chunk_size:
            pieces.extend(_split_recursive(piece, chunk_size, rest))
        else:
            pieces.append(piece)
    return pieces


def chunk_recursive(
    pages: list[ParsedPage],
    *,
    chunk_size: int,
    chunk_overlap: int,
    min_chars: int,
    keep_blank_pages: bool = False,
) -> list[dict[str, object]]:
    del chunk_overlap  # recursive chunks use natural separators; overlap is fixed-mode only
    result: list[dict[str, object]] = []
    for page in _merge_pages(pages, keep_blank_pages):
        pieces = _split_recursive(page.text.strip(), chunk_size, RECURSIVE_SEPARATORS)
        buffer = ""
        for piece in pieces:
            candidate = f"{buffer}{piece}" if buffer else piece
            if len(candidate) <= chunk_size:
                buffer = candidate
                continue
            if buffer.strip():
                result.append(_chunk(buffer.strip(), page.page_no, len(result)))
            buffer = piece
        if buffer.strip():
            result.append(_chunk(buffer.strip(), page.page_no, len(result)))
    return _merge_small(result, chunk_size, min_chars)


def _markdown_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    buffer: list[str] = []
    for line in text.splitlines():
        match = HEADING.match(line.strip())
        if match:
            if buffer:
                heading = " > ".join(item[1] for item in stack)
                sections.append((heading, "\n".join(buffer).strip()))
                buffer = []
            level = len(match.group(1))
            title = match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            buffer.append(line)
        else:
            buffer.append(line)
    if buffer:
        heading = " > ".join(item[1] for item in stack)
        sections.append((heading, "\n".join(buffer).strip()))
    return [(heading, body) for heading, body in sections if body]


def chunk_markdown(
    pages: list[ParsedPage],
    *,
    chunk_size: int,
    chunk_overlap: int,
    min_chars: int,
    keep_heading: bool = True,
    keep_blank_pages: bool = False,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for page in _merge_pages(pages, keep_blank_pages):
        for heading, body in _markdown_sections(page.text):
            meta: dict[str, object] = {}
            prefix = ""
            if keep_heading and heading:
                meta["heading"] = heading
                prefix = f"{heading}\n"
            if len(prefix) + len(body) <= chunk_size:
                result.append(_chunk(f"{prefix}{body}", page.page_no, len(result), meta))
                continue
            for piece in _split_recursive(
                body,
                max(50, chunk_size - len(prefix)),
                ["\n\n", "\n", "。", ". ", " "],
            ):
                result.append(
                    _chunk(f"{prefix}{piece}".strip(), page.page_no, len(result), meta)
                )
    return _merge_small(result, chunk_size, min_chars)
