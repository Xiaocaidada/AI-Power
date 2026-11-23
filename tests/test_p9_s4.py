import json
from uuid import UUID, uuid4

from app.services.knowledge.metrics import (
    aggregate_retrieval_traces,
    metric_delta,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def _retrieval_definition(top_k: int = 5) -> dict:
    return {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "vector", "type": "vector_search", "config": {"top_k": top_k}},
            {"id": "out", "type": "output", "config": {}},
        ],
        "edges": [
            {"from": "start", "to": "vector"},
            {"from": "vector", "to": "out"},
        ],
    }


def test_ranking_metrics_and_trace_aggregation():
    relevant = {UUID(int=1), UUID(int=2)}
    ranked = [UUID(int=1), UUID(int=3), UUID(int=2)]

    assert precision_at_k(relevant, ranked, 3) == 0.6667
    assert recall_at_k(relevant, ranked, 3) == 1.0
    assert 0.0 < ndcg_at_k(relevant, ranked, 3) < 1.0
    assert ndcg_at_k(relevant, [UUID(int=1), UUID(int=2)], 3) == 1.0

    rows = aggregate_retrieval_traces(
        [
            [
                {
                    "node_type": "vector_search",
                    "status": "completed",
                    "duration_ms": 10,
                    "count": 5,
                },
                {
                    "node_type": "rerank",
                    "status": "completed",
                    "duration_ms": 4,
                    "count": 3,
                },
            ],
            [
                {
                    "node_type": "vector_search",
                    "status": "failed",
                    "duration_ms": 20,
                    "count": 0,
                },
            ],
        ]
    )
    by_type = {row["node_type"]: row for row in rows}
    assert by_type["vector_search"]["runs"] == 2
    assert by_type["vector_search"]["failures"] == 1
    assert by_type["vector_search"]["avg_ms"] == 15.0
    assert by_type["rerank"]["avg_count"] == 3.0

    delta = metric_delta({"ndcg_at_5": 0.4}, {"ndcg_at_5": 0.7})
    assert delta["ndcg_at_5"]["delta"] == 0.3


async def _setup_kb_with_document(client, api, fake_ingestion, email: str):
    headers = await api.headers(email)
    kb = await client.post("/knowledge-bases", json={"name": "P9-S4 KB"}, headers=headers)
    assert kb.status_code == 201
    kb_id = kb.json()["id"]
    document = await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("s4.txt", b"alpha beta gamma delta", "text/plain")},
        headers=headers,
    )
    assert document.status_code == 202, document.text
    detail = await client.get(f"/documents/{document.json()['id']}", headers=headers)
    assert detail.json()["status"] == "ready"
    return headers, kb_id, document.json()["id"]


