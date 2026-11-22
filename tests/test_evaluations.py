from uuid import UUID, uuid4

import pytest

from app.db import SessionLocal
from app.models import (
    Chunk,
    ChunkEmbedding,
    Document,
    EvalRunItem,
    Workspace,
    WorkspaceMember,
)


def _vector(position: int) -> list[float]:
    vector = [0.0] * 1024
    vector[position] = 1.0
    return vector


async def _setup(client, api, email: str):
    headers = await api.headers(email)
    me = await client.get("/auth/me", headers=headers)
    user_id = UUID(me.json()["id"])
    async with SessionLocal() as session:
        workspace = (
            await session.execute(
                Workspace.__table__.select()
                .join(
                    WorkspaceMember.__table__,
                    WorkspaceMember.__table__.c.workspace_id == Workspace.__table__.c.id,
                )
                .where(
                    WorkspaceMember.__table__.c.user_id == user_id,
                    Workspace.__table__.c.is_personal.is_(True),
                )
            )
        ).first()
    assert workspace is not None
    response = await client.post("/knowledge-bases", json={"name": "Eval KB"}, headers=headers)
    assert response.status_code == 201
    return headers, user_id, UUID(str(workspace.id)), UUID(response.json()["id"])


async def _seed_document(
    *,
    workspace_id: UUID,
    kb_id: UUID,
    user_id: UUID,
    filename: str,
    text: str,
    vector: list[float],
    status: str = "ready",
) -> UUID:
    async with SessionLocal() as session:
        document = Document(
            workspace_id=workspace_id,
            kb_id=kb_id,
            user_id=user_id,
            filename=filename,
            mime="text/plain",
            size_bytes=len(text.encode("utf-8")),
            content_hash=uuid4().hex,
            storage_path=filename,
            status=status,
        )
        session.add(document)
        await session.flush()
        chunk = Chunk(
            workspace_id=workspace_id,
            document_id=document.id,
            user_id=user_id,
            kb_id=kb_id,
            page_no=1,
            chunk_index=0,
            text=text,
        )
        session.add(chunk)
        await session.flush()
        session.add(ChunkEmbedding(chunk_id=chunk.id, embedding=vector))
        await session.commit()
        return document.id


