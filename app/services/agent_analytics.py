"""Aggregate Agent run health, cost and slow-node signals."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Conversation,
    CustomAgent,
    Message,
    UsageEvent,
    WorkflowNodeRun,
    WorkflowRun,
)

MAX_CHAT_CONVERSATIONS = 200


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * ratio))
    return round(ordered[index], 1)


async def agent_analytics(
    session: AsyncSession,
    agent: CustomAgent,
    workspace_id: UUID,
    *,
    days: int = 30,
) -> dict[str, object]:
    since = datetime.now(UTC) - timedelta(days=days)
    conversations = list(
        (
            await session.execute(
                select(Conversation)
                .where(
                    Conversation.custom_agent_id == agent.id,
                    Conversation.workspace_id == workspace_id,
                    Conversation.updated_at >= since,
                )
                .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
                .limit(MAX_CHAT_CONVERSATIONS)
            )
        ).scalars()
    )
    conversation_ids = [conversation.id for conversation in conversations]
    chat_statuses: list[str] = []
    if conversation_ids:
        replies = (
            await session.execute(
                select(Message.conversation_id, Message.status)
                .where(
                    Message.conversation_id.in_(conversation_ids),
                    Message.role == "assistant",
                )
                .order_by(Message.created_at, Message.id)
            )
        ).all()
        latest: dict[UUID, str] = {}
        for conversation_id, status in replies:
            latest[conversation_id] = status
        chat_statuses = [
            "completed" if latest.get(item) in {None, "ready"} else latest[item]
            for item in conversation_ids
        ]

    runs: list[WorkflowRun] = []
    if agent.workflow_id is not None:
        runs = list(
            (
                await session.execute(
                    select(WorkflowRun).where(
                        WorkflowRun.workflow_id == agent.workflow_id,
                        WorkflowRun.workspace_id == workspace_id,
                        WorkflowRun.started_at >= since,
                    )
                )
            ).scalars()
        )

    chat_tokens = 0
    chat_cost = 0.0
    if conversation_ids:
        chat_totals = (
            await session.execute(
                select(
                    func.coalesce(
                        func.sum(
                            func.coalesce(UsageEvent.prompt_tokens, 0)
                            + func.coalesce(UsageEvent.completion_tokens, 0)
                        ),
                        0,
                    ),
                    func.coalesce(func.sum(UsageEvent.cost), 0.0),
                ).where(
                    UsageEvent.workspace_id == workspace_id,
                    UsageEvent.conversation_id.in_(conversation_ids),
                    UsageEvent.source == "chat",
                )
            )
        ).one()
        chat_tokens = int(chat_totals[0] or 0)
        chat_cost = float(chat_totals[1] or 0.0)

    workflow_tokens = sum(
        int(run.prompt_tokens or 0) + int(run.completion_tokens or 0) for run in runs
    )
    workflow_cost = sum(float(run.cost or 0.0) for run in runs)
    statuses = [*chat_statuses, *[run.status for run in runs]]
    completed = sum(1 for status in statuses if status == "completed")
    failed = sum(1 for status in statuses if status == "failed")
    cancelled = sum(1 for status in statuses if status == "cancelled")
    running = sum(1 for status in statuses if status in {"queued", "running"})
    total = len(statuses)
    success_rate = round(completed / total, 4) if total else 0.0
    durations = [float(run.total_ms) for run in runs if run.total_ms is not None]
    failure_codes: dict[str, int] = {}
    for run in runs:
        if run.status == "failed":
            code = run.error_code or "unknown"
            failure_codes[code] = failure_codes.get(code, 0) + 1

    slow_nodes: list[dict[str, object]] = []
    if runs:
        node_rows = list(
            (
                await session.execute(
                    select(WorkflowNodeRun).where(
                        WorkflowNodeRun.run_id.in_([run.id for run in runs])
                    )
                )
            ).scalars()
        )
        grouped: dict[tuple[str, str], dict[str, object]] = {}
        for node in node_rows:
            key = (node.node_id, node.node_type)
            entry = grouped.setdefault(
                key,
                {
                    "node_id": node.node_id,
                    "node_type": node.node_type,
                    "count": 0,
                    "failures": 0,
                    "durations": [],
                },
            )
            entry["count"] = int(entry["count"]) + 1
            if node.status == "failed":
                entry["failures"] = int(entry["failures"]) + 1
                if node.error_code:
                    failure_codes[node.error_code] = (
                        failure_codes.get(node.error_code, 0) + 1
                    )
            if node.duration_ms is not None:
                durations_for_node = entry["durations"]
                if isinstance(durations_for_node, list):
                    durations_for_node.append(float(node.duration_ms))
        for entry in grouped.values():
            values = entry.pop("durations")
            entry["avg_duration_ms"] = (
                round(sum(values) / len(values), 1)
                if isinstance(values, list) and values
                else 0.0
            )
        slow_nodes = sorted(
            grouped.values(),
            key=lambda item: (float(item["avg_duration_ms"]), int(item["failures"])),
            reverse=True,
        )[:5]

    avg_duration = round(sum(durations) / len(durations), 1) if durations else 0.0
    p95 = _percentile(durations, 0.95)
    cost = round(chat_cost + workflow_cost, 6)
    suggestions: list[dict[str, str]] = []
    if total == 0:
        suggestions.append(
            {
                "kind": "no_data",
                "title": "暂无运行数据",
                "detail": "在体验页运行一次聊天或工作流后再查看分析。",
            }
        )
    if total and (failed / total) >= 0.2:
        top_code = max(failure_codes, key=failure_codes.get) if failure_codes else "unknown"
        suggestions.append(
            {
                "kind": "review_failures",
                "title": "失败率偏高",
                "detail": f"近期失败率 {failed / total:.0%}，最常见错误为 {top_code}。",
            }
        )
    if p95 >= 15000:
        suggestions.append(
            {
                "kind": "slow_runs",
                "title": "P95 耗时较高",
                "detail": f"工作流 P95 为 {p95:.0f} ms，建议检查慢节点或模型响应。",
            }
        )
    failed_nodes = [node for node in slow_nodes if int(node["failures"]) > 0]
    if failed_nodes:
        node = failed_nodes[0]
        suggestions.append(
            {
                "kind": "inspect_node",
                "title": "优先检查失败节点",
                "detail": (
                    f"节点 {node['node_id']}（{node['node_type']}）出现 "
                    f"{node['failures']} 次失败。"
                ),
            }
        )
    if total and cost / total >= 0.02:
        suggestions.append(
            {
                "kind": "reduce_cost",
                "title": "单次成本偏高",
                "detail": f"平均每次运行成本约 ${cost / total:.4f}，可下调 max_tokens。",
            }
        )
    if total >= 5 and success_rate >= 0.95 and failed == 0:
        suggestions.append(
            {
                "kind": "stable",
                "title": "运行稳定",
                "detail": "近期成功率不低于 95%，暂无明显异常。",
            }
        )

    return {
        "window_days": days,
        "total_runs": total,
        "chat_runs": len(chat_statuses),
        "workflow_runs": len(runs),
        "completed": completed,
        "failed": failed,
        "cancelled": cancelled,
        "running": running,
        "success_rate": success_rate,
        "avg_duration_ms": avg_duration,
        "p95_duration_ms": p95,
        "chat_tokens": chat_tokens,
        "workflow_tokens": workflow_tokens,
        "prompt_tokens": sum(int(run.prompt_tokens or 0) for run in runs),
        "completion_tokens": sum(int(run.completion_tokens or 0) for run in runs),
        "cost": cost,
        "failure_codes": failure_codes,
        "slow_nodes": slow_nodes,
        "suggestions": suggestions,
    }