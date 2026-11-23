import httpx
import pytest

from app.config import get_settings
from app.services import parsing, url_import


async def test_url_import_follows_validated_redirects(monkeypatch):
    settings = get_settings().model_copy(update={"url_import_max_redirects": 2})
    validated: list[str] = []

    async def fake_validate(url, _settings=None):
        validated.append(url)

    monkeypatch.setattr(url_import, "validate_outbound_url", fake_validate)

    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/final"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<p>redirected</p>",
        )

    fetched = await url_import.fetch_url_document(
        "https://example.com/start",
        settings=settings,
        transport=httpx.MockTransport(handler),
    )
    assert "redirected" in fetched.text
    assert fetched.url == "https://example.com/final"
    assert validated == [
        "https://example.com/start",
        "https://example.com/final",
    ]


async def test_url_import_rejects_excessive_redirects(monkeypatch):
    settings = get_settings().model_copy(update={"url_import_max_redirects": 1})

    async def fake_validate(url, _settings=None):
        return None

    monkeypatch.setattr(url_import, "validate_outbound_url", fake_validate)

    def handler(request):
        return httpx.Response(302, headers={"location": "/again"})

    with pytest.raises(url_import.UrlImportError) as excinfo:
        await url_import.fetch_url_document(
            "https://example.com/start",
            settings=settings,
            transport=httpx.MockTransport(handler),
        )
    assert excinfo.value.code == "too_many_redirects"


def test_extract_links_normalizes_and_filters():
    links = url_import.extract_links(
        '<a href="/a">A</a><a href="https://other.com/b#x">B</a>'
        '<a href="#top">skip</a><a href="mailto:x@y.z">skip</a>',
        "https://example.com/root",
    )
    assert links == ["https://example.com/a", "https://other.com/b"]


async def test_crawl_site_is_bounded_and_same_origin(monkeypatch):
    def page(url, html):
        return url_import.FetchedUrl(
            content=html.encode(),
            text=html,
            mime="text/html",
            filename="page.html",
            url=url,
        )

    start = "https://example.com/start"
    pages = {
        start: page(start, '<a href="/child">c</a><a href="https://other.com/x">x</a>'),
        "https://example.com/child": page(
            "https://example.com/child", '<a href="/third">t</a>'
        ),
        "https://example.com/third": page("https://example.com/third", "<p>third</p>"),
    }

    async def fake_fetch(url, **_kwargs):
        return pages[url]

    monkeypatch.setattr(url_import, "fetch_url_document", fake_fetch)
    outcome = await url_import.crawl_site(start, max_pages=2, same_origin=True)
    assert [item.url for item in outcome.pages] == [
        start,
        "https://example.com/child",
    ]
    assert outcome.failures == []


def test_image_and_pptx_ocr_use_configured_ocr(monkeypatch, tmp_path):
    monkeypatch.setattr(parsing, "ocr_ready", lambda: True)
    monkeypatch.setattr(parsing, "ocr_image", lambda data, mime: "recognized text")

    image_path = tmp_path / "scan.png"
    image_path.write_bytes(b"not-a-real-image")
    parsed = parsing.ImageDocumentParser().parse(image_path, "image/png")
    assert parsed.pages[0].text == "recognized text"

    from PIL import Image
    from pptx import Presentation
    from pptx.util import Inches

    png_path = tmp_path / "slide.png"
    Image.new("RGB", (20, 20), "white").save(png_path)
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    slide.shapes.add_picture(str(png_path), Inches(1), Inches(1))
    deck = tmp_path / "deck.pptx"
    presentation.save(deck)
    parsed = parsing.PptxDocumentParser().parse(
        deck,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
    assert any("recognized text" in item.text for item in parsed.pages)


async def test_metadata_filter_limits_retrieval(
    client, api, fake_ingestion, fake_retrieval
):
    headers = await api.headers("p9-s5-metadata@example.com")
    kb = await client.post(
        "/knowledge-bases", json={"name": "Metadata KB"}, headers=headers
    )
    kb_id = kb.json()["id"]
    first = await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("first.txt", b"alpha beta", "text/plain")},
        headers=headers,
    )
    second = await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("second.txt", b"gamma delta", "text/plain")},
        headers=headers,
    )
    assert first.status_code == 202
    assert second.status_code == 202
    await client.patch(
        f"/documents/{first.json()['id']}",
        json={"doc_metadata": {"team": "a"}},
        headers=headers,
    )
    await client.patch(
        f"/documents/{second.json()['id']}",
        json={"doc_metadata": {"team": "b"}},
        headers=headers,
    )
    updated = await client.patch(
        f"/knowledge-bases/{kb_id}/settings",
        json={"retrieval": {"metadata_filter": {"team": "a"}}},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["retrieval"]["metadata_filter"] == {"team": "a"}

    searched = await client.post(
        f"/knowledge-bases/{kb_id}/retrieval/search",
        json={"query": "alpha", "top_k": 5},
        headers=headers,
    )
    assert searched.status_code == 200, searched.text
    assert {hit["document_id"] for hit in searched.json()["results"]} == {
        first.json()["id"]
    }

    await client.patch(
        f"/knowledge-bases/{kb_id}/settings",
        json={"retrieval": {"metadata_filter": {}}},
        headers=headers,
    )
    unfiltered = await client.post(
        f"/knowledge-bases/{kb_id}/retrieval/search",
        json={"query": "alpha", "top_k": 5},
        headers=headers,
    )
    assert {hit["document_id"] for hit in unfiltered.json()["results"]} == {
        first.json()["id"],
        second.json()["id"],
    }


async def test_folder_rename_moves_nested_documents(client, api, fake_ingestion):
    headers = await api.headers("p9-s5-rename@example.com")
    kb = await client.post(
        "/knowledge-bases", json={"name": "Rename KB"}, headers=headers
    )
    kb_id = kb.json()["id"]
    first = await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("one.txt", b"one", "text/plain")},
        headers=headers,
    )
    second = await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("two.txt", b"two", "text/plain")},
        headers=headers,
    )
    await client.patch(
        f"/documents/{first.json()['id']}",
        json={"folder": "a/b"},
        headers=headers,
    )
    await client.patch(
        f"/documents/{second.json()['id']}",
        json={"folder": "a/c"},
        headers=headers,
    )

    renamed = await client.post(
        f"/knowledge-bases/{kb_id}/folders/rename",
        json={"from_folder": "a", "to_folder": "z"},
        headers=headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["updated"] == 2
    first_detail = await client.get(
        f"/documents/{first.json()['id']}", headers=headers
    )
    second_detail = await client.get(
        f"/documents/{second.json()['id']}", headers=headers
    )
    assert first_detail.json()["folder"] == "z/b"
    assert second_detail.json()["folder"] == "z/c"

    invalid = await client.post(
        f"/knowledge-bases/{kb_id}/folders/rename",
        json={"from_folder": "z", "to_folder": "z/inside"},
        headers=headers,
    )
    assert invalid.status_code == 422