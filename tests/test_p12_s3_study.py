import json


def _quiz_payload() -> str:
    return json.dumps(
        {
            "questions": [
                {
                    "type": "single_choice",
                    "prompt": "1 + 1 等于几？",
                    "options": [
                        {"id": "A", "text": "1"},
                        {"id": "B", "text": "2"},
                    ],
                    "answer": ["B"],
                    "explanation": "一加一等于二。",
                },
                {
                    "type": "short_answer",
                    "prompt": "水的化学式是什么？",
                    "answer": ["h2o", "H2O"],
                    "explanation": "水由两个氢原子和一个氧原子组成。",
                },
            ]
        },
        ensure_ascii=False,
    )


async def _conversation(client, headers):
    return await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )


async def _study(client, headers, conversation_id, **overrides):
    body = {
        "topic": "基础数学",
        "conversation_id": conversation_id,
        "level": "beginner",
        "mode": "guided",
        "goals": "掌握加法",
        **overrides,
    }
    return await client.post("/study/sessions", json=body, headers=headers)


async def test_create_and_get_study_session(client, api, registry):
    headers = await api.headers("p12-s3-create@example.com")
    conversation = await _conversation(client, headers)

    created = await _study(client, headers, conversation.json()["id"])

    assert created.status_code == 201
    body = created.json()
    assert body["topic"] == "基础数学"
    assert body["level"] == "beginner"
    assert body["mode"] == "guided"
    assert body["status"] == "active"
    detail = await client.get(f"/study/sessions/{body['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["attempts"] == []


async def test_study_session_cross_user_isolation(client, api, registry):
    alice = await api.headers("p12-s3-alice@example.com")
    bob = await api.headers("p12-s3-bob@example.com")
    conversation = await _conversation(client, alice)
    created = await _study(client, alice, conversation.json()["id"])

    response = await client.get(f"/study/sessions/{created.json()['id']}", headers=bob)
    listed = await client.get("/study/sessions", headers=bob)

    assert response.status_code == 404
    assert listed.json() == []


async def test_study_mode_requires_session(client, api, registry):
    headers = await api.headers("p12-s3-required@example.com")
    conversation = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model", "mode": "study"},
        headers=headers,
    )

    response = await client.post(
        f"/conversations/{conversation.json()['id']}/messages",
        json={"content": "解释加法"},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "study_session_required"


async def test_study_chat_injects_session_context(client, api, registry, fake_provider):
    headers = await api.headers("p12-s3-chat@example.com")
    conversation = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model", "mode": "study"},
        headers=headers,
    )
    study = await _study(client, headers, conversation.json()["id"])

    response = await client.post(
        f"/conversations/{conversation.json()['id']}/messages",
        json={
            "content": "解释一下",
            "mode_meta": {
                "thinking_level": "standard",
                "study_session_id": study.json()["id"],
            },
        },
        headers=headers,
    )

    assert response.status_code == 200
    system_message = fake_provider.calls[-1][0][0]
    assert system_message.role == "system"
    assert "基础数学" in system_message.content
    assert "beginner" in system_message.content
    detail = await client.get(f"/conversations/{conversation.json()['id']}", headers=headers)
    assert detail.json()["messages"][0]["mode"] == "study"
    assert detail.json()["messages"][0]["mode_meta"]["study_session_id"] == study.json()["id"]


async def test_quiz_generation_and_pending_questions_hide_answers(
    client, api, registry, fake_provider
):
    headers = await api.headers("p12-s3-quiz@example.com")
    conversation = await _conversation(client, headers)
    study = await _study(client, headers, conversation.json()["id"])
    fake_provider.complete_content = _quiz_payload()

    response = await client.post(
        f"/study/sessions/{study.json()['id']}/quiz",
        json={"count": 2},
        headers=headers,
    )

    assert response.status_code == 200
    attempts = response.json()["attempts"]
    assert len(attempts) == 2
    assert attempts[0]["status"] == "pending"
    assert attempts[0]["correct_answer"] is None
    assert attempts[0]["explanation"] is None
    assert "一加一等于二" not in response.text


