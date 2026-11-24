"""P12-S7 resumable Agent execution with tool approvals and artifacts."""

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.protocol import PROTOCOL_HINT, FinalAnswer, ToolCall, parse_agent_output
from app.config import get_settings
from app.models import ChatTask, Conversation, Message
from app.providers.base import ChatMessage
from app.services.agent_tools import build_mcp_tool_specs
from app.services.chat_modes import thinking_provider_opts
from app.services.chat_tasks import (
    ChatTaskError,
    append_event,
    checkpoint_or_stop,
    fail_task,
    finish_task,
    mark_task_started,
    touch_lease,
)
from app.services.custom_agents import CustomAgentError, get_custom_agent
from app.services.model_stream import ModelCompletion
from app.services.plugins import build_plugin_tools_for_ids
from app.services.provider_configs import build_user_registry
from app.services.reuse import extract_code_blocks
from app.services.usage_ledger import SOURCE_AGENT_TASK
from app.tools.base import ToolContext, ToolRegistry
from app.tools.registry import build_tool_registry

logger = logging.getLogger(__name__)

MODEL_PLAN_MAX_TOKENS = 1000
MODEL_STEP_MAX_TOKENS = 1500
MAX_OBSERVATION_CHARS = 3000


def _text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _json_object(raw: str) -> dict[str, Any] | None:
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(raw[start : end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _fallback_steps(goal: str, language: str) -> list[dict[str, str]]:
    if language == "zh":
        return [
            {"title": "理解目标与约束", "detail": goal[:300]},
            {"title": "检索所需信息", "detail": "使用可用工具收集完成任务所需的事实。"},
            {"title": "执行任务步骤", "detail": "调用工具完成可执行操作，并记录结果。"},
            {"title": "汇总结果", "detail": "给出结果、依据与未完成事项。"},
        ]
    return [
        {"title": "Understand the goal", "detail": goal[:300]},
        {"title": "Gather information", "detail": "Use available tools to collect facts."},
        {"title": "Execute the work", "detail": "Call tools and record every result."},
        {"title": "Summarize", "detail": "Report results, evidence and open items."},
    ]


def _normalize_steps(raw: object, max_steps: int) -> list[dict[str, str]]:
    steps: list[dict[str, str]] = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            title = _text(item.get("title"), 120)
            detail = _text(item.get("detail"), 500)
            if not title:
                continue
            steps.append({"title": title, "detail": detail or title})
            if len(steps) >= max_steps:
                break
    return steps


async def _resolve_agent(
    session: AsyncSession, workspace_id: UUID, user_id: UUID, agent_id: UUID | None
):
    if agent_id is None:
        return None
    try:
        agent = await get_custom_agent(session, workspace_id, agent_id, user_id)
    except CustomAgentError:
        raise ChatTaskError("agent_not_found", "Agent not found") from None
    if not agent.enabled:
        raise ChatTaskError("agent_unavailable", "Agent is not available")
    return agent


async def _build_tools(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    agent,
    plugin_ids: list[str],
    kb_ids: list[UUID],
) -> tuple[ToolRegistry, list[str]]:
    registry = build_tool_registry()
    plugins = await build_plugin_tools_for_ids(session, workspace_id, plugin_ids)
    if plugins:
        registry = registry.with_tools(plugins)
    if agent is not None and agent.tools:
        mcp_tools = await build_mcp_tool_specs(session, list(agent.tools))
        if mcp_tools:
            registry = registry.with_tools(mcp_tools)
    allowed: list[str] = []
    if agent is not None:
        for name in agent.tools:
            if registry.has(name) and name not in allowed:
                allowed.append(name)
    for spec in plugins:
        if spec.name not in allowed:
            allowed.append(spec.name)
    if kb_ids and "kb_search" not in allowed:
        allowed.append("kb_search")
    if not allowed:
        allowed = ["current_time", "calculator"]
        if kb_ids:
            allowed.append("kb_search")
    return registry, allowed


def _descriptor_block(registry: ToolRegistry, allowed: list[str]) -> str:
    descriptors = [
        descriptor
        for name in allowed
        if (spec := registry.get(name)) is not None
        for descriptor in [spec.prompt_descriptor()]
    ]
    return json.dumps(descriptors, ensure_ascii=False)


async def generate_agent_plan(
    *,
    provider,
    model: str,
    goal: str,
    language: str,
    max_steps: int,
    registry: ToolRegistry,
    allowed: list[str],
    workspace_id: UUID,
    user_id: UUID,
    thinking_level: str,
) -> dict[str, Any]:
    prompt = [
        "You are planning an autonomous agent task. Do not execute it yet.",
        f"Goal: {goal}",
        f"Language: {'Chinese' if language == 'zh' else 'English'}",
        f"Available tools: {', '.join(allowed)}",
        'Return JSON only: {"title": string, "steps": [{"title": string, "detail": string}]}',
        f"Produce 3-{max_steps} short steps. Steps describe intent, not tool arguments.",
        "Do not invent tools or claim that work is already done.",
    ]
    completion = ModelCompletion(
        provider=provider,
        model=model,
        messages=[ChatMessage(role="user", content="\n".join(prompt))],
        opts={
            "temperature": 0.2,
            "max_tokens": MODEL_PLAN_MAX_TOKENS,
            **thinking_provider_opts(thinking_level),
        },
        workspace_id=workspace_id,
        user_id=user_id,
        source=SOURCE_AGENT_TASK,
    )
    metrics = await completion.run()
    if metrics.status == "completed":
        parsed = _json_object(metrics.content)
        if parsed is not None:
            steps = _normalize_steps(parsed.get("steps"), max_steps)
            if len(steps) >= 2:
                return {
                    "title": _text(parsed.get("title"), 160) or goal[:160],
                    "steps": steps,
                    "tools": allowed,
                }
    return {"title": goal[:160], "steps": _fallback_steps(goal, language), "tools": allowed}


async def create_agent_task(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    conversation_id: UUID | None,
    provider_id: str,
    model: str,
    goal: str,
    agent_id: UUID | None,
    plugin_ids: list[str],
    kb_ids: list[UUID],
    max_steps: int,
    thinking_level: str,
    language: str,
    provider,
) -> ChatTask:
    clean_goal = _text(goal, 2000)
    if clean_goal == "":
        raise ChatTaskError("goal_required", "Agent task goal is required")
    if conversation_id is not None:
        conversation = (
            await session.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.workspace_id == workspace_id,
                    Conversation.user_id == user_id,
                    Conversation.archived_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if conversation is None:
            raise ChatTaskError("conversation_not_found", "Conversation not found")
    agent = await _resolve_agent(session, workspace_id, user_id, agent_id)
    owned_kbs: list[UUID] = []
    if kb_ids:
        from app.models import KnowledgeBase

        rows = list(
            (
                await session.execute(
                    select(KnowledgeBase.id).where(
                        KnowledgeBase.id.in_(kb_ids),
                        KnowledgeBase.workspace_id == workspace_id,
                        KnowledgeBase.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )
        allowed_kbs = set(rows)
        owned_kbs = [item for item in kb_ids if item in allowed_kbs]
    registry, allowed = await _build_tools(
        session,
        workspace_id=workspace_id,
        agent=agent,
        plugin_ids=[str(item) for item in plugin_ids],
        kb_ids=owned_kbs,
    )
    plan = await generate_agent_plan(
        provider=provider,
        model=model,
        goal=clean_goal,
        language=language,
        max_steps=max_steps,
        registry=registry,
        allowed=allowed,
        workspace_id=workspace_id,
        user_id=user_id,
        thinking_level=thinking_level,
    )
    steps = [
        {
            "index": index,
            "title": step["title"],
            "detail": step["detail"],
            "status": "pending",
        }
        for index, step in enumerate(plan["steps"])
    ]
    task = ChatTask(
        workspace_id=workspace_id,
        user_id=user_id,
        conversation_id=conversation_id,
        kind="agent",
        title=_text(plan["title"], 200) or clean_goal[:200],
        status="waiting_approval",
        input={
            "provider_id": provider_id,
            "model": model,
            "thinking_level": thinking_level,
            "goal": clean_goal,
            "agent_id": str(agent.id) if agent is not None else None,
            "plugin_ids": [str(item) for item in plugin_ids],
            "kb_ids": [str(item) for item in owned_kbs],
            "tools": allowed,
            "max_steps": max_steps,
            "language": language,
        },
        plan={
            "version": 1,
            "confirmed": False,
            "status": "pending_confirmation",
            "steps": steps,
            "approvals": [],
        },
        checkpoint={
            "exchanges": [],
            "tool_records": [],
            "llm_calls": 0,
            "tool_calls": 0,
            "tokens": 0,
            "plan_cursor": 0,
        },
        result={},
    )
    session.add(task)
    await session.flush()
    await append_event(
        session,
        task.id,
        "agent_plan_created",
        {"steps": steps, "tools": allowed, "status": "waiting_approval"},
    )
    return task


async def update_agent_plan(
    session: AsyncSession, task: ChatTask, steps: list[dict[str, str]]
) -> ChatTask:
    if task.kind != "agent":
        raise ChatTaskError("invalid_kind", "Task is not an agent task")
    if task.status != "waiting_approval" or (task.plan or {}).get("confirmed"):
        raise ChatTaskError("plan_locked", "The agent plan can no longer be edited")
    normalized = _normalize_steps(steps, 12)
    if not normalized:
        raise ChatTaskError("plan_required", "At least one agent step is required")
    plan = dict(task.plan or {})
    plan["steps"] = [
        {"index": index, "title": step["title"], "detail": step["detail"], "status": "pending"}
        for index, step in enumerate(normalized)
    ]
    task.plan = plan
    await append_event(session, task.id, "agent_plan_updated", {"steps": plan["steps"]})
    await session.flush()
    return task


async def confirm_agent_plan(session: AsyncSession, task: ChatTask) -> ChatTask:
    if task.kind != "agent":
        raise ChatTaskError("invalid_kind", "Task is not an agent task")
    if task.status != "waiting_approval":
        raise ChatTaskError("plan_not_pending", "The plan is not waiting for confirmation")
    plan = dict(task.plan or {})
    if plan.get("confirmed"):
        return task
    if not plan.get("steps"):
        raise ChatTaskError("plan_required", "At least one agent step is required")
    plan["confirmed"] = True
    plan["status"] = "confirmed"
    task.plan = plan
    task.status = "queued"
    task.finished_at = None
    await append_event(
        session,
        task.id,
        "agent_plan_confirmed",
        {"steps": len(plan["steps"]), "status": "queued"},
    )
    await session.flush()
    return task


def _system_prompt(
    *,
    goal: str,
    agent,
    registry: ToolRegistry,
    allowed: list[str],
    plan: dict[str, Any],
) -> str:
    base = (
        agent.instructions
        if agent is not None
        else "You are an autonomous assistant executing a long-running task."
    )
    plan_lines = [
        f"{index + 1}. {step['title']} — {step.get('detail', '')}"
        for index, step in enumerate(plan.get("steps") or [])
    ]
    return "\n".join(
        [
            base,
            "",
            f"Goal: {goal}",
            "",
            "Plan:",
            *plan_lines,
            "",
            "Available tools (JSON schema):",
            _descriptor_block(registry, allowed),
            "",
            "Rules: call at most one tool per turn. Never invent tool results. "
            "Finish with a final answer that states what was done, evidence and open items.",
            "",
            PROTOCOL_HINT,
        ]
    )


def _observation(output: str, ok: bool, error: str | None) -> str:
    if ok:
        return f"<tool_output>\n{output[:MAX_OBSERVATION_CHARS]}\n</tool_output>"
    return f'<tool_error>\n{(error or "tool failed")[:500]}\n</tool_error>'


def _tool_turn(tool: str, arguments: dict[str, Any]) -> str:
    return json.dumps(
        {"action": "tool", "tool": tool, "arguments": arguments},
        ensure_ascii=False,
    )


def _approval_record(tool: str, arguments: dict[str, Any], risk: str) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "tool": tool,
        "arguments": arguments,
        "risk": risk,
        "status": "pending",
        "created_at": datetime.now(UTC).isoformat(),
        "note": "",
    }


async def decide_approval(
    session: AsyncSession,
    task: ChatTask,
    *,
    approval_id: str,
    decision: str,
    note: str,
) -> ChatTask:
    if task.kind != "agent":
        raise ChatTaskError("invalid_kind", "Task is not an agent task")
    plan = dict(task.plan or {})
    approvals = [dict(item) for item in plan.get("approvals") or [] if isinstance(item, dict)]
    target = next((item for item in approvals if item.get("id") == approval_id), None)
    if target is None:
        raise ChatTaskError("approval_not_found", "Approval request not found")
    if target.get("status") != "pending":
        raise ChatTaskError("approval_resolved", "Approval request is already resolved")
    if task.status not in {"waiting_approval", "paused"}:
        raise ChatTaskError("approval_unavailable", "Task is not waiting for approval")
    target["status"] = "approved" if decision == "approve" else "rejected"
    target["note"] = _text(note, 500)
    target["resolved_at"] = datetime.now(UTC).isoformat()
    plan["approvals"] = approvals
    task.plan = plan
    checkpoint = dict(task.checkpoint or {})
    pending = dict(checkpoint.get("pending_approval") or {})
    if pending.get("id") == approval_id:
        checkpoint["pending_approval"] = {
            **pending,
            "status": target["status"],
            "note": target["note"],
        }
    task.checkpoint = checkpoint
    task.status = "queued"
    task.finished_at = None
    await append_event(
        session,
        task.id,
        "approval_resolved",
        {
            "approval_id": approval_id,
            "tool": target.get("tool"),
            "status": target["status"],
            "note": target["note"],
        },
    )
    await session.flush()
    return task


async def _attach_agent_message(
    session: AsyncSession, task: ChatTask, text: str
) -> UUID | None:
    if task.conversation_id is None:
        return None
    conversation = await session.get(Conversation, task.conversation_id)
    if conversation is None or conversation.workspace_id != task.workspace_id:
        return None
    input_payload = dict(task.input or {})
    message = Message(
        conversation_id=conversation.id,
        user_id=task.user_id,
        role="assistant",
        content=text,
        status="completed",
        provider_id=str(input_payload.get("provider_id") or ""),
        model=str(input_payload.get("model") or ""),
        mode="agent",
        mode_meta={
            "thinking_level": input_payload.get("thinking_level", "standard"),
            "agent_task_id": str(task.id),
        },
    )
    session.add(message)
    await session.flush()
    conversation.updated_at = datetime.now(UTC)
    return message.id


def _plan_step_done(plan: dict[str, Any], cursor: int) -> int:
    steps = list(plan.get("steps") or [])
    if cursor < len(steps):
        steps[cursor] = {**steps[cursor], "status": "done"}
    next_cursor = min(cursor + 1, len(steps))
    if next_cursor < len(steps):
        steps[next_cursor] = {**steps[next_cursor], "status": "running"}
    plan["steps"] = steps
    return next_cursor


async def execute_agent_task(task_id: UUID, provider_registry=None) -> None:
    from app.db import SessionLocal

    settings = get_settings()
    async with SessionLocal() as session:
        task = await session.get(ChatTask, task_id)
        if task is None:
            return
        if not await mark_task_started(session, task):
            return
        plan = dict(task.plan or {})
        input_payload = dict(task.input or {})
        checkpoint = dict(task.checkpoint or {})
        if not plan.get("confirmed") or not plan.get("steps"):
            await fail_task(session, task, "plan_not_confirmed", "Agent plan is not confirmed")
            return
        workspace_id = task.workspace_id
        user_id = task.user_id
        providers = provider_registry or await build_user_registry(
            session, workspace_id, user_id
        )
        provider_id = str(input_payload.get("provider_id") or "")
        model = str(input_payload.get("model") or "")
        try:
            provider = providers.get(provider_id)
        except Exception:
            await fail_task(session, task, "provider_not_found", "Provider is not available")
            return
        conversation_id = task.conversation_id
        agent_id = None
        if input_payload.get("agent_id"):
            try:
                agent_id = UUID(str(input_payload["agent_id"]))
            except ValueError:
                agent_id = None
        goal = str(input_payload.get("goal") or task.title)
        thinking_level = str(input_payload.get("thinking_level") or "standard")
        max_steps = min(
            int(input_payload.get("max_steps") or settings.agent_task_max_steps),
            settings.agent_task_max_steps,
        )
        kb_ids: list[UUID] = []
        for raw in input_payload.get("kb_ids") or []:
            try:
                kb_ids.append(UUID(str(raw)))
            except ValueError:
                continue
        agent = await _resolve_agent(session, workspace_id, user_id, agent_id)
        tool_registry, tool_names = await _build_tools(
            session,
            workspace_id=workspace_id,
            agent=agent,
            plugin_ids=[str(item) for item in input_payload.get("plugin_ids") or []],
            kb_ids=kb_ids,
        )
        tool_context = ToolContext(
            workspace_id=workspace_id,
            user_id=user_id,
            kb_ids=kb_ids,
            conversation_id=conversation_id,
            agent_id=agent_id,
            citations=[],
        )
        exchanges = [item for item in checkpoint.get("exchanges") or [] if isinstance(item, dict)]
        tool_records = [
            item for item in checkpoint.get("tool_records") or [] if isinstance(item, dict)
        ]
        llm_calls = int(checkpoint.get("llm_calls") or 0)
        tool_calls = int(checkpoint.get("tool_calls") or 0)
        tokens = int(checkpoint.get("tokens") or 0)
        plan_cursor = int(checkpoint.get("plan_cursor") or 0)
        pending_approval = checkpoint.get("pending_approval")
        pending_tool = checkpoint.get("pending_tool")
        system_prompt = _system_prompt(
            goal=goal,
            agent=agent,
            registry=tool_registry,
            allowed=tool_names,
            plan=plan,
        )

    while True:
        checkpoint_data = {
            "exchanges": exchanges,
            "tool_records": tool_records,
            "llm_calls": llm_calls,
            "tool_calls": tool_calls,
            "tokens": tokens,
            "plan_cursor": plan_cursor,
        }
        if pending_approval:
            checkpoint_data["pending_approval"] = pending_approval
        if pending_tool:
            checkpoint_data["pending_tool"] = pending_tool
        async with SessionLocal() as session:
            current = await session.get(ChatTask, task_id)
            if current is None:
                return
            if not await checkpoint_or_stop(session, current, checkpoint_data, plan_cursor):
                return
            await session.commit()

        if pending_approval is not None:
            status = str(pending_approval.get("status") or "pending")
            if status == "pending":
                async with SessionLocal() as session:
                    current = await session.get(ChatTask, task_id)
                    if current is None:
                        return
                    current.status = "waiting_approval"
                    current.lease_expires_at = None
                    current.checkpoint = {
                        **dict(current.checkpoint or {}),
                        **checkpoint_data,
                    }
                    await session.commit()
                return
            if pending_tool is None:
                pending_approval = None
                continue
            tool_name = str(pending_tool.get("tool") or "")
            arguments = (
                pending_tool.get("arguments")
                if isinstance(pending_tool.get("arguments"), dict)
                else {}
            )
            if status == "rejected":
                note = str(pending_approval.get("note") or "")
                observation = _observation(
                    "", False, f"User rejected this tool call. {note}".strip()
                )
                exchanges = [
                    *exchanges,
                    {"role": "assistant", "raw": _tool_turn(tool_name, arguments)},
                    {"role": "tool", "observation": observation},
                ]
                tool_records = [
                    *tool_records,
                    {
                        "tool": tool_name,
                        "ok": False,
                        "error_code": "approval_rejected",
                        "arguments": arguments,
                    },
                ]
                pending_approval = None
                pending_tool = None
                async with SessionLocal() as session:
                    current = await session.get(ChatTask, task_id)
                    if current is None:
                        return
                    await append_event(
                        session,
                        current.id,
                        "agent_tool_result",
                        {
                            "tool": tool_name,
                            "ok": False,
                            "error_code": "approval_rejected",
                            "output": "",
                        },
                    )
                    current.checkpoint = {
                        **dict(current.checkpoint or {}),
                        "exchanges": exchanges,
                        "tool_records": tool_records,
                        "pending_approval": None,
                        "pending_tool": None,
                    }
                    await session.commit()
                continue
            async with SessionLocal() as session:
                current = await session.get(ChatTask, task_id)
                if current is None:
                    return
                await append_event(
                    session,
                    current.id,
                    "agent_tool_call",
                    {"tool": tool_name, "arguments": arguments, "approved": True},
                )
                await session.commit()
            result = await tool_registry.execute(tool_name, arguments, tool_context)
            observation = _observation(result.output, result.ok, result.error)
            exchanges = [
                *exchanges,
                {"role": "assistant", "raw": _tool_turn(tool_name, arguments)},
                {"role": "tool", "observation": observation},
            ]
            tool_records = [
                *tool_records,
                {
                    "tool": tool_name,
                    "ok": result.ok,
                    "error_code": result.error_code,
                    "arguments": arguments,
                    "output": result.output[:1000],
                },
            ]
            tool_calls += 1
            plan_cursor = _plan_step_done(plan, plan_cursor)
            pending_approval = None
            pending_tool = None
            async with SessionLocal() as session:
                current = await session.get(ChatTask, task_id)
                if current is None:
                    return
                current.plan = plan
                current.checkpoint = {
                    **dict(current.checkpoint or {}),
                    "exchanges": exchanges,
                    "tool_records": tool_records,
                    "tool_calls": tool_calls,
                    "plan_cursor": plan_cursor,
                    "pending_approval": None,
                    "pending_tool": None,
                }
                await append_event(
                    session,
                    current.id,
                    "agent_tool_result",
                    {
                        "tool": tool_name,
                        "ok": result.ok,
                        "error_code": result.error_code,
                        "output": result.output[:500],
                    },
                )
                await touch_lease(current)
                await session.commit()
            continue

        if llm_calls >= max_steps:
            async with SessionLocal() as session:
                current = await session.get(ChatTask, task_id)
                if current is None:
                    return
                await fail_task(
                    session,
                    current,
                    "agent_step_limit",
                    f"Agent exceeded the {max_steps}-step limit",
                )
            return
        if tool_calls >= settings.agent_task_max_tool_calls:
            async with SessionLocal() as session:
                current = await session.get(ChatTask, task_id)
                if current is None:
                    return
                await fail_task(
                    session,
                    current,
                    "agent_tool_limit",
                    "Agent exceeded the tool-call limit",
                )
            return

        messages = [ChatMessage(role="system", content=system_prompt)]
        messages.append(ChatMessage(role="user", content=goal))
        for item in exchanges:
            if item.get("role") == "assistant":
                messages.append(
                    ChatMessage(role="assistant", content=str(item.get("raw") or ""))
                )
            else:
                messages.append(
                    ChatMessage(role="user", content=str(item.get("observation") or ""))
                )
        llm_calls += 1
        async with SessionLocal() as session:
            current = await session.get(ChatTask, task_id)
            if current is None:
                return
            await append_event(
                session,
                current.id,
                "agent_step_started",
                {"index": llm_calls, "total": max_steps},
            )
            await touch_lease(current)
            await session.commit()
        completion = ModelCompletion(
            provider=provider,
            model=model,
            messages=messages,
            opts={
                "temperature": 0.2,
                "max_tokens": MODEL_STEP_MAX_TOKENS,
                **thinking_provider_opts(thinking_level),
            },
            workspace_id=workspace_id,
            user_id=user_id,
            source=SOURCE_AGENT_TASK,
        )
        metrics = await completion.run()
        if metrics.status != "completed":
            async with SessionLocal() as session:
                current = await session.get(ChatTask, task_id)
                if current is None:
                    return
                await fail_task(
                    session,
                    current,
                    metrics.error_code or "agent_step_failed",
                    "Agent model call failed",
                )
            return
        tokens += (metrics.prompt_tokens or 0) + (metrics.completion_tokens or 0)
        if tokens > settings.agent_task_max_total_tokens:
            async with SessionLocal() as session:
                current = await session.get(ChatTask, task_id)
                if current is None:
                    return
                await fail_task(
                    session,
                    current,
                    "agent_token_limit",
                    "Agent exceeded the token limit",
                )
            return
        parsed = parse_agent_output(metrics.content)
        if isinstance(parsed, FinalAnswer):
            text = parsed.content.strip()
            if not text:
                async with SessionLocal() as session:
                    current = await session.get(ChatTask, task_id)
                    if current is None:
                        return
                    await fail_task(
                        session,
                        current,
                        "agent_empty_output",
                        "Agent finished without an answer",
                    )
                return
            steps = list(plan.get("steps") or [])
            steps = [
                {
                    **step,
                    "status": (
                        "done"
                        if step.get("status") in {"done", "running"}
                        else "skipped"
                    ),
                }
                for step in steps
            ]
            plan["steps"] = steps
            artifacts = [
                {
                    "type": "code",
                    "title": block["title"],
                    "language": block["language"],
                    "content": block["code"],
                }
                for block in extract_code_blocks(text)
            ]
            async with SessionLocal() as session:
                current = await session.get(ChatTask, task_id)
                if current is None:
                    return
                message_id = await _attach_agent_message(session, current, text)
                current.plan = plan
                current.checkpoint = {
                    **dict(current.checkpoint or {}),
                    "exchanges": exchanges,
                    "tool_records": tool_records,
                    "llm_calls": llm_calls,
                    "tool_calls": tool_calls,
                    "tokens": tokens,
                    "plan_cursor": plan_cursor,
                }
                result = {
                    "title": current.title,
                    "text": text,
                    "artifacts": artifacts,
                    "tool_records": tool_records,
                    "message_id": str(message_id) if message_id is not None else None,
                    "token_usage": tokens,
                }
                await finish_task(
                    session,
                    current,
                    result,
                    "agent_artifact_ready",
                    {"artifacts": len(artifacts), "tool_calls": tool_calls},
                )
            return

        assert isinstance(parsed, ToolCall)
        tool_name = parsed.tool
        arguments = parsed.arguments
        async with SessionLocal() as session:
            current = await session.get(ChatTask, task_id)
            if current is None:
                return
            if tool_name not in tool_names or not tool_registry.has(tool_name):
                observation = _observation(
                    "", False, f"Tool {tool_name} is not allowed for this task"
                )
                exchanges = [
                    *exchanges,
                    {"role": "assistant", "raw": metrics.content},
                    {"role": "tool", "observation": observation},
                ]
                tool_records = [
                    *tool_records,
                    {"tool": tool_name, "ok": False, "error_code": "tool_not_allowed"},
                ]
                current.checkpoint = {
                    **dict(current.checkpoint or {}),
                    "exchanges": exchanges,
                    "tool_records": tool_records,
                    "llm_calls": llm_calls,
                    "tokens": tokens,
                }
                await append_event(
                    session,
                    current.id,
                    "agent_tool_result",
                    {"tool": tool_name, "ok": False, "error_code": "tool_not_allowed"},
                )
                await session.commit()
                continue
            spec = tool_registry.get(tool_name)
            risk = spec.risk if spec is not None else "low"
            if risk == "high":
                approval = _approval_record(tool_name, arguments, risk)
                approvals = [
                    *[
                        item
                        for item in (current.plan or {}).get("approvals", [])
                        if isinstance(item, dict)
                    ],
                    approval,
                ]
                plan["approvals"] = approvals
                current.plan = plan
                current.status = "waiting_approval"
                current.lease_expires_at = None
                current.checkpoint = {
                    **dict(current.checkpoint or {}),
                    "exchanges": exchanges,
                    "tool_records": tool_records,
                    "llm_calls": llm_calls,
                    "tool_calls": tool_calls,
                    "tokens": tokens,
                    "plan_cursor": plan_cursor,
                    "pending_approval": approval,
                    "pending_tool": {"tool": tool_name, "arguments": arguments},
                }
                await append_event(
                    session,
                    current.id,
                    "approval_required",
                    approval,
                )
                await session.commit()
                return
            await append_event(
                session,
                current.id,
                "agent_tool_call",
                {"tool": tool_name, "arguments": arguments, "approved": False},
            )
            await session.commit()

        result = await tool_registry.execute(tool_name, arguments, tool_context)
        observation = _observation(result.output, result.ok, result.error)
        exchanges = [
            *exchanges,
            {"role": "assistant", "raw": metrics.content},
            {"role": "tool", "observation": observation},
        ]
        tool_records = [
            *tool_records,
            {
                "tool": tool_name,
                "ok": result.ok,
                "error_code": result.error_code,
                "arguments": arguments,
                "output": result.output[:1000],
            },
        ]
        tool_calls += 1
        plan_cursor = _plan_step_done(plan, plan_cursor)
        async with SessionLocal() as session:
            current = await session.get(ChatTask, task_id)
            if current is None:
                return
            current.plan = plan
            current.checkpoint = {
                **dict(current.checkpoint or {}),
                "exchanges": exchanges,
                "tool_records": tool_records,
                "llm_calls": llm_calls,
                "tool_calls": tool_calls,
                "tokens": tokens,
                "plan_cursor": plan_cursor,
            }
            await append_event(
                session,
                current.id,
                "agent_tool_result",
                {
                    "tool": tool_name,
                    "ok": result.ok,
                    "error_code": result.error_code,
                    "output": result.output[:500],
                },
            )
            await touch_lease(current)
            await session.commit()