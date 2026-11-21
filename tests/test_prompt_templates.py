import json

import pytest

from app.providers.base import ChatChunk, ModelInfo, Usage


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        event = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data = json.loads(
            next(line[len("data: ") :] for line in lines if line.startswith("data: "))
        )
        events.append((event, data))
    return events


class ScriptedProvider:
    id = "fake"

    def __init__(self) -> None:
        self.outputs: list[str] = []
        self.calls: list[list[object]] = []
        self.models = [ModelInfo(id="fake-model", provider_id="fake")]

    async def list_models(self):
        return list(self.models)

    async def stream_chat(self, messages, model, **_opts):
        self.calls.append(list(messages))
        output = (
            self.outputs.pop(0) if self.outputs else json.dumps({"action": "final", "answer": "ok"})
        )
        yield ChatChunk(delta=output)
        yield ChatChunk(usage=Usage(prompt_tokens=1, completion_tokens=1))
        yield ChatChunk(finish_reason="stop")


@pytest.fixture
def scripted():
    from app.deps import get_registry
    from app.main import app
    from app.providers.registry import ProviderRegistry

    script = ScriptedProvider()
    app.dependency_overrides[get_registry] = lambda: ProviderRegistry({"fake": script})
    yield script
    app.dependency_overrides.pop(get_registry, None)


async def _create_template(client, headers, system_prompt="You are {{tone}}."):
    return await client.post(
        "/prompt-templates",
        json={
            "name": "Support",
            "description": "Support replies",
            "system_prompt": system_prompt,
        },
        headers=headers,
    )


async def _create_conversation(client, headers, **extra):
    return await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model", **extra},
        headers=headers,
    )


async def _send(client, headers, conversation_id, content="hi"):
    return await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": content},
        headers=headers,
    )


async def test_create_template_extracts_variables_and_renders(client, api):
    headers = await api.headers("prompt-create@example.com")

    created = await _create_template(client, headers, "You are {{tone}}. Answer in {{language}}.")

    assert created.status_code == 201
    body = created.json()
    assert body["name"] == "Support"
    assert body["versions"][0]["version"] == 1
    assert body["versions"][0]["variables"] == ["tone", "language"]
    listed = await client.get("/prompt-templates", headers=headers)
    assert [item["id"] for item in listed.json()] == [body["id"]]

    rendered = await client.post(
        f"/prompt-templates/{body['id']}/render",
        json={"variables": {"tone": "concise", "language": "English"}},
        headers=headers,
    )

    assert rendered.status_code == 200
    assert rendered.json()["rendered"] == "You are concise. Answer in English."
    assert rendered.json()["version"] == 1