async def _create_dataset(client, headers, document_id: str) -> dict:
    response = await client.post(
        "/evaluations/datasets",
        json={
            "name": f"S4 dataset {uuid4().hex[:6]}",
            "description": "P9-S4",
            "questions": [
                {
                    "question": "alpha beta",
                    "relevant_document_ids": [document_id],
                    "evidence": [],
                },
                {
                    "question": "gamma delta",
                    "relevant_document_ids": [document_id],
                    "evidence": [],
                },
            ],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_evaluation_with_retrieval_workflow_metrics_and_analysis(
    client, api, fake_ingestion, fake_retrieval
):
    headers, kb_id, document_id = await _setup_kb_with_document(
        client, api, fake_ingestion, "p9-s4-eval@example.com"
    )
    dataset = await _create_dataset(client, headers, document_id)
    workflow = await client.post(
        "/workflows",
        json={
            "name": "S4 retrieval",
            "kind": "knowledge_retrieval",
            "definition": _retrieval_definition(),
        },
        headers=headers,
    )
    assert workflow.status_code == 201, workflow.text
    version_id = workflow.json()["versions"][0]["id"]

    created = await client.post(
        "/evaluations/runs",
        json={
            "dataset_id": dataset["id"],
            "kb_id": kb_id,
            "retrieval_workflow_version_id": version_id,
            "top_k": 5,
            "candidate_k": 10,
            "hybrid_enabled": False,
            "rerank_enabled": False,
        },
        headers=headers,
    )
    assert created.status_code == 202, created.text
    run = created.json()
    assert run["retrieval_workflow_version_id"] == version_id
    assert run["status"] == "completed", run
    metrics = run["metrics"]
    assert metrics["retrieval_mode"] == "workflow"
    assert metrics["precision_at_5"] == 0.2
    assert metrics["recall_at_5_docs"] == 1.0
    assert metrics["ndcg_at_5"] == 1.0
    assert metrics["success_rate"] == 1.0
    timing_types = {row["node_type"] for row in metrics["node_timing"]}
    assert {"start", "vector_search", "output"} <= timing_types

    detail = await client.get(f"/evaluations/runs/{run['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    item = detail.json()["items"][0]
    assert item["retrieval_mode"] == "workflow"
    assert item["retrieval_trace"]
    assert item["ndcg_at_5"] == 1.0

    analysis = await client.get(
        f"/evaluations/runs/{run['id']}/analysis", headers=headers
    )
    assert analysis.status_code == 200, analysis.text
    body = analysis.json()
    assert body["run"]["id"] == run["id"]
    assert body["node_timing"]
    assert body["worst_questions"]
    assert body["slowest_questions"]

    builtin = await client.post(
        "/evaluations/runs",
        json={
            "dataset_id": dataset["id"],
            "kb_id": kb_id,
            "top_k": 5,
            "candidate_k": 10,
            "hybrid_enabled": False,
            "rerank_enabled": False,
        },
        headers=headers,
    )
    assert builtin.status_code == 202, builtin.text
    assert builtin.json()["retrieval_workflow_version_id"] is None
    compared = await client.get(
        f"/evaluations/compare?ids={run['id']}&ids={builtin.json()['id']}",
        headers=headers,
    )
    assert compared.status_code == 200, compared.text
    ids = {row["id"] for row in compared.json()["runs"]}
    assert ids == {run["id"], builtin.json()["id"]}


async def test_optimization_generate_apply_rollback(
    client, api, fake_ingestion, fake_retrieval, registry
):
    headers, kb_id, document_id = await _setup_kb_with_document(
        client, api, fake_ingestion, "p9-s4-opt@example.com"
    )
    dataset = await _create_dataset(client, headers, document_id)
    workflow = await client.post(
        "/workflows",
        json={
            "name": "S4 optimize me",
            "kind": "knowledge_retrieval",
            "definition": _retrieval_definition(),
        },
        headers=headers,
    )
    assert workflow.status_code == 201, workflow.text
    workflow_id = workflow.json()["id"]
    version_id = workflow.json()["versions"][0]["id"]
    bound = await client.put(
        f"/knowledge-bases/{kb_id}/retrieval/binding",
        json={"workflow_version_id": version_id},
        headers=headers,
    )
    assert bound.status_code == 200, bound.text

    run = await client.post(
        "/evaluations/runs",
        json={
            "dataset_id": dataset["id"],
            "kb_id": kb_id,
            "retrieval_workflow_version_id": version_id,
            "top_k": 5,
            "candidate_k": 10,
            "hybrid_enabled": False,
            "rerank_enabled": False,
        },
        headers=headers,
    )
    assert run.status_code == 202, run.text
    assert run.json()["status"] == "completed"

    proposal = _retrieval_definition(top_k=8)
    registry.get("fake").complete_content = json.dumps(
        {
            "summary": "Increase recall window",
            "rationale": "The failing questions need a wider candidate set.",
            "suggestions": [
                {"title": "Raise top_k", "detail": "Use top_k=8 for recall."},
            ],
            "definition": proposal,
        }
    )
    generated = await client.post(
        f"/knowledge-bases/{kb_id}/optimizations",
        json={
            "eval_run_id": run.json()["id"],
            "provider_id": "fake",
            "model": "fake-model",
        },
        headers=headers,
    )
    assert generated.status_code == 201, generated.text
    optimization = generated.json()
    assert optimization["status"] == "proposed"
    assert optimization["proposed_definition"]["nodes"][1]["config"]["top_k"] == 8
    assert optimization["diff"] is not None
    assert optimization["suggestions"][0]["title"] == "Raise top_k"

    listed = await client.get(
        f"/knowledge-bases/{kb_id}/optimizations", headers=headers
    )
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [optimization["id"]]

    applied = await client.post(
        f"/knowledge-bases/{kb_id}/optimizations/{optimization['id']}/apply",
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    applied_body = applied.json()
    assert applied_body["status"] == "applied"
    assert applied_body["applied_version_id"] is not None
    assert applied_body["previous_binding_version_id"] == version_id

    binding = await client.get(
        f"/knowledge-bases/{kb_id}/retrieval/binding", headers=headers
    )
    assert binding.json()["workflow_version_id"] == applied_body["applied_version_id"]
    assert binding.json()["workflow_id"] == workflow_id

    reverted = await client.post(
        f"/knowledge-bases/{kb_id}/optimizations/{optimization['id']}/rollback",
        headers=headers,
    )
    assert reverted.status_code == 200, reverted.text
    assert reverted.json()["status"] == "reverted"
    binding_after = await client.get(
        f"/knowledge-bases/{kb_id}/retrieval/binding", headers=headers
    )
    assert binding_after.json()["workflow_version_id"] == version_id


async def test_optimization_requires_completed_run_and_matching_kb(
    client, api, fake_ingestion, fake_retrieval, registry
):
    headers, kb_id, document_id = await _setup_kb_with_document(
        client, api, fake_ingestion, "p9-s4-scope@example.com"
    )
    dataset = await _create_dataset(client, headers, document_id)
    run = await client.post(
        "/evaluations/runs",
        json={
            "dataset_id": dataset["id"],
            "kb_id": kb_id,
            "top_k": 5,
            "hybrid_enabled": False,
            "rerank_enabled": False,
        },
        headers=headers,
    )
    assert run.status_code == 202
    other = await client.post(
        "/knowledge-bases", json={"name": "Other KB"}, headers=headers
    )
    generated = await client.post(
        f"/knowledge-bases/{other.json()['id']}/optimizations",
        json={
            "eval_run_id": run.json()["id"],
            "provider_id": "fake",
            "model": "fake-model",
        },
        headers=headers,
    )
    assert generated.status_code == 404