async def _create_dataset(client, headers, kb_id: UUID, document_ids: list[UUID], count: int = 1):
    response = await client.post(
        "/evaluations/datasets",
        json={
            "name": f"Dataset {uuid4().hex[:6]}",
            "description": "test set",
            "questions": [
                {
                    "question": f"question {index}",
                    "relevant_document_ids": [str(document_ids[index % len(document_ids)])],
                    "evidence": [],
                }
                for index in range(count)
            ],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _run(client, headers, dataset_id: str, kb_id: UUID, **overrides):
    payload = {
        "dataset_id": dataset_id,
        "kb_id": str(kb_id),
        "top_k": 1,
        "candidate_k": 5,
        "hybrid_enabled": True,
        "rerank_enabled": False,
        **overrides,
    }
    response = await client.post("/evaluations/runs", json=payload, headers=headers)
    assert response.status_code == 202, response.text
    return response.json()


async def test_retrieval_evaluation_persists_metrics_and_items(
    client, api, fake_retrieval, monkeypatch
):
    from app.services import evaluation_runner

    monkeypatch.setattr(evaluation_runner, "build_embedder", lambda: fake_retrieval)
    headers, user_id, workspace_id, kb_id = await _setup(client, api, "eval-retrieval@example.com")
    alpha = await _seed_document(
        workspace_id=workspace_id,
        kb_id=kb_id,
        user_id=user_id,
        filename="alpha.txt",
        text="alpha answer",
        vector=_vector(0),
    )
    await _seed_document(
        workspace_id=workspace_id,
        kb_id=kb_id,
        user_id=user_id,
        filename="beta.txt",
        text="beta answer",
        vector=_vector(1),
    )
    gamma = await _seed_document(
        workspace_id=workspace_id,
        kb_id=kb_id,
        user_id=user_id,
        filename="gamma.txt",
        text="gamma answer",
        vector=_vector(2),
    )
    fake_retrieval.mapping = {"alpha": 0}
    dataset = await _create_dataset(client, headers, kb_id, [alpha, gamma], count=2)
    # Both questions ask for "alpha": alpha is rank 1, gamma is a miss at top_k=1.
    from app.models import EvalQuestion

    async with SessionLocal() as session:
        await session.execute(
            EvalQuestion.__table__.update()
            .where(EvalQuestion.__table__.c.dataset_id == UUID(dataset["id"]))
            .values(question="alpha")
        )
        await session.commit()

    run = await _run(client, headers, dataset["id"], kb_id)

    assert run["status"] == "completed", run
    detail = await client.get(f"/evaluations/runs/{run['id']}", headers=headers)
    assert detail.status_code == 200
    body = detail.json()
    assert body["progress_done"] == 2
    assert body["metrics"]["total"] == 2
    assert body["metrics"]["recall_at_1"] == 0.5
    assert body["metrics"]["mrr"] == 0.5
    assert len(body["items"]) == 2
    assert body["items"][0]["hit_rank"] == 1
    assert body["items"][1]["hit_rank"] is None
    assert body["items"][0]["top_document_ids"]


async def test_evaluation_supports_llm_as_judge(client, api, fake_retrieval, monkeypatch):
    from app.deps import get_registry
    from app.main import app as app_instance
    from app.providers.base import ChatChunk, Usage
    from app.providers.registry import ProviderRegistry
    from app.services import evaluation_runner

    class JudgeProvider:
        id = "fake-judge"

        def __init__(self) -> None:
            self.calls: list[list[object]] = []

        async def stream_chat(self, messages, model, **_opts):
            self.calls.append(list(messages))
            if "strict evaluator" in messages[0].content:
                yield ChatChunk(
                    delta='{"score": 4, "faithful": true, "reason": "supported"}',
                    usage=Usage(prompt_tokens=3, completion_tokens=2),
                    finish_reason="stop",
                )
            else:
                yield ChatChunk(
                    delta="退款一般在 3 个工作日内到账。",
                    usage=Usage(prompt_tokens=5, completion_tokens=4),
                    finish_reason="stop",
                )

    provider = JudgeProvider()
    registry = ProviderRegistry({provider.id: provider})
    monkeypatch.setattr(evaluation_runner, "build_embedder", lambda: fake_retrieval)
    monkeypatch.setattr(evaluation_runner, "build_registry", lambda: registry)
    previous = app_instance.dependency_overrides.get(get_registry)
    app_instance.dependency_overrides[get_registry] = lambda: registry
    try:
        headers, user_id, workspace_id, kb_id = await _setup(client, api, "eval-judge@example.com")
        refund = await _seed_document(
            workspace_id=workspace_id,
            kb_id=kb_id,
            user_id=user_id,
            filename="refund.txt",
            text="退款一般在 3 个工作日内到账。",
            vector=_vector(0),
        )
        fake_retrieval.mapping = {"退款": 0}
        dataset = await _create_dataset(client, headers, kb_id, [refund], count=1)
        run = await _run(
            client,
            headers,
            dataset["id"],
            kb_id,
            answer_enabled=True,
            judge_enabled=True,
            provider_id=provider.id,
            model="judge-model",
        )
    finally:
        if previous is None:
            app_instance.dependency_overrides.pop(get_registry, None)
        else:
            app_instance.dependency_overrides[get_registry] = previous

    assert run["status"] == "completed", run
    detail = await client.get(f"/evaluations/runs/{run['id']}", headers=headers)
    body = detail.json()
    assert body["metrics"]["judged_count"] == 1
    assert body["metrics"]["judge_avg_score"] == 4.0
    assert body["metrics"]["judge_pass_rate"] == 1.0
    assert body["metrics"]["faithful_rate"] == 1.0
    assert body["items"][0]["answer"] == "退款一般在 3 个工作日内到账。"
    assert body["items"][0]["judge_reason"] == "supported"
    assert len(provider.calls) == 2


async def test_dataset_import_maps_filenames_to_kb_documents(client, api):
    headers, user_id, workspace_id, kb_id = await _setup(client, api, "eval-import@example.com")
    refund = await _seed_document(
        workspace_id=workspace_id,
        kb_id=kb_id,
        user_id=user_id,
        filename="refund.md",
        text="退款政策",
        vector=_vector(0),
    )
    response = await client.post(
        "/evaluations/datasets/import",
        json={
            "name": "导入评测集",
            "kb_id": str(kb_id),
            "bundle": {
                "description": "bundle",
                "documents": [{"filename": "refund.md", "text": "退款政策"}],
                "questions": [
                    {
                        "question": "退款多久到账",
                        "relevant_filenames": ["refund.md"],
                        "evidence": ["3 个工作日"],
                    }
                ],
            },
        },
        headers=headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["question_count"] == 1
    assert body["questions"][0]["relevant_document_ids"] == [str(refund)]

    missing = await client.post(
        "/evaluations/datasets/import",
        json={
            "name": "bad",
            "kb_id": str(kb_id),
            "bundle": {
                "documents": [],
                "questions": [
                    {"question": "q", "relevant_filenames": ["missing.md"], "evidence": []}
                ],
            },
        },
        headers=headers,
    )
    assert missing.status_code == 422
    assert missing.json()["detail"]["code"] == "unknown_filenames"


async def test_dataset_and_run_are_workspace_scoped(client, api, fake_retrieval, monkeypatch):
    from app.services import evaluation_runner

    monkeypatch.setattr(evaluation_runner, "build_embedder", lambda: fake_retrieval)
    headers, user_id, workspace_id, kb_id = await _setup(client, api, "eval-alice@example.com")
    bob = await api.headers("eval-bob@example.com")
    doc = await _seed_document(
        workspace_id=workspace_id,
        kb_id=kb_id,
        user_id=user_id,
        filename="a.txt",
        text="alpha",
        vector=_vector(0),
    )
    dataset = await _create_dataset(client, headers, kb_id, [doc], count=1)
    run = await _run(client, headers, dataset["id"], kb_id)

    assert (
        await client.get(f"/evaluations/datasets/{dataset['id']}", headers=bob)
    ).status_code == 404
    assert (
        await client.post(
            "/evaluations/runs",
            json={"dataset_id": dataset["id"], "kb_id": str(kb_id)},
            headers=bob,
        )
    ).status_code == 404
    assert (await client.get(f"/evaluations/runs/{run['id']}", headers=bob)).status_code == 404
    assert (await client.get("/evaluations/datasets", headers=bob)).json() == []


async def test_run_rejects_documents_not_ready_in_selected_kb(client, api):
    headers, user_id, workspace_id, kb_id = await _setup(client, api, "eval-not-ready@example.com")
    doc = await _seed_document(
        workspace_id=workspace_id,
        kb_id=kb_id,
        user_id=user_id,
        filename="a.txt",
        text="alpha",
        vector=_vector(0),
        status="failed",
    )
    dataset = await _create_dataset(client, headers, kb_id, [doc], count=1)

    response = await client.post(
        "/evaluations/runs",
        json={"dataset_id": dataset["id"], "kb_id": str(kb_id)},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "dataset_documents_unavailable"


async def test_compare_runs(client, api, fake_retrieval, monkeypatch):
    from app.services import evaluation_runner

    monkeypatch.setattr(evaluation_runner, "build_embedder", lambda: fake_retrieval)
    headers, user_id, workspace_id, kb_id = await _setup(client, api, "eval-compare@example.com")
    doc = await _seed_document(
        workspace_id=workspace_id,
        kb_id=kb_id,
        user_id=user_id,
        filename="a.txt",
        text="alpha",
        vector=_vector(0),
    )
    fake_retrieval.mapping = {"alpha": 0}
    dataset = await _create_dataset(client, headers, kb_id, [doc], count=1)
    first = await _run(client, headers, dataset["id"], kb_id)
    second = await _run(client, headers, dataset["id"], kb_id, hybrid_enabled=False)

    response = await client.get(
        f"/evaluations/compare?ids={first['id']}&ids={second['id']}", headers=headers
    )

    assert response.status_code == 200
    assert [run["id"] for run in response.json()["runs"]] == [first["id"], second["id"]]


def test_judge_response_parsing_rejects_invalid_payloads():
    from app.services.evaluation_runner import parse_judge_response

    assert parse_judge_response('```json\n{"score": 4, "faithful": true, "reason": "ok"}\n```') == (
        4,
        True,
        "ok",
    )
    assert parse_judge_response('{"score": 4.6, "faithful": false, "reason": "x"}') == (
        5,
        False,
        "x",
    )
    assert parse_judge_response('{"score": "4", "faithful": "false", "reason": "x"}') == (
        4,
        False,
        "x",
    )
    with pytest.raises(ValueError):
        parse_judge_response('{"score": 9, "faithful": true, "reason": "bad"}')
    with pytest.raises(ValueError):
        parse_judge_response("no json here")


def test_compute_metrics_handles_empty_and_judge_fields():
    from app.services.evaluation_runner import compute_metrics

    assert compute_metrics([])["total"] == 0

    def item(rank, rr, evidence=None, score=None, faithful=None):
        return EvalRunItem(
            question_id=uuid4(),
            question_text="q",
            hit_rank=rank,
            reciprocal_rank=rr,
            evidence_hit=evidence,
            latency_ms=10.0,
            judge_score=score,
            judge_faithful=faithful,
        )

    metrics = compute_metrics(
        [item(1, 1.0, True, 5, True), item(None, 0.0, False, 3, False)],
        answer_enabled=True,
        judge_enabled=True,
    )

    assert metrics["recall_at_1"] == 0.5
    assert metrics["mrr"] == 0.5
    assert metrics["evidence_hit_rate"] == 0.5
    assert metrics["judge_avg_score"] == 4.0
    assert metrics["judge_pass_rate"] == 0.5
    assert metrics["faithful_rate"] == 0.5