async def test_render_reports_missing_variables(client, api):
    headers = await api.headers("prompt-missing@example.com")
    template = (await _create_template(client, headers, "Tone: {{tone}} / {{language}}")).json()

    response = await client.post(
        f"/prompt-templates/{template['id']}/render",
        json={"variables": {"tone": "calm"}},
        headers=headers,
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "missing_variables"
    assert detail["missing"] == ["language"]


async def test_new_version_is_immutable_and_render_can_pick_one(client, api):
    headers = await api.headers("prompt-versions@example.com")
    template = (await _create_template(client, headers, "v1 {{tone}}")).json()
    template_id = template["id"]

    second = await client.post(
        f"/prompt-templates/{template_id}/versions",
        json={"system_prompt": "v2 {{tone}}"},
        headers=headers,
    )

    assert second.status_code == 201
    assert second.json()["version"] == 2
    detail = (await client.get(f"/prompt-templates/{template_id}", headers=headers)).json()
    assert [version["version"] for version in detail["versions"]] == [2, 1]
    first_render = await client.post(
        f"/prompt-templates/{template_id}/render",
        json={"version": 1, "variables": {"tone": "x"}},
        headers=headers,
    )
    latest_render = await client.post(
        f"/prompt-templates/{template_id}/render",
        json={"variables": {"tone": "x"}},
        headers=headers,
    )
    assert first_render.json()["rendered"] == "v1 x"
    assert latest_render.json()["rendered"] == "v2 x"


async def test_prompt_templates_are_workspace_scoped(client, api):
    alice = await api.headers("prompt-alice@example.com")
    bob = await api.headers("prompt-bob@example.com")
    template = (await _create_template(client, alice)).json()

    for response in (
        await client.get(f"/prompt-templates/{template['id']}", headers=bob),
        await client.post(
            f"/prompt-templates/{template['id']}/render",
            json={"variables": {"tone": "x"}},
            headers=bob,
        ),
        await client.delete(f"/prompt-templates/{template['id']}", headers=bob),
    ):
        assert response.status_code == 404


async def test_conversation_uses_rendered_prompt_and_reports_version(
    client, api, registry, fake_provider
):
    headers = await api.headers("prompt-conversation@example.com")
    template = (await _create_template(client, headers, "You are {{tone}}.")).json()
    version_id = template["versions"][0]["id"]

    created = await _create_conversation(
        client,
        headers,
        prompt_version_id=version_id,
        prompt_variables={"tone": "terse"},
    )

    assert created.status_code == 201
    assert created.json()["prompt_version_id"] == version_id
    response = await _send(client, headers, created.json()["id"])
    assert response.status_code == 200
    messages, _ = fake_provider.calls[-1]
    assert messages[0].role == "system"
    assert messages[0].content == "You are terse."
    detail = await client.get(f"/conversations/{created.json()['id']}", headers=headers)
    assert detail.json()["prompt_version_id"] == version_id


async def test_conversation_rejects_missing_prompt_variables(client, api, registry):
    headers = await api.headers("prompt-conv-missing@example.com")
    template = (await _create_template(client, headers, "Tone: {{tone}}")).json()

    response = await _create_conversation(
        client,
        headers,
        prompt_version_id=template["versions"][0]["id"],
        prompt_variables={},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "missing_variables"


async def test_agent_supervisor_uses_template(client, api, scripted):
    headers = await api.headers("prompt-agent@example.com")
    template = (await _create_template(client, headers, "You are {{tone}}.")).json()
    created = await _create_conversation(
        client,
        headers,
        agent=True,
        prompt_version_id=template["versions"][0]["id"],
        prompt_variables={"tone": "terse"},
    )

    await _send(client, headers, created.json()["id"])

    first_messages = scripted.calls[0]
    assert first_messages[0].content.startswith("You are terse.")
    assert "delegate_to_agent" in first_messages[0].content


async def test_deleting_template_keeps_existing_conversation(client, api, registry, fake_provider):
    headers = await api.headers("prompt-delete@example.com")
    template = (await _create_template(client, headers, "You are {{tone}}.")).json()
    created = await _create_conversation(
        client,
        headers,
        prompt_version_id=template["versions"][0]["id"],
        prompt_variables={"tone": "calm"},
    )
    await _send(client, headers, created.json()["id"])

    deleted = await client.delete(f"/prompt-templates/{template['id']}", headers=headers)
    listed = await client.get("/prompt-templates", headers=headers)
    fetched = await client.get(f"/prompt-templates/{template['id']}", headers=headers)

    assert deleted.status_code == 204
    assert listed.json() == []
    assert fetched.status_code == 404
    detail = await client.get(f"/conversations/{created.json()['id']}", headers=headers)
    assert detail.json()["prompt_version_id"] == template["versions"][0]["id"]
    again = await _send(client, headers, created.json()["id"], "again")
    assert again.status_code == 200
    messages, _ = fake_provider.calls[-1]
    assert messages[0].content == "You are calm."


async def test_rag_prompt_combines_template_with_references(
    client, api, registry, fake_provider, fake_ingestion, fake_retrieval
):
    headers = await api.headers("prompt-rag@example.com")
    kb = await client.post("/knowledge-bases", json={"name": "KB"}, headers=headers)
    await client.post(
        f"/knowledge-bases/{kb.json()['id']}/documents",
        files={"file": ("note.txt", b"hello world", "text/plain")},
        headers=headers,
    )
    template = (await _create_template(client, headers, "You are {{tone}}.")).json()
    created = await _create_conversation(
        client,
        headers,
        kb_id=kb.json()["id"],
        prompt_version_id=template["versions"][0]["id"],
        prompt_variables={"tone": "careful"},
    )

    await _send(client, headers, created.json()["id"])

    messages, _ = fake_provider.calls[-1]
    assert messages[0].content.startswith("You are careful.")
    assert "<reference_material>" in messages[0].content
    assert "hello world" in messages[0].content
