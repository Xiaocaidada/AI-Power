"""Pure ranking metrics used by knowledge evaluation and optimization."""

import math
from collections.abc import Sequence
from uuid import UUID

METRIC_KEYS = (
    "recall_at_1",
    "recall_at_3",
    "recall_at_5",
    "precision_at_5",
    "recall_at_5_docs",
    "ndcg_at_5",
    "precision_at_10",
    "recall_at_10_docs",
    "ndcg_at_10",
    "mrr",
)


def _ranked_documents(ranked: Sequence[UUID]) -> list[UUID]:
    seen: set[UUID] = set()
    ordered: list[UUID] = []
    for document_id in ranked:
        if document_id in seen:
            continue
        seen.add(document_id)
        ordered.append(document_id)
    return ordered


def precision_at_k(relevant: set[UUID], ranked: Sequence[UUID], k: int) -> float:
    if k <= 0:
        return 0.0
    docs = _ranked_documents(ranked)[:k]
    hits = sum(1 for document_id in docs if document_id in relevant)
    return round(hits / k, 4)


def recall_at_k(relevant: set[UUID], ranked: Sequence[UUID], k: int) -> float:
    if not relevant:
        return 0.0
    docs = _ranked_documents(ranked)[:k]
    hits = sum(1 for document_id in relevant if document_id in docs)
    return round(hits / len(relevant), 4)


def ndcg_at_k(relevant: set[UUID], ranked: Sequence[UUID], k: int) -> float:
    if not relevant or k <= 0:
        return 0.0
    docs = _ranked_documents(ranked)[:k]
    dcg = sum(
        1.0 / math.log2(index + 2)
        for index, document_id in enumerate(docs)
        if document_id in relevant
    )
    ideal = sum(1.0 / math.log2(index + 2) for index in range(min(len(relevant), k)))
    return round(dcg / ideal, 4) if ideal else 0.0


def aggregate_retrieval_traces(
    traces: Sequence[Sequence[dict[str, object]]],
) -> list[dict[str, object]]:
    """Aggregate per-question node traces into per-node-type timing rows."""
    buckets: dict[str, dict[str, object]] = {}
    order: list[str] = []
    for item_traces in traces:
        for trace in item_traces:
            node_type = str(trace.get("node_type") or "")
            if not node_type:
                continue
            bucket = buckets.get(node_type)
            if bucket is None:
                bucket = {
                    "node_type": node_type,
                    "runs": 0,
                    "failures": 0,
                    "total_ms": 0.0,
                    "total_count": 0,
                }
                buckets[node_type] = bucket
                order.append(node_type)
            bucket["runs"] = int(bucket["runs"]) + 1
            if str(trace.get("status") or "") != "completed":
                bucket["failures"] = int(bucket["failures"]) + 1
            try:
                bucket["total_ms"] = float(bucket["total_ms"]) + float(
                    trace.get("duration_ms") or 0.0
                )
            except (TypeError, ValueError):
                pass
            try:
                bucket["total_count"] = int(bucket["total_count"]) + int(
                    trace.get("count") or 0
                )
            except (TypeError, ValueError):
                pass
    rows: list[dict[str, object]] = []
    for node_type in order:
        bucket = buckets[node_type]
        runs = int(bucket["runs"])
        rows.append(
            {
                "node_type": node_type,
                "runs": runs,
                "failures": int(bucket["failures"]),
                "avg_ms": round(float(bucket["total_ms"]) / runs, 1) if runs else 0.0,
                "avg_count": round(float(bucket["total_count"]) / runs, 1)
                if runs
                else 0.0,
            }
        )
    return rows


def metric_delta(
    base: dict[str, object], candidate: dict[str, object]
) -> dict[str, dict[str, float | None]]:
    result: dict[str, dict[str, float | None]] = {}
    for key in METRIC_KEYS:
        before = _float_or_none(base.get(key))
        after = _float_or_none(candidate.get(key))
        result[key] = {
            "base": before,
            "candidate": after,
            "delta": round(after - before, 4)
            if before is not None and after is not None
            else None,
        }
    return result


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None