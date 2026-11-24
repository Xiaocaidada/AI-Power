from sqlalchemy import select

from app.db import SessionLocal
from app.deps import get_scoped_registry
from app.main import app as app_instance
from app.models import UsageEvent
from app.providers.base import ChatChunk, Usage
from app.providers.registry import ProviderRegistry


async def _create_skill(client, headers, **overrides):
    return await client.post(
        "/skills",
        json={
            "name": "Summarizer",
            "description": "Summarize long text",
            "instructions": "Summarize the user's text.",
            "tool_names": ["calculator"],
            **overrides,
        },
        headers=headers,
    )


async def test_skill_crud_match_and_isolation(client, api):
    alice = await api.headers("p12-s10-skill-alice@example.com")
    bob = await api.headers("p12-s10-skill-bob@example.com")
    workspaces = await client.get("/workspaces", headers=alice)
    workspace_id = workspaces.json()[0]["id"]
    bob_me = await client.get("/auth/me", headers=bob)
    await client.post(
        f"/workspaces/{workspace_id}/members",
        json={"email": bob_me.json()["email"]},
        headers=alice,
    )
    bob = {**bob, "X-Workspace-Id": workspace_id}

    created = await _create_skill(client, alice)
    assert created.status_code == 201
    skill = created.json()
    assert skill["tool_names"] == ["calculator"]
    assert skill["owned"] is True

    duplicate = await _create_skill(client, alice)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "name_exists"

    listed = await client.get("/skills", headers=alice)
    assert len(listed.json()) == 1
    matched = await client.get("/skills/match?q=summar", headers=alice)
    assert matched.json()[0]["name"] == "Summarizer"

    assert (await client.get(f"/skills/{skill['id']}", headers=bob)).status_code == 404
    assert (
        await client.patch(
            f"/skills/{skill['id']}", json={"name": "Hijack"}, headers=bob
        )
    ).status_code == 404

    shared = await client.patch(
        f"/skills/{skill['id']}", json={"shared": True}, headers=alice
    )
    assert shared.status_code == 200
    bob_list = await client.get("/skills", headers=bob)
    assert len(bob_list.json()) == 1
    assert bob_list.json()[0]["owned"] is False

    removed = await client.delete(f"/skills/{skill['id']}", headers=alice)
    assert removed.status_code == 204
    assert (await client.get(f"/skills/{skill['id']}", headers=alice)).status_code == 404


async def test_skill_run_records_usage_and_history(
    client, api, registry, fake_provider
):
    headers = await api.headers("p12-s10-skill-run@example.com")
    app_instance.dependency_overrides[get_scoped_registry] = lambda: ProviderRegistry(
        {"fake": fake_provider}
    )
    try:
        created = await _create_skill(client, headers)
        skill_id = created.json()["id"]
        fake_provider.chunks = [
            ChatChunk(delta="Summary"),
            ChatChunk(usage=Usage(prompt_tokens=3, completion_tokens=2)),
            ChatChunk(finish_reason="stop"),
        ]

        run = await client.post(
            f"/skills/{skill_id}/run",
            json={"input": "long text", "provider_id": "fake", "model": "fake-model"},
            headers=headers,
        )
    finally:
        app_instance.dependency_overrides.pop(get_scoped_registry, None)

    assert run.status_code == 200
    body = run.json()
    assert body["status"] == "completed"
    assert body["output"] == "Summary"
    assert body["prompt_tokens"] == 3
    assert body["completion_tokens"] == 2

    runs = await client.get(f"/skills/{skill_id}/runs", headers=headers)
    assert len(runs.json()) == 1
    assert runs.json()[0]["id"] == body["id"]

    async with SessionLocal() as session:
        event = (
            await session.execute(
                select(UsageEvent).where(UsageEvent.source == "skill")
            )
        ).scalar_one()
        assert event.source_ref_id is not None


async def test_skill_run_requires_enabled_skill(client, api, registry, fake_provider):
    headers = await api.headers("p12-s10-skill-disabled@example.com")
    created = await _create_skill(client, headers, enabled=False)
    response = await client.post(
        f"/skills/{created.json()['id']}/run",
        json={"input": "text", "provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "skill_disabled"