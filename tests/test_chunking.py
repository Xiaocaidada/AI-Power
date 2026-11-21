import pytest


def _imports():
    from app.services.chunking import chunk_pages
    from app.services.parsing import ParsedPage

    return chunk_pages, ParsedPage


def test_short_text_produces_single_chunk():
    chunk_pages, ParsedPage = _imports()

    chunks = chunk_pages([ParsedPage(page_no=1, text="hello world")], max_chars=100, overlap=10)

    assert [chunk.text for chunk in chunks] == ["hello world"]
    assert chunks[0].page_no == 1
    assert chunks[0].chunk_index == 0


def test_long_text_splits_with_overlap():
    chunk_pages, ParsedPage = _imports()

    chunks = chunk_pages([ParsedPage(page_no=None, text="a" * 250)], max_chars=100, overlap=20)

    assert [len(chunk.text) for chunk in chunks] == [100, 100, 90]
    assert chunks[1].text[:20] == chunks[0].text[-20:]


def test_page_numbers_are_preserved():
    chunk_pages, ParsedPage = _imports()

    chunks = chunk_pages(
        [
            ParsedPage(page_no=1, text="first page"),
            ParsedPage(page_no=2, text="second page"),
        ],
        max_chars=100,
        overlap=10,
    )

    assert [(chunk.page_no, chunk.text) for chunk in chunks] == [
        (1, "first page"),
        (2, "second page"),
    ]


def test_blank_pages_are_skipped():
    chunk_pages, ParsedPage = _imports()

    chunks = chunk_pages(
        [
            ParsedPage(page_no=1, text="   "),
            ParsedPage(page_no=2, text="content"),
        ],
        max_chars=100,
        overlap=10,
    )

    assert [chunk.text for chunk in chunks] == ["content"]


def test_chunk_index_increments_across_pages():
    chunk_pages, ParsedPage = _imports()

    chunks = chunk_pages(
        [
            ParsedPage(page_no=1, text="one"),
            ParsedPage(page_no=2, text="two"),
        ],
        max_chars=100,
        overlap=10,
    )

    assert [chunk.chunk_index for chunk in chunks] == [0, 1]


def test_overlap_must_be_smaller_than_max_chars():
    chunk_pages, ParsedPage = _imports()

    with pytest.raises(ValueError):
        chunk_pages([ParsedPage(page_no=1, text="x")], max_chars=10, overlap=10)
