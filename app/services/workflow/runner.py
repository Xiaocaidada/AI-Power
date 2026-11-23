import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.agents.registry import SUPERVISOR_AGENT, AgentRegistry
from app.clients import RedisLike
from app.config import get_settings
from app.db import SessionLocal
from app.metrics import record_usage_metrics
from app.models import WorkflowNodeRun, WorkflowRun
from app.providers.base import ChatMessage, ProviderError, Usage
from app.providers.registry import ProviderRegistry
from app.services.agent import AgentFailure, AgentRunner
from app.services.budget import check_workspace_budget
from app.services.custom_agents import (
    CustomAgentError,
    build_agent_spec,
    get_custom_agent,
)
from app.services.plugins import build_plugin_tools_for_ids, plugin_tool_names
from app.services.usage_ledger import SOURCE_WORKFLOW, write_usage_event
from app.services.webhooks import enqueue_event
from app.services.workflow.schema import (
    AgentNodeConfig,
    ConditionNodeConfig,
    KbSearchNodeConfig,
    LLMNodeConfig,
    ToolNodeConfig,
    WorkflowDefinition,
    WorkflowNode,
)
from app.tools.base import ToolContext, ToolRegistry

logger = logging.getLogger(__name__)

TEMPLATE_VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
SUMMARY_MAX_CHARS = 500


@dataclass(frozen=True, slots=True)
class WorkflowEvent:
    kind: str
    data: dict[str, object]


@dataclass(frozen=True, slots=True)
class NodeOutcome:
    status: str
    output: str = ""
    error_code: str | None = None
    attempts: int = 1
    duration_ms: float = 0.0
    input_summary: str = ""


class NodeFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class RunCancelled(Exception):
    """Raised at a node boundary after a cancellation request."""

    def __init__(self) -> None:
        super().__init__("Run cancelled")


