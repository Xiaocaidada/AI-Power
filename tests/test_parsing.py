import pytest


def _imports():
    from app.services.parsing import (
        PdfDocumentParser,
        TextDocumentParser,
        UnsupportedDocumentType,
        detect_mime,
        parser_for_mime,
    )

    return (
        PdfDocumentParser,
        TextDocumentParser,
        UnsupportedDocumentType,
        detect_mime,
        parser_for_mime,
    )


def test_text_parser_reads_utf8(tmp_path):
    _Pdf, TextDocumentParser, _Unsupported, _detect, _parser = _imports()
    path = tmp_path / "note.md"
    path.write_text("# 标题\n\n正文", encoding="utf-8")

    parsed = TextDocumentParser().parse(path, "text/markdown")

    assert [page.text for page in parsed.pages] == ["# 标题\n\n正文"]
    assert parsed.pages[0].page_no is None


def test_parser_for_mime_dispatches_pdf_and_text():
    PdfDocumentParser, TextDocumentParser, _Unsupported, _detect, parser_for_mime = _imports()

    assert isinstance(parser_for_mime("application/pdf"), PdfDocumentParser)
    assert isinstance(parser_for_mime("text/plain"), TextDocumentParser)
    assert isinstance(parser_for_mime("text/markdown"), TextDocumentParser)


def test_parser_for_mime_rejects_unknown():
    _Pdf, _Text, UnsupportedDocumentType, _detect, parser_for_mime = _imports()

    with pytest.raises(UnsupportedDocumentType):
        parser_for_mime("image/png")


def test_detect_mime_by_extension():
    _Pdf, _Text, _Unsupported, detect_mime, _parser = _imports()

    assert detect_mime("a.PDF", None) == "application/pdf"
    assert detect_mime("a.md", None) == "text/markdown"
    assert detect_mime("a.txt", None) == "text/plain"


def test_detect_mime_rejects_unknown_extension_even_with_text_type():
    _Pdf, _Text, UnsupportedDocumentType, detect_mime, _parser = _imports()

    with pytest.raises(UnsupportedDocumentType):
        detect_mime("a.exe", "text/plain")
