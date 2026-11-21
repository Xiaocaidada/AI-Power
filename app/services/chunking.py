from dataclasses import dataclass

from app.services.parsing import ParsedPage


@dataclass(frozen=True)
class TextChunk:
    text: str
    page_no: int | None
    chunk_index: int


def chunk_pages(
    pages: list[ParsedPage], max_chars: int = 1000, overlap: int = 150
) -> list[TextChunk]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap must be in [0, max_chars)")

    chunks: list[TextChunk] = []
    index = 0
    for page in pages:
        text = page.text.strip()
        if not text:
            continue
        start = 0
        while start < len(text):
            end = min(start + max_chars, len(text))
            piece = text[start:end].strip()
            if piece:
                chunks.append(TextChunk(text=piece, page_no=page.page_no, chunk_index=index))
                index += 1
            if end >= len(text):
                break
            start = end - overlap
    return chunks
