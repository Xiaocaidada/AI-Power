import json

from sqlalchemy import select


async def _make_admin(email: str) -> None:
    from app.db import SessionLocal
    from app.models import User

    async with SessionLocal() as session:
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one()
        user.role = "admin"
        await session.commit()


def _events(text: str) -> list[tuple[str, dict]]:
    result: list[tuple[str, dict]] = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        event = next(
            (line[len("event: ") :] for line in lines if line.startswith("event: ")),
            "message",
        )
        data = next(
            (line[len("data: ") :] for line in lines if line.startswith("data: ")),
            "{}",
        )
        result.append((event, json.loads(data)))
    return result


async def test_arena_blind_parallel_and_reveal(client, api, registry):
    headers = await api.headers("p7-arena@example.com")
    created = await client.post(
        "/arena/rounds",
        json={
            "prompt": "Explain vectors",
            "blind": True,
            "models": [
                {"provider_id": "fake", "model": "fake-model"},
                {"provider_id": "fake", "model": "second-model"},
            ],
        },
        headers=headers,
    )
    assert created.status_code == 201
    round_id = created.json()["id"]
    responses = created.json()["responses"]
    assert len(responses) == 2
    assert all(item["provider_id"] is None for item in responses)
    assert [item["label"] for item in responses] == ["A", "B"]

    for item in responses:
        stream = await client.post(
            f"/arena/rounds/{round_id}/responses/{item['id']}/stream",
            headers=headers,
        )
        events = _events(stream.text)
        assert events[0][0] == "meta"
        assert "provider_id" not in events[0][1]
        assert any(event == "done" for event, _ in events)

    revealed = await client.post(f"/arena/rounds/{round_id}/reveal", headers=headers)
    assert revealed.status_code == 200
    assert all(item["model"] is not None for item in revealed.json()["responses"])

    voted = await client.post(
        f"/arena/rounds/{round_id}/vote",
        json={"response_id": responses[0]["id"], "reason": "clearer"},
        headers=headers,
    )
    assert voted.status_code == 200
    assert voted.json()["vote_response_id"] == responses[0]["id"]

    feedback = await client.put(
        f"/arena/rounds/{round_id}/responses/{responses[0]['id']}/feedback",
        json={"feedback": "helpful"},
        headers=headers,
    )
    assert feedback.status_code == 200
    assert feedback.json()["feedback"] == "helpful"

    detail = await client.get(f"/arena/rounds/{round_id}", headers=headers)
    by_id = {item["id"]: item for item in detail.json()["responses"]}
    assert by_id[responses[0]["id"]]["feedback"] == "helpful"
    assert by_id[responses[1]["id"]]["feedback"] is None

    other = await api.headers("p7-arena-other@example.com")
    denied = await client.put(
        f"/arena/rounds/{round_id}/responses/{responses[0]['id']}/feedback",
        json={"feedback": "unhelpful"},
        headers=other,
    )
    assert denied.status_code == 404

    usage = await client.get("/usage/recent", headers=headers)
    assert any(item["source"] == "arena" for item in usage.json())


async def test_prompt_lab_snapshot_and_stream(client, api, registry):
    headers = await api.headers("p7-prompt@example.com")
    template = await client.post(
        "/prompt-templates",
        json={
            "name": "Rewrite",
            "system_prompt": "You edit text.",
            "user_prompt": "Rewrite: {{text}}",
        },
        headers=headers,
    )
    assert template.status_code == 201
    template_id = template.json()["id"]

    experiment = await client.post(
        "/prompt-lab/experiments",
        json={
            "template_id": template_id,
            "variables": {"text": "hello world"},
            "models": [{"provider_id": "fake", "model": "fake-model"}],
        },
        headers=headers,
    )
    assert experiment.status_code == 201
    payload = experiment.json()
    assert payload["user_prompt"] == "Rewrite: hello world"
    output_id = payload["outputs"][0]["id"]

    stream = await client.post(
        f"/prompt-lab/experiments/{payload['id']}/outputs/{output_id}/stream",
        headers=headers,
    )
    events = _events(stream.text)
    assert any(event == "delta" for event, _ in events)
    assert any(event == "done" for event, _ in events)

    history = await client.get("/prompt-lab/experiments", headers=headers)
    assert history.status_code == 200
    assert history.json()[0]["system_prompt"] == "You edit text."

    version = await client.post(
        f"/prompt-templates/{template_id}/versions",
        json={
            "system_prompt": "You edit text.\nBe concise.",
            "user_prompt": "Rewrite: {{text}}",
        },
        headers=headers,
    )
    assert version.status_code == 201
    diff = await client.get(
        f"/prompt-templates/{template_id}/diff?from_version=1&to_version=2",
        headers=headers,
    )
    assert diff.status_code == 200
    payload = diff.json()
    assert payload["from_version"] == 1
    assert payload["to_version"] == 2
    assert any(line["type"] == "insert" for line in payload["system"])
    assert any(line["type"] == "equal" for line in payload["user"])


