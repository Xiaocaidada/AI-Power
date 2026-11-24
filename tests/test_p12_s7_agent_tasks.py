import json
from uuid import UUID

from pydantic import BaseModel

from app.db import SessionLocal
from app.models import CustomAgent
from app.tools.base import ToolRegistry, ToolSpec

PLAN = json.dumps(
    {
        "title": "执行危险操作",
        "steps": [
            {"title": "准备", "detail": "确认输入"},
            {"title": "执行", "detail": "调用工具"},
        ],
    }
)
TOOL_CALL = json.dumps({"action": "tool", "tool": "danger", "arguments": {}})
FINAL = json.dumps(
    {"action": "final", "answer": "任务已完成。\n\n```python\nprint('ok')\n```"}
)


class EmptyArgs(BaseModel):
    pass


def _patch_tools(monkeypatch, calls: list[str]):
    async def handler(context, args):
        calls.append("executed")
        return "danger done"

    registry = ToolRegistry(
        [
            ToolSpec(
                name="danger",
                description="Perform a sensitive external action",
                args_model=EmptyArgs,
                handler=handler,
                risk="high",
            )
        ]
    )
    monkeypatch.setattr("app.services.agent_tasks.build_tool_registry", lambda: registry)


async def _agent(client, headers, tools: list[str]) -> str:
    me = await client.get("/auth/me", headers=headers)
    workspaces = await client.get("/workspaces", headers=headers)
    async with SessionLocal() as session:
        agent = CustomAgent(
            workspace_id=UUID(workspaces.json()[0]["id"]),
            owner_user_id=UUID(me.json()["id"]),
            name="Danger agent",
            instructions="Execute the goal carefully.",
            tools=tools,
        )
        session.add(agent)
        await session.commit()
        return str(agent.id)


async def _create_task(client, headers, agent_id):
    return await client.post(
        "/agent-tasks",
        json={
            "goal": "执行需要审批的操作",
            "agent_id": agent_id,
            "provider_id": "fake",
            "model": "fake-model",
            "max_steps": 4,
        },
        headers=headers,
    )


async def test_agent_task_requires_approval_for_high_risk_tool(
    client, api, registry, fake_provider, monkeypatch
):
    headers = await api.headers("p12-s7-approve@example.com")
    calls: list[str] = []
    _patch_tools(monkeypatch, calls)
    agent_id = await _agent(client, headers, ["danger"])
    fake_provider.complete_contents = [PLAN, TOOL_CALL, FINAL]

    created = await _create_task(client, headers, agent_id)
    assert created.status_code == 201
    task_id = created.json()["id"]
    assert created.json()["status"] == "waiting_approval"
    assert created.json()["plan"]["confirmed"] is False

    await client.post(f"/agent-tasks/{task_id}/confirm", headers=headers)
    pending = await client.get(f"/agent-tasks/{task_id}", headers=headers)
    assert pending.json()["status"] == "waiting_approval"
    approvals = pending.json()["plan"]["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["status"] == "pending"
    assert approvals[0]["tool"] == "danger"
    assert calls == []

    approved = await client.post(
        f"/agent-tasks/{task_id}/approval",
        json={"approval_id": approvals[0]["id"], "decision": "approve"},
        headers=headers,
    )
    assert approved.status_code == 200

    detail = await client.get(f"/agent-tasks/{task_id}", headers=headers)
    body = detail.json()
    assert body["status"] == "completed"
    assert body["result"]["text"].startswith("任务已完成")
    assert body["result"]["artifacts"][0]["language"] == "python"
    assert body["plan"]["approvals"][0]["status"] == "approved"
    assert body["checkpoint"]["tool_calls"] == 1
    assert calls == ["executed"]

    events = await client.get(f"/chat-tasks/{task_id}/events?after=0", headers=headers)
    names = [
        line.split("event: ", 1)[1]
        for line in events.text.splitlines()
        if line.startswith("event: ")
    ]
    assert "approval_required" in names
    assert "approval_resolved" in names
    assert "agent_tool_call" in names
    assert "agent_tool_result" in names
    assert "agent_artifact_ready" in names


async def test_agent_task_rejection_does_not_execute_tool(
    client, api, registry, fake_provider, monkeypatch
):
    headers = await api.headers("p12-s7-reject@example.com")
    calls: list[str] = []
    _patch_tools(monkeypatch, calls)
    agent_id = await _agent(client, headers, ["danger"])
    fake_provider.complete_contents = [PLAN, TOOL_CALL, FINAL]
    created = await _create_task(client, headers, agent_id)
    task_id = created.json()["id"]
    await client.post(f"/agent-tasks/{task_id}/confirm", headers=headers)
    pending = await client.get(f"/agent-tasks/{task_id}", headers=headers)
    approval_id = pending.json()["plan"]["approvals"][0]["id"]

    rejected = await client.post(
        f"/agent-tasks/{task_id}/approval",
        json={
            "approval_id": approval_id,
            "decision": "reject",
            "note": "外部写操作不允许",
        },
        headers=headers,
    )
    assert rejected.status_code == 200

    detail = await client.get(f"/agent-tasks/{task_id}", headers=headers)
    assert detail.json()["status"] == "completed"
    assert calls == []
    records = detail.json()["checkpoint"]["tool_records"]
    assert records[0]["error_code"] == "approval_rejected"


async def test_agent_task_plan_confirm_pause_and_cancel(
    client, api, registry, fake_provider, monkeypatch, fake_queue
):
    headers = await api.headers("p12-s7-control@example.com")
    calls: list[str] = []
    _patch_tools(monkeypatch, calls)
    agent_id = await _agent(client, headers, ["danger"])
    fake_provider.complete_contents = [PLAN]
    fake_queue.defer_chat_tasks = True
    created = await _create_task(client, headers, agent_id)
    task_id = created.json()["id"]

    confirmed = await client.post(f"/agent-tasks/{task_id}/confirm", headers=headers)
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "queued"
    paused = await client.post(f"/chat-tasks/{task_id}/pause", headers=headers)
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    resumed = await client.post(f"/chat-tasks/{task_id}/resume", headers=headers)
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "queued"

    cancelled = await client.post(f"/chat-tasks/{task_id}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    again = await client.post(f"/chat-tasks/{task_id}/cancel", headers=headers)
    assert again.json()["status"] == "cancelled"