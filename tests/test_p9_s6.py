import pytest

from app.config import get_settings


@pytest.fixture
def quota_settings(monkeypatch):
    import app.services.quotas as quotas

    settings = get_settings().model_copy(deep=True)
    monkeypatch.setattr(quotas, "get_settings", lambda: settings)
    return settings


async def _kb(client, headers, name):
    response = await client.post(
        "/knowledge-bases", json={"name": name}, headers=headers
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_project_kb_links_are_inherited_by_conversations(
    client, api, fake_ingestion
):
    headers = await api.headers("p9-s6-project@example.com")
    first = await _kb(client, headers, "Project KB A")
    second = await _kb(client, headers, "Project KB B")

    created = await client.post(
        "/projects",
        json={
            "name": "Project with KBs",
            "default_provider_id": "auto",
            "default_model": "auto",
            "kb_ids": [first, second],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    project = created.json()
    assert project["kb_ids"] == [first, second]

    conversation = await client.post(
        "/conversations",
        json={"project_id": project["id"]},
        headers=headers,
    )
    assert conversation.status_code == 201, conversation.text
    detail = await client.get(
        f"/conversations/{conversation.json()['id']}", headers=headers
    )
    assert detail.status_code == 200, detail.text
    assert set(detail.json()["kb_ids"]) == {first, second}


async def test_knowledge_base_and_document_quotas(
    client, api, fake_ingestion, quota_settings
):
    headers = await api.headers("p9-s6-quota@example.com")
    quota_settings.quota_free_max_kbs = 1
    first = await _kb(client, headers, "Only KB")
    blocked_kb = await client.post(
        "/knowledge-bases", json={"name": "Blocked KB"}, headers=headers
    )
    assert blocked_kb.status_code == 429
    assert blocked_kb.json()["detail"]["metric"] == "knowledge_bases"

    quota_settings.quota_free_max_kbs = 10
    quota_settings.quota_free_max_documents_per_kb = 1
    accepted = await client.post(
        f"/knowledge-bases/{first}/documents",
        files={"file": ("one.txt", b"alpha", "text/plain")},
        headers=headers,
    )
    assert accepted.status_code == 202
    blocked_doc = await client.post(
        f"/knowledge-bases/{first}/documents",
        files={"file": ("two.txt", b"beta", "text/plain")},
        headers=headers,
    )
    assert blocked_doc.status_code == 429
    assert blocked_doc.json()["detail"]["metric"] == "documents"

    quota_settings.quota_free_max_documents_per_kb = 200
    quota_settings.quota_free_max_kb_bytes = 1
    blocked_bytes = await client.post(
        f"/knowledge-bases/{first}/documents",
        files={"file": ("three.txt", b"gamma", "text/plain")},
        headers=headers,
    )
    assert blocked_bytes.status_code == 429
    assert blocked_bytes.json()["detail"]["metric"] == "bytes"


async def test_quota_summary_reports_knowledge_usage(
    client, api, fake_ingestion, quota_settings
):
    headers = await api.headers("p9-s6-quota-summary@example.com")
    kb_id = await _kb(client, headers, "Summary KB")
    await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("summary.txt", b"alpha beta", "text/plain")},
        headers=headers,
    )
    response = await client.get("/usage/quota", headers=headers)
    assert response.status_code == 200, response.text
    knowledge = response.json()["knowledge"]
    assert knowledge["kb_count"] == 1
    assert knowledge["max_kbs"] == 10
    assert knowledge["kb_bytes"] >= 10
    assert knowledge["max_documents_per_kb"] == 200


async def test_knowledge_import_metrics_are_exposed(client, api, fake_ingestion):
    headers = await api.headers("p9-s6-metrics@example.com")
    kb_id = await _kb(client, headers, "Metrics KB")
    await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("metrics.txt", b"alpha beta", "text/plain")},
        headers=headers,
    )
    response = await client.get("/metrics")
    assert response.status_code == 200
    text = response.text
    assert "ai_power_knowledge_imports_total" in text
    assert 'kind="upload"' in text