async def test_platform_prompt_admin_crud(client, api):
    admin = await api.headers("p7-admin-prompt@example.com")
    await _make_admin("p7-admin-prompt@example.com")
    user = await api.headers("p7-prompt-reader@example.com")

    created = await client.post(
        "/admin/prompt-templates",
        json={
            "name": "Platform rewrite",
            "description": "Shared template",
            "category": "writing",
            "system_prompt": "Rewrite clearly.",
        },
        headers=admin,
    )
    assert created.status_code == 201
    template_id = created.json()["id"]
    assert created.json()["scope"] == "platform"

    assert (
        await client.get("/admin/prompt-templates", headers=user)
    ).status_code == 404
    listing = await client.get("/admin/prompt-templates", headers=admin)
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [template_id]

    updated = await client.patch(
        f"/admin/prompt-templates/{template_id}",
        json={"name": "Platform rewrite v2"},
        headers=admin,
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Platform rewrite v2"

    version = await client.post(
        f"/admin/prompt-templates/{template_id}/versions",
        json={"system_prompt": "Rewrite clearly and concisely."},
        headers=admin,
    )
    assert version.status_code == 201
    assert version.json()["version"] == 2

    visible = await client.get(f"/prompt-templates/{template_id}", headers=user)
    assert visible.status_code == 200
    assert visible.json()["scope"] == "platform"

    logs = await client.get("/admin/audit-logs", headers=admin)
    assert any(
        item["action"] == "prompt.platform_create" for item in logs.json()
    )

    deleted = await client.delete(
        f"/admin/prompt-templates/{template_id}", headers=admin
    )
    assert deleted.status_code == 204
    assert (
        await client.get(f"/prompt-templates/{template_id}", headers=user)
    ).status_code == 404


async def test_model_eval_rule_manual_and_metrics(client, api, registry):
    headers = await api.headers("p7-modeleval@example.com")
    dataset = await client.post(
        "/model-eval/datasets",
        json={
            "name": "Smoke",
            "questions": [
                {
                    "question": "Say hello",
                    "expected_keywords": ["hello"],
                }
            ],
        },
        headers=headers,
    )
    assert dataset.status_code == 201
    dataset_id = dataset.json()["id"]
    question_id = dataset.json()["questions"][0]["id"]

    run = await client.post(
        "/model-eval/runs",
        json={
            "dataset_id": dataset_id,
            "models": [
                {"provider_id": "fake", "model": "fake-model"},
                {"provider_id": "fake", "model": "second-model"},
            ],
            "concurrency": 1,
            "methods": ["rule", "ai"],
            "judge_provider_id": "fake",
            "judge_model": "fake-model",
        },
        headers=headers,
    )
    assert run.status_code == 202
    run_id = run.json()["id"]

    detail = await client.get(f"/model-eval/runs/{run_id}", headers=headers)
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["status"] == "completed"
    assert payload["progress_done"] == 2, payload
    assert payload["metrics"]["models"]
    assert all(item["scores"] for item in payload["items"])
    model_metrics = next(iter(payload["metrics"]["models"].values()))
    assert model_metrics["ai_scored"] == 0
    assert model_metrics["ai_unscored"] == 1
    ai_scores = [
        score
        for item in payload["items"]
        for score in item["scores"]
        if score["method"] == "ai"
    ]
    assert ai_scores
    assert all("judge" in score["reason"] for score in ai_scores)
    assert all(item["status"] == "completed" for item in payload["items"])
    assert len(registry.get("fake").complete_calls) == 4

    item_id = payload["items"][0]["id"]
    score = await client.post(
        f"/model-eval/items/{item_id}/scores",
        json={"score": 5, "reason": "good"},
        headers=headers,
    )
    assert score.status_code == 200
    assert score.json()["method"] == "manual"

    updated = await client.patch(
        f"/model-eval/questions/{question_id}",
        json={
            "question": "Say hello again",
            "reference_answer": "hello",
            "expected_keywords": ["hello"],
        },
        headers=headers,
    )
    assert updated.status_code == 200
    assert updated.json()["question"] == "Say hello again"

    blocked = await client.delete(
        f"/model-eval/questions/{question_id}", headers=headers
    )
    assert blocked.status_code == 409

    assert (
        await client.delete(f"/model-eval/runs/{run_id}", headers=headers)
    ).status_code == 204
    assert (
        await client.get(f"/model-eval/runs/{run_id}", headers=headers)
    ).status_code == 404
    assert (
        await client.delete(f"/model-eval/questions/{question_id}", headers=headers)
    ).status_code == 204

    other = await api.headers("p7-modeleval-other@example.com")
    assert (
        await client.patch(
            f"/model-eval/questions/{question_id}",
            json={"question": "nope"},
            headers=other,
        )
    ).status_code == 404