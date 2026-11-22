from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class UnsupportedDocumentType(Exception):
    def __init__(self, mime: str) -> None:
        super().__init__(f"Unsupported document type: {mime}")
        self.mime = mime


@dataclass(frozen=True)
class ParsedPage:
    page_no: int | None
    text: str


@dataclass(frozen=True)
class ParsedDocument:
    pages: list[ParsedPage]


class DocumentParser(Protocol):
    def parse(self, path: Path, mime: str) -> ParsedDocument: ...


class TextDocumentParser:
    def parse(self, path: Path, mime: str) -> ParsedDocument:
        text = path.read_text(encoding="utf-8", errors="replace")
        return ParsedDocument(pages=[ParsedPage(page_no=None, text=text)])


class PdfDocumentParser:
    def parse(self, path: Path, mime: str) -> ParsedDocument:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        pages = [
            ParsedPage(page_no=index + 1, text=page.extract_text() or "")
            for index, page in enumerate(reader.pages)
        ]
        return ParsedDocument(pages=pages)


class DocxDocumentParser:
    def parse(self, path: Path, mime: str) -> ParsedDocument:
        from docx import Document as DocxDocument

        document = DocxDocument(str(path))
        parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            for row in table.rows:
                parts.append("\t".join(cell.text for cell in row.cells))
        return ParsedDocument(pages=[ParsedPage(page_no=None, text="\n".join(parts))])


class CsvDocumentParser:
    def parse(self, path: Path, mime: str) -> ParsedDocument:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        return ParsedDocument(pages=[ParsedPage(page_no=None, text=text)])


_EXTENSION_MIME = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".csv": "text/csv",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}


def detect_mime(filename: str | None, content_type: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    mime = _EXTENSION_MIME.get(suffix)
    if mime is None:
        raise UnsupportedDocumentType(content_type or suffix or "unknown")
    return mime


def parser_for_mime(mime: str) -> DocumentParser:
    if mime == "application/pdf":
        return PdfDocumentParser()
    if mime in {"text/plain", "text/markdown"}:
        return TextDocumentParser()
    if mime == "text/csv":
        return CsvDocumentParser()
    if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return DocxDocumentParser()
    raise UnsupportedDocumentType(mime)
