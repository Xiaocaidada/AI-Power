from uuid import UUID

from app.models import EvalRunItem
from app.services.evaluation_runner import compute_metrics


async def _agent(client, headers, *, attachments: bool) -> dict:
    response = await client.post(
        "/agents",
        json={
            "name": f"Attachments {attachments}",
            "description": "Attachment capability agent",
            "instructions": "Help with tasks.",
            "default_provider_id": "fake",
            "default_model": "fake-model",
            "tools": ["calculator"],
            "visibility": "private",
            "attachments_enabled": attachments,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_agent_attachment_capability_enforced(client, api, registry):
    headers = await api.headers("p11s12-attachments@example.com")
    disabled = await _agent(client, headers, attachments=False)
    conversation = await client.post(
        "/conversations",
        json={
            "custom_agent_id": disabled["id"],
            "provider_id": "fake",
            "model": "fake-model",
        },
        headers=headers,
    )
    assert conversation.status_code == 201, conversation.text
    conversation_id = conversation.json()["id"]

    rejected = await client.post(
        "/attachments",
        files={"file": ("note.txt", b"hello attachment", "text/plain")},
        data={"conversation_id": conversation_id},
        headers=headers,
    )
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "agent_attachments_disabled"

    enabled = await client.patch(
        f"/agents/{disabled['id']}",
        json={"attachments_enabled": True},
        headers=headers,
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["attachments_enabled"] is True

    accepted = await client.post(
        "/attachments",
        files={"file": ("note.txt", b"hello attachment", "text/plain")},
        data={"conversation_id": conversation_id},
        headers=headers,
    )
    assert accepted.status_code == 201, accepted.text

    image = await client.post(
        "/attachments",
        files={"file": ("shot.png", b"not-an-image", "image/png")},
        data={"conversation_id": conversation_id},
        headers=headers,
    )
    assert image.status_code == 422
    assert image.json()["detail"]["code"] == "image_agent_unsupported"


def test_citation_metrics_aggregate():
    items = [
        EvalRunItem(
            question_id=UUID(int=1),
            question_text="q1",
            reciprocal_rank=0.0,
            citation_precision=0.5,
            citation_recall=1.0,
            judge_score=5,
            judge_faithful=True,
        ),
        EvalRunItem(
            question_id=UUID(int=2),
            question_text="q2",
            reciprocal_rank=0.0,
            citation_precision=1.0,
            citation_recall=0.5,
            judge_score=3,
            judge_faithful=False,
        ),
    ]
    metrics = compute_metrics(items, answer_enabled=True, judge_enabled=True)
    assert metrics["citation_precision"] == 0.75
    assert metrics["citation_recall"] == 0.75
    assert metrics["citation_f1"] == 0.75
    assert metrics["faithful_rate"] == 0.5
    assert metrics["judge_avg_score"] == 4.0


async def test_memory_answer_evaluation_ab_metrics(client, api, registry):
    headers = await api.headers("p11s12-memory-eval@example.com")
    memory = await client.post(
        "/memories",
        json={
            "title": "Deployment platform",
            "content": "The service deploys on Kubernetes.",
            "category": "technical",
            "scope_type": "global",
        },
        headers=headers,
    )
    assert memory.status_code == 201, memory.text
    case = await client.post(
        "/memories/eval/cases",
        json={
            "name": "Deployment",
            "query": "Where does the service deploy?",
            "expected_memory_ids": [memory.json()["id"]],
        },
        headers=headers,
    )
    assert case.status_code == 201, case.text

    provider = registry.get("fake")
    provider.complete_contents = [
        "The service deploys on Kubernetes.",
        "I don't know.",
        '{"score": 5, "faithful": true, "reason": "supported"}',
        '{"score": 2, "faithful": true, "reason": "unhelpful"}',
    ]
    response = await client.post(
        "/memories/eval/run",
        json={
            "top_k": 5,
            "generate_answers": True,
            "provider_id": "fake",
            "model": "fake-model",
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["metrics"]["generate_answers"] is True
    assert body["metrics"]["answer_score_with_memory"] == 5.0
    assert body["metrics"]["answer_score_without_memory"] == 2.0
    assert body["metrics"]["answer_lift"] == 3.0
    assert body["metrics"]["faithful_rate_with_memory"] == 1.0
    result = body["results"][0]
    assert result["answer_with_memory"] == "The service deploys on Kubernetes."
    assert result["answer_without"] == "I don't know."
    assert result["score_with_memory"] == 5
    assert result["score_without_memory"] == 2
    assert result["answer_lift"] == 3