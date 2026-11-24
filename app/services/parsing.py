from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

from app.services.ocr import OcrError, ocr_image, ocr_ready


class UnsupportedDocumentType(Exception):
    def __init__(self, mime: str) -> None:
        super().__init__(f"Unsupported document type: {mime}")
        self.mime = mime


class OcrParseError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _ocr(data: bytes, mime: str) -> str:
    try:
        return ocr_image(data, mime)
    except OcrError as exc:
        raise OcrParseError(exc.code, exc.message) from None


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
        texts = [(page.extract_text() or "") for page in reader.pages]
        if ocr_ready() and any(not text.strip() for text in texts):
            import pymupdf

            document = pymupdf.open(str(path))
            try:
                for index, text in enumerate(texts):
                    if text.strip() or index >= document.page_count:
                        continue
                    pixmap = document.load_page(index).get_pixmap(dpi=144)
                    texts[index] = _ocr(pixmap.tobytes("png"), "image/png")
            finally:
                document.close()
        return ParsedDocument(
            pages=[
                ParsedPage(page_no=index + 1, text=text)
                for index, text in enumerate(texts)
            ]
        )


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


_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "footer",
    "form",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}
_SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe"}


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        text = " ".join(data.split())
        if text:
            self.parts.append(text)
            self.parts.append(" ")

    def text(self) -> str:
        raw = "".join(self.parts)
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


class HtmlDocumentParser:
    def parse(self, path: Path, mime: str) -> ParsedDocument:
        extractor = _HtmlTextExtractor()
        extractor.feed(path.read_text(encoding="utf-8", errors="replace"))
        extractor.close()
        return ParsedDocument(pages=[ParsedPage(page_no=None, text=extractor.text())])


class ImageDocumentParser:
    def parse(self, path: Path, mime: str) -> ParsedDocument:
        text = _ocr(path.read_bytes(), mime)
        return ParsedDocument(pages=[ParsedPage(page_no=1, text=text)])


class XlsxDocumentParser:
    def parse(self, path: Path, mime: str) -> ParsedDocument:
        from openpyxl import load_workbook

        workbook = load_workbook(filename=str(path), read_only=True, data_only=True)
        pages: list[ParsedPage] = []
        try:
            for index, sheet in enumerate(workbook.worksheets, start=1):
                rows: list[str] = []
                for row in sheet.iter_rows(values_only=True):
                    cells = [
                        str(cell).strip()
                        for cell in row
                        if cell is not None and str(cell).strip()
                    ]
                    if cells:
                        rows.append("\t".join(cells))
                text = "\n".join(rows).strip()
                if text:
                    pages.append(
                        ParsedPage(page_no=index, text=f"{sheet.title}\n{text}")
                    )
        finally:
            workbook.close()
        return ParsedDocument(pages=pages)


class PptxDocumentParser:
    def parse(self, path: Path, mime: str) -> ParsedDocument:
        from pptx import Presentation

        presentation = Presentation(str(path))
        pages: list[ParsedPage] = []
        for index, slide in enumerate(presentation.slides, start=1):
            parts: list[str] = []
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False):
                    for paragraph in shape.text_frame.paragraphs:
                        line = "".join(run.text for run in paragraph.runs).strip()
                        if line:
                            parts.append(line)
                if getattr(shape, "has_table", False):
                    for row in shape.table.rows:
                        cells = [
                            cell.text.strip()
                            for cell in row.cells
                            if cell.text.strip()
                        ]
                        if cells:
                            parts.append("\t".join(cells))
                if ocr_ready():
                    try:
                        image = shape.image
                    except (AttributeError, ValueError):
                        image = None
                    if image is not None:
                        parts.append(
                            _ocr(
                                image.blob,
                                getattr(image, "content_type", None) or "image/png",
                            )
                        )
            if parts:
                pages.append(ParsedPage(page_no=index, text="\n".join(parts)))
        return ParsedDocument(pages=pages)


_EXTENSION_MIME = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".csv": "text/csv",
    ".html": "text/html",
    ".htm": "text/html",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
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


def ocr_file_text(path: Path, mime: str) -> str:
    if mime not in IMAGE_MIMES:
        raise OcrParseError(
            "ocr_unsupported_format", f"OCR is not supported for {mime}"
        )
    return _ocr(path.read_bytes(), mime)


def ocr_pdf_pages(path: Path, page_numbers: list[int]) -> dict[int, str]:
    if not page_numbers:
        return {}
    import pymupdf

    document = pymupdf.open(str(path))
    try:
        results: dict[int, str] = {}
        for page_no in sorted(set(page_numbers)):
            index = page_no - 1
            if index < 0 or index >= document.page_count:
                raise OcrParseError(
                    "ocr_page_out_of_range", f"PDF page {page_no} is out of range"
                )
            pixmap = document.load_page(index).get_pixmap(dpi=144)
            results[page_no] = _ocr(pixmap.tobytes("png"), "image/png")
        return results
    finally:
        document.close()


def parser_for_mime(mime: str) -> DocumentParser:
    if mime == "application/pdf":
        return PdfDocumentParser()
    if mime in {"text/plain", "text/markdown"}:
        return TextDocumentParser()
    if mime == "text/csv":
        return CsvDocumentParser()
    if mime == "text/html":
        return HtmlDocumentParser()
    if mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return DocxDocumentParser()
    if mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        return XlsxDocumentParser()
    if mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
        return PptxDocumentParser()
    if mime in IMAGE_MIMES:
        if not ocr_ready():
            raise UnsupportedDocumentType(mime)
        return ImageDocumentParser()
    raise UnsupportedDocumentType(mime)
