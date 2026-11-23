
from app.services.parsing import (
    HtmlDocumentParser,
    PptxDocumentParser,
    XlsxDocumentParser,
)
from app.services.url_import import FetchedUrl


def test_html_parser_extracts_visible_text(tmp_path):
    html = (
        "<html><head><title>T</title><style>.x{}</style></head>"
        "<body><h1>Hello</h1><p>alpha <b>beta</b></p>"
        "<script>alert('x')</script><ul><li>one</li><li>two</li></ul></body></html>"
    )
    path = tmp_path / "page.html"
    path.write_text(html, encoding="utf-8")

    parsed = HtmlDocumentParser().parse(path, "text/html")
    text = parsed.pages[0].text
    assert "Hello" in text
    assert "alpha beta" in text
    assert "one" in text and "two" in text
    assert "alert" not in text
    assert ".x{}" not in text


def test_xlsx_parser_reads_sheets(tmp_path):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Inventory"
    sheet.append(["name", "qty"])
    sheet.append(["apple", 3])
    path = tmp_path / "book.xlsx"
    workbook.save(path)

    parsed = XlsxDocumentParser().parse(
        path,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    assert parsed.pages
    assert "Inventory" in parsed.pages[0].text
    assert "apple" in parsed.pages[0].text


def test_pptx_parser_reads_slide_text(tmp_path):
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[6])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(2))
    box.text_frame.text = "Roadmap\nQ4 release"
    path = tmp_path / "deck.pptx"
    presentation.save(path)

    parsed = PptxDocumentParser().parse(
        path,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
    assert parsed.pages
    assert "Roadmap" in parsed.pages[0].text
    assert "Q4 release" in parsed.pages[0].text


async def test_url_import_creates_document_and_deduplicates(
    client, api, fake_ingestion, monkeypatch
):
    headers = await api.headers("p9-s5-url@example.com")
    kb = await client.post(
        "/knowledge-bases", json={"name": "URL KB"}, headers=headers
    )
    kb_id = kb.json()["id"]

    async def fake_fetch(url, **_kwargs):
        return FetchedUrl(
            content=b"<html><body>imported url text</body></html>",
            text="imported url text",
            mime="text/html",
            filename="example.com-page.html",
        )

    from app.routers import documents as documents_router

    monkeypatch.setattr(documents_router, "fetch_url_document", fake_fetch)

    created = await client.post(
        f"/knowledge-bases/{kb_id}/documents/import-url",
        json={
            "url": "https://example.com/page",
            "folder": "docs/web",
            "tags": ["web"],
        },
        headers=headers,
    )
    assert created.status_code == 202, created.text
    body = created.json()
    assert body["duplicate"] is False

    detail = await client.get(f"/documents/{body['id']}", headers=headers)
    assert detail.status_code == 200
    stored = detail.json()
    assert stored["status"] == "ready"
    assert stored["source_url"] == "https://example.com/page"
    assert stored["folder"] == "docs/web"
    assert stored["tags"] == ["web"]

    duplicate = await client.post(
        f"/knowledge-bases/{kb_id}/documents/import-url",
        json={"url": "https://example.com/page"},
        headers=headers,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["id"] == body["id"]


async def test_url_import_blocks_private_addresses(client, api, fake_ingestion):
    headers = await api.headers("p9-s5-block@example.com")
    kb = await client.post(
        "/knowledge-bases", json={"name": "Blocked KB"}, headers=headers
    )
    blocked = await client.post(
        f"/knowledge-bases/{kb.json()['id']}/documents/import-url",
        json={"url": "https://127.0.0.1/secret"},
        headers=headers,
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "invalid_url"


async def test_document_folder_metadata_and_filter(client, api, fake_ingestion):
    headers = await api.headers("p9-s5-folders@example.com")
    kb = await client.post(
        "/knowledge-bases", json={"name": "Folder KB"}, headers=headers
    )
    kb_id = kb.json()["id"]
    first = await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("one.txt", b"alpha beta", "text/plain")},
        headers=headers,
    )
    second = await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("two.txt", b"gamma delta", "text/plain")},
        headers=headers,
    )
    assert first.status_code == 202
    assert second.status_code == 202

    updated = await client.patch(
        f"/documents/{first.json()['id']}",
        json={
            "folder": "handbook/policies",
            "doc_metadata": {"owner": "HR", "year": "2026"},
            "tags": ["policy"],
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["folder"] == "handbook/policies"
    assert updated.json()["doc_metadata"] == {"owner": "HR", "year": "2026"}
    assert updated.json()["tags"] == ["policy"]

    only_folder = await client.get(
        f"/knowledge-bases/{kb_id}/documents?folder=handbook/policies",
        headers=headers,
    )
    assert only_folder.status_code == 200
    assert [row["id"] for row in only_folder.json()] == [first.json()["id"]]

    folders = await client.get(
        f"/knowledge-bases/{kb_id}/folders", headers=headers
    )
    assert folders.status_code == 200
    assert {"folder": "handbook/policies", "count": 1} in folders.json()
    assert {"folder": "", "count": 1} in folders.json()

    metadata_patch = await client.patch(
        f"/documents/{first.json()['id']}",
        json={"doc_metadata": {"owner": "Legal"}},
        headers=headers,
    )
    assert metadata_patch.status_code == 200
    assert metadata_patch.json()["doc_metadata"] == {"owner": "Legal"}
    assert metadata_patch.json()["folder"] == "handbook/policies"
    assert metadata_patch.json()["tags"] == ["policy"]