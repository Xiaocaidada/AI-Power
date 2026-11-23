from app.config import get_settings


async def _memory(client, headers, **values):
    response = await client.post(
        "/memories",
        json={"content": values.pop("content"), **values},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _suggestion(payload, kind):
    return next(item for item in payload["suggestions"] if item["kind"] == kind)


async def test_duplicate_suggestion_apply_and_rollback(client, api):
    headers = await api.headers("p10s6-merge@example.com")
    first = await _memory(
        client,
        headers,
        title="Concise answers",
        content="Prefers concise answers for release notes.",
        category="preference",
    )
    second = await _memory(
        client,
        headers,
        title="Concise answers copy",
        content="Prefers concise answers for release updates.",
        category="preference",
    )
    analyzed = await client.post("/memories/quality/analyze", headers=headers)
    assert analyzed.status_code == 200, analyzed.text
    payload = analyzed.json()
    assert payload["analysis"]["duplicates"] >= 1
    suggestion = _suggestion(payload, "merge_duplicates")
    target_id = suggestion["payload"]["target_id"]
    source_ids = suggestion["payload"]["source_ids"]
    assert source_ids

    applied = await client.post(
        f"/memories/optimizations/{suggestion['id']}/apply", headers=headers
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "applied"
    target = await client.get(f"/memories/{target_id}", headers=headers)
    assert target.status_code == 200
    assert target.json()["status"] == "active"
    assert "release notes" in target.json()["content"]
    for source_id in source_ids:
        source = await client.get(f"/memories/{source_id}", headers=headers)
        assert source.json()["status"] == "archived"

    rolled = await client.post(
        f"/memories/optimizations/{suggestion['id']}/rollback", headers=headers
    )
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["status"] == "rolled_back"
    restored_first = await client.get(f"/memories/{first['id']}", headers=headers)
    restored_second = await client.get(f"/memories/{second['id']}", headers=headers)
    assert restored_first.json()["status"] == "active"
    assert restored_second.json()["status"] == "active"
    assert restored_first.json()["content"] == first["content"]
    assert restored_second.json()["content"] == second["content"]


async def test_conflict_and_expired_suggestions(client, api):
    headers = await api.headers("p10s6-quality@example.com")
    database = await _memory(
        client,
        headers,
        title="Database choice",
        content="The billing service uses PostgreSQL.",
        category="technical",
    )
    alternative = await _memory(
        client,
        headers,
        title="Database alternative",
        content="The billing service uses MySQL.",
        category="technical",
    )
    relation = await client.post(
        f"/memories/{database['id']}/relations",
        json={
            "to_type": "memory",
            "to_id": alternative["id"],
            "relation_type": "contradicts",
            "basis": "mutually exclusive database",
        },
        headers=headers,
    )
    assert relation.status_code == 200, relation.text
    expired_memory = await _memory(
        client,
        headers,
        title="Temporary plan",
        content="Temporary launch plan for the old quarter.",
        category="decision",
        valid_until="2020-01-01T00:00:00Z",
    )

    analyzed = await client.post("/memories/quality/analyze", headers=headers)
    assert analyzed.status_code == 200, analyzed.text
    payload = analyzed.json()
    assert payload["analysis"]["conflicts"] >= 1
    assert payload["analysis"]["expired"] >= 1

    conflict = _suggestion(payload, "resolve_conflict")
    applied = await client.post(
        f"/memories/optimizations/{conflict['id']}/apply", headers=headers
    )
    assert applied.status_code == 200, applied.text
    archived_id = conflict["payload"]["archive_id"]
    archived = await client.get(f"/memories/{archived_id}", headers=headers)
    assert archived.json()["status"] == "archived"

    expire = _suggestion(payload, "expire_memory")
    expired = await client.post(
        f"/memories/optimizations/{expire['id']}/apply", headers=headers
    )
    assert expired.status_code == 200, expired.text
    expired_row = await client.get(
        f"/memories/{expired_memory['id']}", headers=headers
    )
    assert expired_row.json()["status"] == "expired"


async def test_dismiss_suggestion_and_cross_user_isolation(client, api):
    owner = await api.headers("p10s6-owner@example.com")
    other = await api.headers("p10s6-other@example.com")
    await _memory(
        client,
        owner,
        title="Old preference",
        content="This preference expired long ago.",
        category="preference",
        valid_until="2020-01-01T00:00:00Z",
    )
    analyzed = await client.post("/memories/quality/analyze", headers=owner)
    suggestion = _suggestion(analyzed.json(), "expire_memory")

    denied = await client.post(
        f"/memories/optimizations/{suggestion['id']}/apply", headers=other
    )
    assert denied.status_code == 404, denied.text

    dismissed = await client.post(
        f"/memories/optimizations/{suggestion['id']}/dismiss", headers=owner
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["status"] == "dismissed"
    cannot_apply = await client.post(
        f"/memories/optimizations/{suggestion['id']}/apply", headers=owner
    )
    assert cannot_apply.status_code == 422, cannot_apply.text


async def test_memory_eval_cases_and_metrics(client, api):
    headers = await api.headers("p10s6-eval@example.com")
    first = await _memory(
        client,
        headers,
        title="Answer style",
        content="Prefers concise Chinese answers.",
        category="preference",
    )
    second = await _memory(
        client,
        headers,
        title="Billing database",
        content="The billing service uses PostgreSQL for storage.",
        category="technical",
    )
    await _memory(
        client,
        headers,
        title="Theme",
        content="Prefers dark mode for code review.",
        category="preference",
    )
    case = await client.post(
        "/memories/eval/cases",
        json={
            "name": "Style recall",
            "query": "concise Chinese answer style",
            "expected_memory_ids": [first["id"]],
            "notes": "top 5 should include answer style",
        },
        headers=headers,
    )
    assert case.status_code == 201, case.text
    case_id = case.json()["id"]
    second_case = await client.post(
        "/memories/eval/cases",
        json={
            "name": "Storage recall",
            "query": "billing storage database",
            "expected_memory_ids": [second["id"]],
        },
        headers=headers,
    )
    assert second_case.status_code == 201, second_case.text

    run = await client.post(
        "/memories/eval/run", json={"top_k": 5}, headers=headers
    )
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["status"] == "completed"
    assert body["cases_count"] == 2
    assert body["metrics"]["recall"] > 0
    assert body["metrics"]["mrr"] > 0
    assert len(body["results"]) == 2

    listed = await client.get("/memories/eval/runs", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == body["id"]

    deleted = await client.delete(
        f"/memories/eval/cases/{case_id}", headers=headers
    )
    assert deleted.status_code == 204
    other = await api.headers("p10s6-eval-other@example.com")
    denied = await client.delete(
        f"/memories/eval/cases/{second_case.json()['id']}", headers=other
    )
    assert denied.status_code == 404, denied.text


async def test_memory_quota_enforced(client, api, monkeypatch):
    headers = await api.headers("p10s6-quota@example.com")
    monkeypatch.setattr(get_settings(), "quota_free_max_memories", 1)
    first = await client.post(
        "/memories",
        json={"content": "First quota memory.", "title": "First"},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        "/memories",
        json={"content": "Second quota memory.", "title": "Second"},
        headers=headers,
    )
    assert second.status_code == 429, second.text
    assert second.json()["detail"]["code"] == "quota_exceeded"
    assert second.headers["X-Quota-Metric"] == "memories"