class WorkflowRunner:
    def __init__(
        self,
        *,
        run_id: UUID,
        workflow_id: UUID,
        version: int,
        definition: WorkflowDefinition,
        provider_registry: ProviderRegistry,
        tool_registry: ToolRegistry,
        agent_registry: AgentRegistry,
        workspace_id: UUID,
        user_id: UUID,
        kb_id: UUID | None,
        redis: RedisLike,
        input_text: str,
        quota_guard: Callable[[], Awaitable[None]] | None = None,
        api_key_id: UUID | None = None,
    ) -> None:
        self._run_id = run_id
        self._workflow_id = workflow_id
        self._version = version
        self._definition = definition
        self._providers = provider_registry
        self._tools = tool_registry
        self._agents = agent_registry
        self._workspace_id = workspace_id
        self._user_id = user_id
        self._kb_id = kb_id
        self._redis = redis
        self._input = input_text
        self._quota_guard = quota_guard
        self._api_key_id = api_key_id
        self._settings = get_settings()
        self._outputs: dict[str, str] = {}
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._cost = 0.0

    async def run(self) -> AsyncIterator[WorkflowEvent]:
        started = time.perf_counter()
        yield WorkflowEvent(
            "workflow_start",
            {
                "run_id": str(self._run_id),
                "workflow_id": str(self._workflow_id),
                "version": self._version,
            },
        )
        try:
            async for event in self._run_graph():
                yield event
            await self._check_cancel()
        except asyncio.CancelledError:
            await self._finish_run("cancelled", 0.0, "cancelled")
            raise
        except RunCancelled:
            total_ms = _elapsed_ms(started)
            await self._finish_run("cancelled", total_ms, "cancelled")
            yield self._end_event("cancelled", total_ms, "cancelled")
            return
        except NodeFailure as exc:
            total_ms = _elapsed_ms(started)
            await self._finish_run("failed", total_ms, exc.code)
            yield self._end_event("failed", total_ms, exc.code)
            return
        except Exception:
            logger.exception("workflow run %s failed unexpectedly", self._run_id)
            total_ms = _elapsed_ms(started)
            await self._finish_run("failed", total_ms, "internal_error")
            yield self._end_event("failed", total_ms, "internal_error")
            return
        total_ms = _elapsed_ms(started)
        await self._finish_run("completed", total_ms, None)
        yield self._end_event("completed", total_ms, None)

    def _end_event(self, status: str, total_ms: float, error_code: str | None) -> WorkflowEvent:
        data: dict[str, object] = {
            "run_id": str(self._run_id),
            "status": status,
            "total_ms": total_ms,
            "prompt_tokens": self._prompt_tokens,
            "completion_tokens": self._completion_tokens,
            "cost": self._cost,
            "output": _truncate(self._final_output(), SUMMARY_MAX_CHARS),
        }
        if error_code is not None:
            data["error_code"] = error_code
        return WorkflowEvent("workflow_end", data)

    async def _run_graph(self) -> AsyncIterator[WorkflowEvent]:
        await self._check_cancel()
        nodes = self._definition.node_map()
        incoming = self._definition.incoming()
        outgoing = self._definition.outgoing()
        states: dict[str, str] = {node_id: "pending" for node_id in nodes}
        edge_state: dict[tuple[str, str], bool | None] = {
            (edge.from_node, edge.to): None for edges in outgoing.values() for edge in edges
        }
        entry = next(node_id for node_id, edges in incoming.items() if not edges)
        states[entry] = "ready"
        ready: list[str] = [entry]
        running: dict[asyncio.Task, str] = {}
        semaphore = asyncio.Semaphore(self._settings.workflow_parallel_limit)

        try:
            while any(state in {"pending", "ready", "running"} for state in states.values()):
                await self._check_cancel()
                progressed = True
                while progressed:
                    progressed = False
                    for node_id, node in nodes.items():
                        if states[node_id] != "pending":
                            continue
                        edges = incoming[node_id]
                        if not edges:
                            continue
                        if any(edge_state[(edge.from_node, node_id)] is None for edge in edges):
                            continue
                        active = [
                            edge for edge in edges if edge_state[(edge.from_node, node_id)] is True
                        ]
                        if not active:
                            states[node_id] = "skipped"
                            await self._record_skipped(node)
                            yield _node_end(self._run_id, node.id, "skipped", 0, 0.0)
                            for edge in outgoing[node.id]:
                                edge_state[(node.id, edge.to)] = False
                            progressed = True
                        elif all(states[edge.from_node] == "completed" for edge in active):
                            states[node_id] = "ready"
                            ready.append(node_id)
                            progressed = True

                while ready:
                    node_id = ready.pop(0)
                    if states[node_id] != "ready":
                        continue
                    states[node_id] = "running"
                    yield WorkflowEvent(
                        "node_start",
                        {
                            "run_id": str(self._run_id),
                            "node_id": node_id,
                            "node_type": nodes[node_id].type,
                        },
                    )
                    task = asyncio.create_task(
                        self._execute_with_semaphore(nodes[node_id], semaphore)
                    )
                    running[task] = node_id

                if not running:
                    break
                done, _ = await asyncio.wait(set(running), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    node_id = running.pop(task)
                    outcome = task.result()
                    if outcome.status == "failed":
                        states[node_id] = "failed"
                        yield _node_end(
                            self._run_id,
                            node_id,
                            "failed",
                            outcome.attempts,
                            outcome.duration_ms,
                            outcome.output,
                            outcome.error_code,
                        )
                        await _cancel_tasks(running)
                        raise NodeFailure(
                            outcome.error_code or "node_failed", f"Node {node_id} failed"
                        )
                    states[node_id] = "completed"
                    self._outputs[node_id] = outcome.output
                    yield _node_end(
                        self._run_id,
                        node_id,
                        "completed",
                        outcome.attempts,
                        outcome.duration_ms,
                        outcome.output,
                    )
                    for edge in outgoing[node_id]:
                        if nodes[node_id].type == "condition":
                            edge_state[(node_id, edge.to)] = edge.when == outcome.output
                        else:
                            edge_state[(node_id, edge.to)] = True
        except (asyncio.CancelledError, RunCancelled):
            await _cancel_tasks(running)
            raise

    async def _check_cancel(self) -> None:
        try:
            async with SessionLocal() as session:
                requested = (
                    await session.execute(
                        select(WorkflowRun.cancel_requested_at).where(
                            WorkflowRun.id == self._run_id
                        )
                    )
                ).scalar_one_or_none()
        except Exception:
            logger.warning("failed to check workflow cancellation", exc_info=True)
            return
        if requested is not None:
            raise RunCancelled()

    async def _execute_with_semaphore(
        self, node: WorkflowNode, semaphore: asyncio.Semaphore
    ) -> NodeOutcome:
        async with semaphore:
            return await self._execute_node_with_retries(node)

    async def _execute_node_with_retries(self, node: WorkflowNode) -> NodeOutcome:
        started = time.perf_counter()
        node_run_id = await self._start_node_run(node)
        attempts = 0
        last_error: NodeFailure | None = None
        output = ""
        input_summary = ""
        while attempts < self._settings.workflow_node_attempts:
            attempts += 1
            try:
                output, input_summary = await asyncio.wait_for(
                    self._execute_node(node, node_run_id),
                    timeout=self._settings.workflow_node_timeout_seconds,
                )
                last_error = None
                break
            except TimeoutError:
                last_error = NodeFailure("node_timeout", f"Node {node.id} timed out")
            except ProviderError as exc:
                last_error = NodeFailure(exc.code, exc.message)
            except NodeFailure as exc:
                last_error = exc
                break
        duration_ms = _elapsed_ms(started)
        if last_error is not None:
            await self._finish_node_run(
                node_run_id,
                "failed",
                attempts,
                duration_ms,
                input_summary,
                "",
                last_error.code,
            )
            return NodeOutcome(
                status="failed",
                error_code=last_error.code,
                attempts=attempts,
                duration_ms=duration_ms,
                input_summary=input_summary,
            )
        await self._finish_node_run(
            node_run_id, "completed", attempts, duration_ms, input_summary, output, None
        )
        return NodeOutcome(
            status="completed",
            output=output,
            attempts=attempts,
            duration_ms=duration_ms,
            input_summary=input_summary,
        )

    async def _execute_node(self, node: WorkflowNode, node_run_id: UUID) -> tuple[str, str]:
        if node.type == "llm":
            config = LLMNodeConfig.model_validate(node.config)
            prompt = self._render(config.prompt)
            system_prompt = self._render(config.system_prompt) if config.system_prompt else None
            await self._guard_quota()
            output, usage = await self._call_llm(config, prompt, system_prompt)
            await self._record_usage(config.provider_id, config.model, usage, node_run_id)
            return output, prompt
        if node.type == "start":
            return self._input, "start"
        if node.type == "output":
            return self._join_outputs(node) or self._input, "output"
        if node.type == "kb_search":
            config = KbSearchNodeConfig.model_validate(node.config)
            query = self._render(config.query)
            return await self._search_knowledge(query, config.kb_ids), query
        if node.type == "tool":
            config = ToolNodeConfig.model_validate(node.config)
            arguments = {key: self._render(value) for key, value in config.arguments.items()}
            return await self._call_tool(config.tool, arguments), _arguments_summary(arguments)
        if node.type == "agent":
            config = AgentNodeConfig.model_validate(node.config)
            task = self._render(config.task)
            return await self._call_agent(config, task, node_run_id), task
        if node.type == "condition":
            config = ConditionNodeConfig.model_validate(node.config)
            left = self._render(config.left)
            right = self._render(config.right)
            return _evaluate_condition(left, config.operator, right), left
        if node.type == "join":
            return self._join_outputs(node), "join"
        if node.type == "parallel":
            return self._join_outputs(node) or self._input, "fan-out"
        raise NodeFailure("unsupported_node_type", f"Unsupported node type: {node.type}")

    def _render(self, text: str) -> str:
        return render_template(text, {"input": self._input, **self._outputs})

    async def _call_llm(
        self, config: LLMNodeConfig, prompt: str, system_prompt: str | None
    ) -> tuple[str, Usage]:
        provider = self._providers.get(config.provider_id)
        messages: list[ChatMessage] = []
        if system_prompt:
            messages.append(ChatMessage(role="system", content=system_prompt))
        messages.append(ChatMessage(role="user", content=prompt))
        parts: list[str] = []
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        async for chunk in provider.stream_chat(messages, config.model):
            if chunk.delta:
                parts.append(chunk.delta)
            if chunk.usage is not None:
                prompt_tokens = (prompt_tokens or 0) + (chunk.usage.prompt_tokens or 0)
                completion_tokens = (completion_tokens or 0) + (chunk.usage.completion_tokens or 0)
        return "".join(parts), Usage(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )

    async def _call_agent(self, config: AgentNodeConfig, task: str, node_run_id: UUID) -> str:
        provider_id = config.provider_id
        model = config.model
        kb_ids = list(config.kb_ids)
        plugin_tools = []
        agent_registry = self._agents
        root_agent = None
        extra_tools = list(config.tools)
        if config.agent_id is not None:
            async with SessionLocal() as session:
                try:
                    agent = await get_custom_agent(
                        session,
                        self._workspace_id,
                        config.agent_id,
                        self._user_id,
                    )
                except CustomAgentError as exc:
                    raise NodeFailure(exc.code, exc.message) from None
                plugin_tools = await build_plugin_tools_for_ids(
                    session, self._workspace_id, list(agent.plugin_ids)
                )
                provider_id = provider_id or agent.default_provider_id
                model = model or agent.default_model
                if not kb_ids:
                    kb_ids = [UUID(item) for item in agent.kb_ids]
                    if not kb_ids and agent.default_kb_id is not None:
                        kb_ids = [agent.default_kb_id]
                spec = build_agent_spec(
                    agent, tuple([*extra_tools, *plugin_tool_names(plugin_tools)])
                )
                agent_registry = AgentRegistry([spec])
                root_agent = spec.name
        if not provider_id or not model or provider_id == "auto":
            raise NodeFailure(
                "agent_model_required", "Agent node requires an explicit provider and model"
            )
        provider = self._providers.get(provider_id)
        tool_registry = self._tools.with_tools(plugin_tools) if plugin_tools else self._tools
        runner = AgentRunner(
            provider=provider,
            model=model,
            tool_registry=tool_registry,
            agent_registry=agent_registry,
            context=ToolContext(
                workspace_id=self._workspace_id,
                user_id=self._user_id,
                kb_id=self._kb_id,
                kb_ids=kb_ids or None,
                redis=self._redis,
            ),
            quota_guard=self._quota_guard,
            root_agent=root_agent or SUPERVISOR_AGENT,
            max_steps=config.max_steps,
        )
        parts: list[str] = []
        try:
            async for event in runner.run([ChatMessage(role="user", content=task)]):
                if event.kind == "delta":
                    parts.append(str(event.data.get("text", "")))
        except AgentFailure as exc:
            raise NodeFailure(exc.code, exc.message) from None
        await self._record_usage(provider_id, model, runner.usage, node_run_id)
        return "".join(parts)

    async def _call_tool(
        self,
        tool: str,
        arguments: dict[str, str],
        kb_ids: list[UUID] | None = None,
    ) -> str:
        result = await self._tools.execute(
            tool,
            arguments,
            ToolContext(
                workspace_id=self._workspace_id,
                user_id=self._user_id,
                kb_id=self._kb_id,
                kb_ids=kb_ids,
                redis=self._redis,
            ),
        )
        if not result.ok:
            raise NodeFailure(result.error_code or "tool_error", result.error or "Tool failed")
        return result.output

    async def _search_knowledge(self, query: str, kb_ids: list[UUID] | None = None) -> str:
        resolved = kb_ids or ([self._kb_id] if self._kb_id is not None else [])
        if not resolved:
            raise NodeFailure("no_knowledge_base", "A kb_search node requires a knowledge base")
        return await self._call_tool(
            "kb_search",
            {"query": query},
            kb_ids=resolved,
        )

    async def _guard_quota(self) -> None:
        if self._quota_guard is None:
            return
        try:
            await self._quota_guard()
        except HTTPException as exc:
            detail = exc.detail
            code = detail.get("code") if isinstance(detail, dict) else None
            raise NodeFailure(str(code or "quota_exceeded"), "Quota exceeded") from None

    async def _record_usage(
        self, provider_id: str, model: str, usage: Usage, node_run_id: UUID
    ) -> None:
        self._prompt_tokens += usage.prompt_tokens or 0
        self._completion_tokens += usage.completion_tokens or 0
        try:
            async with SessionLocal() as session:
                written = await write_usage_event(
                    session,
                    workspace_id=self._workspace_id,
                    user_id=self._user_id,
                    source=SOURCE_WORKFLOW,
                    provider_id=provider_id,
                    model=model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    api_key_id=self._api_key_id,
                    workflow_node_run_id=node_run_id,
                )
                await session.commit()
        except Exception:
            logger.exception("failed to record workflow node usage")
            return
        if written is None:
            return
        self._cost += written.cost
        record_usage_metrics(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost=written.cost,
            provider_id=provider_id,
            model=model,
            source=SOURCE_WORKFLOW,
        )

    def _join_outputs(self, node: WorkflowNode) -> str:
        incoming = self._definition.incoming().get(node.id, [])
        parts = [
            self._outputs[edge.from_node] for edge in incoming if edge.from_node in self._outputs
        ]
        return "\n".join(parts)

    def _final_output(self) -> str:
        outgoing = self._definition.outgoing()
        terminals = [node_id for node_id, edges in outgoing.items() if not edges]
        completed = [self._outputs[node_id] for node_id in terminals if node_id in self._outputs]
        if completed:
            return "\n".join(completed)
        return next(reversed(self._outputs.values()), "")

    async def _start_node_run(self, node: WorkflowNode) -> UUID:
        try:
            async with SessionLocal() as session:
                record = WorkflowNodeRun(
                    run_id=self._run_id,
                    node_id=node.id,
                    node_type=node.type,
                    status="running",
                )
                session.add(record)
                await session.commit()
                await session.refresh(record)
                return record.id
        except Exception:
            logger.exception("failed to create workflow node run")
            return UUID(int=0)

    async def _finish_node_run(
        self,
        node_run_id: UUID,
        status: str,
        attempts: int,
        duration_ms: float,
        input_summary: str,
        output: str,
        error_code: str | None,
    ) -> None:
        if node_run_id == UUID(int=0):
            return
        try:
            async with SessionLocal() as session:
                record = await session.get(WorkflowNodeRun, node_run_id)
                if record is None:
                    return
                record.status = status
                record.attempts = attempts
                record.duration_ms = duration_ms
                record.input_summary = _truncate(input_summary, SUMMARY_MAX_CHARS)
                record.output_summary = _truncate(output, SUMMARY_MAX_CHARS)
                record.error_code = error_code
                await session.commit()
        except Exception:
            logger.exception("failed to finalize workflow node run")

    async def _record_skipped(self, node: WorkflowNode) -> None:
        try:
            async with SessionLocal() as session:
                session.add(
                    WorkflowNodeRun(
                        run_id=self._run_id,
                        node_id=node.id,
                        node_type=node.type,
                        status="skipped",
                    )
                )
                await session.commit()
        except Exception:
            logger.exception("failed to record skipped workflow node")

    async def _finish_run(self, status: str, total_ms: float, error_code: str | None) -> None:
        try:
            async with SessionLocal() as session:
                run = await session.get(WorkflowRun, self._run_id)
                if run is None:
                    return
                run.status = status
                run.error_code = error_code
                run.total_ms = total_ms
                run.prompt_tokens = self._prompt_tokens
                run.completion_tokens = self._completion_tokens
                run.cost = round(self._cost, 6)
                run.finished_at = datetime.now(UTC)
                await session.commit()
                try:
                    await check_workspace_budget(session, self._redis, self._workspace_id)
                    await session.commit()
                except Exception:
                    logger.warning("workflow budget check failed", exc_info=True)
                await enqueue_event(
                    run.workspace_id,
                    "workflow.completed",
                    {
                        "run_id": str(run.id),
                        "workflow_id": str(run.workflow_id),
                        "status": run.status,
                        "error_code": run.error_code,
                        "total_ms": run.total_ms,
                        "prompt_tokens": run.prompt_tokens,
                        "completion_tokens": run.completion_tokens,
                        "cost": run.cost,
                    },
                )
        except Exception:
            logger.exception("failed to finalize workflow run")


def _node_end(
    run_id: UUID,
    node_id: str,
    status: str,
    attempts: int,
    duration_ms: float,
    output: str | None = None,
    error_code: str | None = None,
) -> WorkflowEvent:
    data: dict[str, object] = {
        "run_id": str(run_id),
        "node_id": node_id,
        "status": status,
        "attempts": attempts,
        "duration_ms": duration_ms,
    }
    if output is not None:
        data["output"] = _truncate(output, SUMMARY_MAX_CHARS)
    if error_code is not None:
        data["error_code"] = error_code
    return WorkflowEvent("node_end", data)


async def _cancel_tasks(running: dict[asyncio.Task, str]) -> None:
    tasks = list(running)
    running.clear()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def render_template(text: str, values: dict[str, str]) -> str:
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            missing.append(name)
            return match.group(0)
        return str(values[name])

    rendered = TEMPLATE_VARIABLE.sub(replace, text)
    if missing:
        raise NodeFailure(
            "invalid_template",
            "Unknown template variables: " + ", ".join(sorted(set(missing))),
        )
    return rendered


def _evaluate_condition(left: str, operator: str, right: str) -> str:
    if operator == "equals":
        result = left == right
    elif operator == "not_equals":
        result = left != right
    elif operator == "contains":
        result = right in left
    elif operator == "not_contains":
        result = right not in left
    elif operator == "not_empty":
        result = left.strip() != ""
    else:
        result = left.strip() == ""
    return "true" if result else "false"


def _arguments_summary(arguments: dict[str, str]) -> str:
    return json.dumps(arguments, ensure_ascii=False)[:SUMMARY_MAX_CHARS]


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