async def test_quiz_grading_and_mastery(client, api, registry, fake_provider):
    headers = await api.headers("p12-s3-grade@example.com")
    conversation = await _conversation(client, headers)
    study = await _study(client, headers, conversation.json()["id"])
    fake_provider.complete_content = _quiz_payload()
    generated = await client.post(
        f"/study/sessions/{study.json()['id']}/quiz",
        json={"count": 2},
        headers=headers,
    )
    attempts = generated.json()["attempts"]

    wrong = await client.post(
        f"/study/sessions/{study.json()['id']}/attempts/{attempts[0]['id']}/answer",
        json={"answer": "A"},
        headers=headers,
    )
    assert wrong.status_code == 200
    assert wrong.json()["attempt"]["score"] == 0.0
    assert "正确答案" in wrong.json()["attempt"]["feedback"]
    assert wrong.json()["attempt"]["correct_answer"] == ["B"]
    assert wrong.json()["mastery"]["answered"] == 1
    assert wrong.json()["mastery"]["accuracy"] == 0.0

    correct = await client.post(
        f"/study/sessions/{study.json()['id']}/attempts/{attempts[1]['id']}/answer",
        json={"answer": "H2O"},
        headers=headers,
    )
    again = await client.post(
        f"/study/sessions/{study.json()['id']}/attempts/{attempts[1]['id']}/answer",
        json={"answer": "H2O"},
        headers=headers,
    )

    assert correct.status_code == 200
    assert correct.json()["attempt"]["score"] == 1.0
    assert correct.json()["mastery"]["answered"] == 2
    assert correct.json()["mastery"]["accuracy"] == 0.5
    assert correct.json()["mastery"]["suggestions"]
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "attempt_already_graded"


async def test_single_choice_accepts_case_insensitive_answer(client, api, registry, fake_provider):
    headers = await api.headers("p12-s3-choice@example.com")
    conversation = await _conversation(client, headers)
    study = await _study(client, headers, conversation.json()["id"])
    fake_provider.complete_content = _quiz_payload()
    generated = await client.post(
        f"/study/sessions/{study.json()['id']}/quiz",
        json={"count": 1},
        headers=headers,
    )
    attempt = generated.json()["attempts"][0]

    response = await client.post(
        f"/study/sessions/{study.json()['id']}/attempts/{attempt['id']}/answer",
        json={"answer": "B"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["attempt"]["score"] == 1.0
    assert response.json()["attempt"]["correct_answer"] == ["B"]


async def test_invalid_quiz_json_returns_502(client, api, registry, fake_provider):
    headers = await api.headers("p12-s3-bad-quiz@example.com")
    conversation = await _conversation(client, headers)
    study = await _study(client, headers, conversation.json()["id"])
    fake_provider.complete_content = "not json"

    response = await client.post(
        f"/study/sessions/{study.json()['id']}/quiz", json={}, headers=headers
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "quiz_generation_failed"


async def test_normal_chat_does_not_create_study_attempts(client, api, registry, fake_provider):
    headers = await api.headers("p12-s3-normal@example.com")
    conversation = await _conversation(client, headers)
    study = await _study(client, headers, conversation.json()["id"])

    await client.post(
        f"/conversations/{conversation.json()['id']}/messages",
        json={"content": "普通聊天"},
        headers=headers,
    )
    detail = await client.get(f"/study/sessions/{study.json()['id']}", headers=headers)

    assert detail.json()["attempts"] == []


async def test_study_mode_regenerates_with_same_session(client, api, registry, fake_provider):
    headers = await api.headers("p12-s3-regenerate@example.com")
    conversation = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model", "mode": "study"},
        headers=headers,
    )
    study = await _study(client, headers, conversation.json()["id"])
    sent = await client.post(
        f"/conversations/{conversation.json()['id']}/messages",
        json={
            "content": "解释",
            "mode_meta": {"study_session_id": study.json()["id"]},
        },
        headers=headers,
    )
    assert sent.status_code == 200
    detail = await client.get(f"/conversations/{conversation.json()['id']}", headers=headers)
    assistant = detail.json()["messages"][1]

    regenerated = await client.post(
        f"/conversations/{conversation.json()['id']}/messages/{assistant['id']}/regenerate",
        headers=headers,
    )

    assert regenerated.status_code == 200
    assert "基础数学" in fake_provider.calls[-1][0][0].content
