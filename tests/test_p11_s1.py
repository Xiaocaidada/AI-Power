def _definition(label: str) -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {
                "id": "say",
                "type": "llm",
                "config": {
                    "provider_id": "fake",
                    "model": "fake-model",
                    "prompt": label,
                },
            },
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": "say"},
            {"from": "say", "to": "out"},
        ],
    }


async def _workflow(client, headers, label: str) -> dict:
    response = await client.post(
        "/workflows",
        json={"name": f"Canvas {label}", "description": "p11 s1", "definition": _definition(label)},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_workflow_draft_autosave_and_clear(client, api):
    headers = await api.headers("p11s1-draft@example.com")
    workflow = await _workflow(client, headers, "first prompt")
    workflow_id = workflow["id"]

    draft_definition = _definition("draft prompt")
    saved = await client.put(
        f"/workflows/{workflow_id}/draft",
        json={"definition": draft_definition},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["definition"]["nodes"][1]["config"]["prompt"] == "draft prompt"
    assert saved.json()["saved_at"] is not None

    fetched = await client.get(f"/workflows/{workflow_id}", headers=headers)
    assert fetched.status_code == 200
    payload = fetched.json()
    assert payload["draft_definition"]["nodes"][1]["config"]["prompt"] == "draft prompt"
    assert payload["draft_saved_at"] is not None

    draft_only = await client.get(
        f"/workflows/{workflow_id}/draft", headers=headers
    )
    assert draft_only.status_code == 200
    assert draft_only.json()["definition"]["nodes"][1]["config"]["prompt"] == "draft prompt"

    version = await client.post(
        f"/workflows/{workflow_id}/versions",
        json={"definition": _definition("saved prompt")},
        headers=headers,
    )
    assert version.status_code == 201, version.text
    after_save = await client.get(f"/workflows/{workflow_id}", headers=headers)
    assert after_save.json()["draft_definition"] is None
    assert after_save.json()["draft_saved_at"] is None

    recreated = await client.put(
        f"/workflows/{workflow_id}/draft",
        json={"definition": _definition("another draft")},
        headers=headers,
    )
    assert recreated.status_code == 200
    cleared = await client.delete(f"/workflows/{workflow_id}/draft", headers=headers)
    assert cleared.status_code == 204
    empty = await client.get(f"/workflows/{workflow_id}/draft", headers=headers)
    assert empty.json()["definition"] is None


async def test_workflow_invalid_draft_rejected(client, api):
    headers = await api.headers("p11s1-invalid@example.com")
    workflow = await _workflow(client, headers, "valid")
    invalid = await client.put(
        f"/workflows/{workflow['id']}/draft",
        json={"definition": {"nodes": "not-a-list", "edges": []}},
        headers=headers,
    )
    assert invalid.status_code == 422, invalid.text
    assert invalid.json()["detail"]["code"] == "invalid_draft"


async def test_workflow_version_list_and_restore(client, api):
    headers = await api.headers("p11s1-restore@example.com")
    workflow = await _workflow(client, headers, "version one")
    workflow_id = workflow["id"]
    second = await client.post(
        f"/workflows/{workflow_id}/versions",
        json={"definition": _definition("version two")},
        headers=headers,
    )
    assert second.status_code == 201, second.text
    versions = await client.get(f"/workflows/{workflow_id}/versions", headers=headers)
    assert versions.status_code == 200
    numbers = [item["version"] for item in versions.json()]
    assert numbers == [2, 1]

    restored = await client.post(
        f"/workflows/{workflow_id}/versions/1/restore", headers=headers
    )
    assert restored.status_code == 201, restored.text
    assert restored.json()["version"] == 3
    assert (
        restored.json()["definition"]["nodes"][1]["config"]["prompt"]
        == "version one"
    )
    latest = await client.get(f"/workflows/{workflow_id}", headers=headers)
    assert latest.json()["versions"][0]["version"] == 3
    assert latest.json()["draft_definition"] is None

    missing = await client.post(
        f"/workflows/{workflow_id}/versions/99/restore", headers=headers
    )
    assert missing.status_code == 404


async def test_workflow_draft_and_versions_are_workspace_scoped(client, api):
    owner = await api.headers("p11s1-owner@example.com")
    other = await api.headers("p11s1-other@example.com")
    workflow = await _workflow(client, owner, "private")
    workflow_id = workflow["id"]
    draft = await client.get(f"/workflows/{workflow_id}/draft", headers=other)
    assert draft.status_code == 404
    save = await client.put(
        f"/workflows/{workflow_id}/draft",
        json={"definition": _definition("intruder")},
        headers=other,
    )
    assert save.status_code == 404
    versions = await client.get(
        f"/workflows/{workflow_id}/versions", headers=other
    )
    assert versions.status_code == 404
    restore = await client.post(
        f"/workflows/{workflow_id}/versions/1/restore", headers=other
    )
    assert restore.status_code == 404