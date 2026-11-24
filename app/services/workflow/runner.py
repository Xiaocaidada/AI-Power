import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update

from app.agents.registry import SUPERVISOR_AGENT, AgentRegistry
from app.clients import RedisLike
from app.config import get_settings
from app.db import SessionLocal
from app.metrics import record_usage_metrics
from app.models import (
    DatabaseConnection,
    McpServer,
    Workflow,
    WorkflowNodeRun,
    WorkflowReview,
    WorkflowRun,
)
from app.providers.base import ChatMessage, ProviderError, Usage
from app.providers.registry import ProviderRegistry
from app.services.agent import AgentFailure, AgentRunner
from app.services.agent_tools import build_mcp_tool_specs, is_mcp_tool
from app.services.budget import check_workspace_budget
from app.services.custom_agents import (
    CustomAgentError,
    build_agent_spec,
    get_custom_agent,
)
from app.services.database_nodes import DatabaseNodeError, execute_read_query
from app.services.generation import normalize_generation_settings
from app.services.mcp import (
    McpError,
    call_mcp_tool,
    get_mcp_prompt,
    read_mcp_resource,
)
from app.services.memories import (
    MemoryError,
    create_memory,
    find_memory_by_title,
    get_memory_settings,
    record_memory_usage,
    select_memories,
    update_memory,
    validate_memory_targets,
)
from app.services.memory_permissions import agent_memory_access
from app.services.outbound import OutboundError, request_outbound
from app.services.plugins import build_plugin_tools_for_ids, plugin_tool_names
from app.services.sandbox import SandboxError, evaluate_expression
from app.services.usage_ledger import SOURCE_WORKFLOW, write_usage_event
from app.services.webhooks import enqueue_event
from app.services.workflow.schema import (
    AgentNodeConfig,
    CodeNodeConfig,
    ConditionNodeConfig,
    DatabaseNodeConfig,
    HttpNodeConfig,
    KbSearchNodeConfig,
    LLMNodeConfig,
    LoopNodeConfig,
    McpNodeConfig,
    McpPromptNodeConfig,
    McpResourceNodeConfig,
    MemoryReadNodeConfig,
    MemoryWriteNodeConfig,
    ReviewNodeConfig,
    ToolNodeConfig,
    WorkflowDefinition,
    WorkflowNode,
)
from app.tools.base import ToolContext, ToolRegistry

logger = logging.getLogger(__name__)

TEMPLATE_VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")
SUMMARY_MAX_CHARS = 500
EVENT_DRAIN_INTERVAL = 0.2


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
        resume_state: dict[str, object] | None = None,
        start_node_id: str | None = None,
        seed_outputs: dict[str, str] | None = None,
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
        self._start_node_id = start_node_id
        self._seed_outputs = dict(seed_outputs or {})
        self._outputs: dict[str, str] = dict(self._seed_outputs)
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._cost = 0.0
        self._events: asyncio.Queue[WorkflowEvent] = asyncio.Queue()
        self._resume_state = resume_state or {}
        self._pending_reviews: dict[str, dict[str, str]] = {}
        resume_reviews = self._resume_state.get("pending_reviews")
        if isinstance(resume_reviews, list):
            for item in resume_reviews:
                if isinstance(item, dict) and item.get("node_id") and item.get("review_id"):
                    self._pending_reviews[str(item["node_id"])] = {
                        "node_id": str(item["node_id"]),
                        "review_id": str(item["review_id"]),
                    }
        legacy_review = self._resume_state.get("pending_review")
        if isinstance(legacy_review, dict) and legacy_review.get("node_id"):
            self._pending_reviews.setdefault(
                str(legacy_review["node_id"]),
                {
                    "node_id": str(legacy_review["node_id"]),
                    "review_id": str(legacy_review.get("review_id", "")),
                },
            )
        self._live_states: dict[str, str] | None = None
        self._live_edge_state: dict[tuple[str, str], bool | None] | None = None

    def _emit(self, kind: str, data: dict[str, object]) -> None:
        self._events.put_nowait(WorkflowEvent(kind, data))

    async def run(self) -> AsyncIterator[WorkflowEvent]:
        started = time.perf_counter()
        yield WorkflowEvent(
            "workflow_start",
            {
                "run_id": str(self._run_id),
                "workflow_id": str(self._workflow_id),
                "version": self._version,
                "resumed": bool(self._resume_state),
            },
        )
        try:
            async for event in self._run_graph():
                yield event
            await self._check_cancel()
        except asyncio.CancelledError:
            await self._finish_run(
                "cancelled", 0.0, "cancelled", preserve_checkpoint=True
            )
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

    async def debug_node(self, node_id: str) -> NodeOutcome:
        node = self._definition.node_map().get(node_id)
        if node is None:
            raise NodeFailure("node_not_found", f"Node not found: {node_id}")
        if node.type == "review":
            raise NodeFailure(
                "review_node_requires_run",
                "Review nodes need a queued run and human reviewer",
            )
        return await self._execute_node_with_retries(node)

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
        ready: list[str] = []
        if self._start_node_id is not None:
            if self._start_node_id not in nodes:
                raise NodeFailure(
                    "start_node_not_found",
                    f"Start node not found: {self._start_node_id}",
                )
            for node_id in self._seed_outputs:
                if node_id not in states:
                    continue
                states[node_id] = "completed"
                for edge in outgoing[node_id]:
                    edge_state[(node_id, edge.to)] = True
            states[self._start_node_id] = "ready"
            ready.append(self._start_node_id)
        resume_states = self._resume_state.get("node_states")
        if self._start_node_id is None and isinstance(resume_states, dict):
            for node_id, status in resume_states.items():
                if node_id not in states:
                    continue
                if status == "completed":
                    states[node_id] = "completed"
                elif status == "skipped":
                    states[node_id] = "skipped"
                else:
                    states[node_id] = "pending"
            resume_outputs = self._resume_state.get("outputs")
            if isinstance(resume_outputs, dict):
                self._outputs.update(
                    {str(key): str(value) for key, value in resume_outputs.items()}
                )
            resume_edges = self._resume_state.get("edge_state")
            if isinstance(resume_edges, dict):
                for pair, value in resume_edges.items():
                    if not isinstance(pair, str) or "->" not in pair:
                        continue
                    source, target = pair.split("->", 1)
                    key = (source, target)
                    if key in edge_state and isinstance(value, bool):
                        edge_state[key] = value
        elif self._start_node_id is None:
            entry = next(node_id for node_id, edges in incoming.items() if not edges)
            states[entry] = "ready"
            ready.append(entry)
        self._live_states = states
        self._live_edge_state = edge_state
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
                            await self._save_checkpoint()
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
                done, _ = await asyncio.wait(
                    set(running),
                    timeout=EVENT_DRAIN_INTERVAL,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                while not self._events.empty():
                    yield self._events.get_nowait()
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
                    await self._save_checkpoint()
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
        if node.type == "review":
            # A human gate must not occupy a parallel slot while it waits.
            return await self._execute_node_with_retries(node)
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
                if node.type == "review":
                    # Review nodes own their timeout; the normal node budget would
                    # cancel a pending human approval far too early.
                    output, input_summary = await self._execute_node(node, node_run_id)
                elif node.type == "loop":
                    loop_config = LoopNodeConfig.model_validate(node.config)
                    iterations = min(
                        loop_config.max_iterations,
                        self._settings.workflow_loop_max_iterations,
                    )
                    output, input_summary = await asyncio.wait_for(
                        self._execute_node(node, node_run_id),
                        timeout=self._settings.workflow_node_timeout_seconds
                        * max(1, iterations),
                    )
                else:
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
            output, usage = await self._call_llm(
                config.provider_id, config.model, prompt, system_prompt
            )
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
        if node.type == "review":
            config = ReviewNodeConfig.model_validate(node.config)
            return await self._review_node(node, config, node_run_id)
        if node.type == "loop":
            config = LoopNodeConfig.model_validate(node.config)
            return await self._loop_node(node, config, node_run_id)
        if node.type == "http":
            config = HttpNodeConfig.model_validate(node.config)
            return await self._http_node(config)
        if node.type == "mcp":
            config = McpNodeConfig.model_validate(node.config)
            return await self._mcp_node(config)
        if node.type == "mcp_resource":
            config = McpResourceNodeConfig.model_validate(node.config)
            return await self._mcp_resource_node(config)
        if node.type == "mcp_prompt":
            config = McpPromptNodeConfig.model_validate(node.config)
            return await self._mcp_prompt_node(config)
        if node.type == "memory_read":
            config = MemoryReadNodeConfig.model_validate(node.config)
            return await self._memory_read(config)
        if node.type == "memory_write":
            config = MemoryWriteNodeConfig.model_validate(node.config)
            return await self._memory_write(config)
        if node.type == "code":
            config = CodeNodeConfig.model_validate(node.config)
            return await self._code_node(config)
        if node.type == "database":
            config = DatabaseNodeConfig.model_validate(node.config)
            return await self._database_node(config)
        raise NodeFailure("unsupported_node_type", f"Unsupported node type: {node.type}")

    def _render(self, text: str) -> str:
        return render_template(text, {"input": self._input, **self._outputs})

    def _render_extra(self, text: str, extra: dict[str, str]) -> str:
        return render_template(text, {"input": self._input, **self._outputs, **extra})

    async def _call_llm(
        self, provider_id: str, model: str, prompt: str, system_prompt: str | None
    ) -> tuple[str, Usage]:
        provider = self._providers.get(provider_id)
        messages: list[ChatMessage] = []
        if system_prompt:
            messages.append(ChatMessage(role="system", content=system_prompt))
        messages.append(ChatMessage(role="user", content=prompt))
        parts: list[str] = []
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        async for chunk in provider.stream_chat(messages, model):
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
        bound_agent = None
        generation_opts: dict[str, object] = {}
        mcp_tools = []
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
                bound_agent = agent
                if config.project_id is not None:
                    try:
                        await validate_memory_targets(
                            session,
                            self._workspace_id,
                            project_id=config.project_id,
                        )
                    except MemoryError as exc:
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
                generation_opts = normalize_generation_settings(
                    agent.generation_settings
                )
                mcp_tools = await build_mcp_tool_specs(
                    session, [*agent.tools, *extra_tools]
                )
        if not mcp_tools and any(is_mcp_tool(tool) for tool in extra_tools):
            async with SessionLocal() as session:
                mcp_tools = await build_mcp_tool_specs(session, extra_tools)
        if not provider_id or not model or provider_id == "auto":
            raise NodeFailure(
                "agent_model_required", "Agent node requires an explicit provider and model"
            )
        provider = self._providers.get(provider_id)
        tool_registry = self._tools.with_tools(plugin_tools) if plugin_tools else self._tools
        if mcp_tools:
            tool_registry = tool_registry.with_tools(mcp_tools)
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
                agent_id=bound_agent.id if bound_agent is not None else None,
                project_id=config.project_id,
                memory_access=(
                    agent_memory_access(bound_agent)
                    if bound_agent is not None
                    else None
                ),
                redis=self._redis,
            ),
            quota_guard=self._quota_guard,
            root_agent=root_agent or SUPERVISOR_AGENT,
            max_steps=config.max_steps,
            generation_opts=generation_opts,
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

    async def _review_node(
        self, node: WorkflowNode, config: ReviewNodeConfig, node_run_id: UUID
    ) -> tuple[str, str]:
        prompt = self._render(config.prompt)
        timeout = float(
            config.timeout_seconds or self._settings.workflow_review_timeout_seconds
        )
        resumed = self._pending_reviews.get(node.id)
        if resumed is not None:
            try:
                review_id = UUID(str(resumed.get("review_id", "")))
            except ValueError:
                raise NodeFailure("review_missing", "Review checkpoint is invalid") from None
            async with SessionLocal() as session:
                review = await session.get(WorkflowReview, review_id)
                if review is None:
                    raise NodeFailure("review_missing", "Review task no longer exists")
                expires_at = review.expires_at
                review_status = review.status
            remaining = timeout
            if expires_at is not None:
                remaining = (_as_utc(expires_at) - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                await self._close_review(review_id, "expired")
                self._pending_reviews.pop(node.id, None)
                raise NodeFailure("review_timeout", "Human review timed out")
            timeout = remaining
            if review_status == "pending":
                self._emit(
                    "review_requested",
                    {
                        "run_id": str(self._run_id),
                        "review_id": str(review_id),
                        "node_id": node.id,
                        "prompt": _truncate(prompt, SUMMARY_MAX_CHARS),
                    },
                )
        else:
            review_id = await self._create_review(node, node_run_id, prompt, timeout)
            self._pending_reviews[node.id] = {
                "node_id": node.id,
                "review_id": str(review_id),
            }
            await self._save_checkpoint()
            self._emit(
                "review_requested",
                {
                    "run_id": str(self._run_id),
                    "review_id": str(review_id),
                    "node_id": node.id,
                    "prompt": _truncate(prompt, SUMMARY_MAX_CHARS),
                },
            )
        deadline = time.monotonic() + timeout
        try:
            decided = await self._wait_for_review(review_id, deadline)
        except RunCancelled:
            await self._close_review(review_id, "cancelled")
            raise
        except asyncio.CancelledError:
            # Worker shutdown: keep the review pending so a resumed job can
            # pick it up from the saved checkpoint.
            raise
        if decided is None:
            await self._close_review(review_id, "expired")
            self._pending_reviews.pop(node.id, None)
            raise NodeFailure("review_timeout", "Human review timed out")
        self._pending_reviews.pop(node.id, None)
        self._emit(
            "review_resolved",
            {
                "run_id": str(self._run_id),
                "review_id": str(review_id),
                "node_id": node.id,
                "decision": decided["decision"],
            },
        )
        if decided["decision"] == "expired":
            raise NodeFailure("review_timeout", "Human review timed out")
        if decided["decision"] != "approved":
            raise NodeFailure("review_rejected", "Human review rejected the run")
        output = decided["output"] or decided["comment"] or prompt
        return output, f"review {review_id}"

    async def _create_review(
        self, node: WorkflowNode, node_run_id: UUID, prompt: str, timeout: float
    ) -> UUID:
        try:
            async with SessionLocal() as session:
                review = WorkflowReview(
                    run_id=self._run_id,
                    node_run_id=node_run_id if node_run_id != UUID(int=0) else None,
                    workspace_id=self._workspace_id,
                    node_id=node.id,
                    status="pending",
                    prompt=prompt,
                    expires_at=datetime.now(UTC) + timedelta(seconds=timeout),
                )
                session.add(review)
                if node_run_id != UUID(int=0):
                    node_run = await session.get(WorkflowNodeRun, node_run_id)
                    if node_run is not None:
                        node_run.status = "waiting_review"
                await session.commit()
                await session.refresh(review)
                return review.id
        except Exception:
            logger.exception("failed to create workflow review")
            raise NodeFailure("review_unavailable", "Could not create a review task") from None

    async def _wait_for_review(
        self, review_id: UUID, deadline: float
    ) -> dict[str, str] | None:
        while True:
            await self._check_cancel()
            async with SessionLocal() as session:
                review = await session.get(WorkflowReview, review_id)
                if review is None:
                    return None
                if review.status != "pending":
                    return {
                        "decision": review.decision or "rejected",
                        "comment": review.comment,
                        "output": review.output,
                    }
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(self._settings.workflow_review_poll_seconds)

    async def _close_review(self, review_id: UUID, status: str) -> None:
        try:
            async with SessionLocal() as session:
                review = await session.get(WorkflowReview, review_id)
                if review is not None and review.status == "pending":
                    review.status = status
                    review.decision = status
                    review.resolved_at = datetime.now(UTC)
                    await session.commit()
        except Exception:
            logger.warning("failed to close workflow review %s", review_id, exc_info=True)

    async def _loop_node(
        self, node: WorkflowNode, config: LoopNodeConfig, node_run_id: UUID
    ) -> tuple[str, str]:
        limit = min(config.max_iterations, self._settings.workflow_loop_max_iterations)
        if config.mode == "repeat":
            items = [str(index) for index in range(1, min(config.times, limit) + 1)]
        else:
            items = _parse_loop_items(self._render(config.items))[:limit]
        outputs: list[str] = []
        prompt_tokens = 0
        completion_tokens = 0
        billed = False
        for index, item in enumerate(items, start=1):
            extra = {
                "item": item,
                "index": str(index),
                "iteration": item,
                "count": str(len(items)),
            }
            if config.prompt.strip():
                prompt = self._render_extra(config.prompt, extra)
                system_prompt = (
                    self._render_extra(config.system_prompt, extra)
                    if config.system_prompt
                    else None
                )
                await self._guard_quota()
                assert config.provider_id is not None and config.model is not None
                text, usage = await self._call_llm(
                    config.provider_id, config.model, prompt, system_prompt
                )
                prompt_tokens += usage.prompt_tokens or 0
                completion_tokens += usage.completion_tokens or 0
                billed = True
            else:
                text = self._render_extra(item, extra)
            outputs.append(text)
            self._emit(
                "node_iteration",
                {
                    "run_id": str(self._run_id),
                    "node_id": node.id,
                    "index": index,
                    "total": len(items),
                    "output": _truncate(text, SUMMARY_MAX_CHARS),
                },
            )
            if config.until_operator is not None:
                right = self._render_extra(config.until_right, extra)
                if _evaluate_condition(text, config.until_operator, right) == "true":
                    break
        if billed:
            assert config.provider_id is not None and config.model is not None
            await self._record_usage(
                config.provider_id,
                config.model,
                Usage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                ),
                node_run_id,
            )
        return config.separator.join(outputs), f"loop {len(outputs)} iteration(s)"

    async def _http_node(self, config: HttpNodeConfig) -> tuple[str, str]:
        url = self._render(config.url)
        headers = {key: self._render(value) for key, value in config.headers.items()}
        body = self._render(config.body) if config.body else ""
        try:
            output = await request_outbound(
                config.method,
                url,
                headers=headers,
                body=body,
                timeout_seconds=config.timeout_seconds,
                settings=self._settings,
            )
        except OutboundError as exc:
            raise NodeFailure(exc.code, exc.message) from None
        return output, f"{config.method} {_redact_url(url)}"

    async def _mcp_node(self, config: McpNodeConfig) -> tuple[str, str]:
        arguments = {key: self._render(value) for key, value in config.arguments.items()}
        async with SessionLocal() as session:
            server = await session.get(McpServer, config.server_id)
            if server is None or not server.enabled:
                raise NodeFailure("mcp_server_not_found", "MCP server is not available")
            server_name = server.name
            try:
                output = await call_mcp_tool(
                    server,
                    config.tool,
                    arguments,
                    timeout_seconds=config.timeout_seconds,
                    settings=self._settings,
                )
            except McpError as exc:
                raise NodeFailure(exc.code, exc.message) from None
        return output, f"mcp {server_name}/{config.tool}"

    async def _mcp_resource_node(
        self, config: McpResourceNodeConfig
    ) -> tuple[str, str]:
        uri = self._render(config.uri)
        async with SessionLocal() as session:
            server = await session.get(McpServer, config.server_id)
            if server is None or not server.enabled:
                raise NodeFailure("mcp_server_not_found", "MCP server is not available")
            server_name = server.name
            try:
                output = await read_mcp_resource(
                    server,
                    uri,
                    timeout_seconds=config.timeout_seconds,
                    settings=self._settings,
                )
            except McpError as exc:
                raise NodeFailure(exc.code, exc.message) from None
        return output, f"mcp resource {server_name}/{uri}"

    async def _mcp_prompt_node(
        self, config: McpPromptNodeConfig
    ) -> tuple[str, str]:
        arguments = {key: self._render(value) for key, value in config.arguments.items()}
        async with SessionLocal() as session:
            server = await session.get(McpServer, config.server_id)
            if server is None or not server.enabled:
                raise NodeFailure("mcp_server_not_found", "MCP server is not available")
            server_name = server.name
            try:
                output = await get_mcp_prompt(
                    server,
                    config.name,
                    arguments,
                    timeout_seconds=config.timeout_seconds,
                    settings=self._settings,
                )
            except McpError as exc:
                raise NodeFailure(exc.code, exc.message) from None
        return output, f"mcp prompt {server_name}/{config.name}"

    async def _memory_read(
        self, config: MemoryReadNodeConfig
    ) -> tuple[str, str]:
        query = self._render(config.query) if config.query.strip() else self._input
        if config.scope_type == "all":
            allowed_scopes = {"global"}
            if config.project_id is not None:
                allowed_scopes.add("project")
            if config.agent_id is not None:
                allowed_scopes.add("agent")
        else:
            allowed_scopes = {config.scope_type}
        async with SessionLocal() as session:
            try:
                memory_settings = await get_memory_settings(
                    session, self._workspace_id, self._user_id
                )
                if not memory_settings.enabled:
                    await session.commit()
                    return "(memory disabled)", query
                await validate_memory_targets(
                    session,
                    self._workspace_id,
                    project_id=config.project_id,
                    agent_id=config.agent_id,
                )
                selection = await select_memories(
                    session,
                    workspace_id=self._workspace_id,
                    user_id=self._user_id,
                    agent_id=config.agent_id,
                    project_id=config.project_id,
                    query=query,
                    limit=min(config.limit, memory_settings.max_inject_items),
                    max_chars=min(
                        self._settings.agent_memory_inject_chars,
                        memory_settings.max_inject_chars,
                    ),
                    allowed_scopes=allowed_scopes,
                    allowed_provider_ids=memory_settings.allowed_provider_ids,
                    allowed_models=memory_settings.allowed_models,
                    allowed_agent_ids=memory_settings.allowed_agent_ids,
                )
                if selection.items:
                    await record_memory_usage(
                        session,
                        workspace_id=self._workspace_id,
                        user_id=self._user_id,
                        memories=[
                            (item.memory, item.score, item.injected_chars)
                            for item in selection.items
                        ],
                        context_type="workflow",
                        context_id=str(self._run_id),
                        provider_id=None,
                        model=None,
                    )
                await session.commit()
                output = selection.block
            except MemoryError as exc:
                raise NodeFailure(exc.code, exc.message) from None
        return output or "(no matching memories)", query

    async def _memory_write(
        self, config: MemoryWriteNodeConfig
    ) -> tuple[str, str]:
        title = self._render(config.title) if config.title else ""
        content = self._render(config.content)
        scope_type = config.scope_type
        project_id = config.project_id if scope_type == "project" else None
        agent_id = config.agent_id if scope_type == "agent" else None
        async with SessionLocal() as session:
            try:
                memory_settings = await get_memory_settings(
                    session, self._workspace_id, self._user_id
                )
                if not memory_settings.enabled:
                    raise MemoryError(
                        "memory_disabled", "Memory hub is disabled for this user"
                    )
                await validate_memory_targets(
                    session,
                    self._workspace_id,
                    project_id=project_id,
                    agent_id=agent_id,
                )
                existing = None
                if config.upsert:
                    existing = await find_memory_by_title(
                        session,
                        workspace_id=self._workspace_id,
                        user_id=self._user_id,
                        title=title,
                        scope_type=scope_type,
                        project_id=project_id,
                        agent_id=agent_id,
                    )
                if existing is not None:
                    memory = await update_memory(
                        session,
                        existing,
                        title=title or existing.title,
                        content=content,
                        status=config.status,
                        change_reason="workflow update",
                        changed_by=self._user_id,
                    )
                    action = "updated"
                else:
                    memory = await create_memory(
                        session,
                        workspace_id=self._workspace_id,
                        user_id=self._user_id,
                        content=content,
                        title=title,
                        kind=config.kind,
                        scope_type=scope_type,
                        project_id=project_id,
                        agent_id=agent_id,
                        status=config.status,
                        source="workflow",
                        source_type="workflow",
                        source_id=str(self._run_id),
                    )
                    action = "saved"
                saved_title = memory.title
                await session.commit()
            except MemoryError as exc:
                raise NodeFailure(exc.code, exc.message) from None
        if config.status == "candidate":
            return f"memory candidate {action}: {saved_title}", content
        return f"memory {action}: {saved_title}", content

    async def _code_node(self, config: CodeNodeConfig) -> tuple[str, str]:
        limit = min(config.max_output_chars, self._settings.code_node_max_output_chars)
        try:
            output = evaluate_expression(
                config.code,
                {"input": self._input, "outputs": dict(self._outputs)},
                max_output_chars=limit,
            )
        except SandboxError as exc:
            raise NodeFailure(exc.code, exc.message) from None
        return output, _truncate(config.code, SUMMARY_MAX_CHARS)

    async def _database_node(
        self, config: DatabaseNodeConfig
    ) -> tuple[str, str]:
        params = {key: self._render(value) for key, value in config.params.items()}
        async with SessionLocal() as session:
            connection = await session.get(DatabaseConnection, config.connection_id)
            if connection is None or not connection.enabled:
                raise NodeFailure(
                    "database_not_found", "Database connection is not available"
                )
            connection_name = connection.name
            try:
                output = await execute_read_query(
                    connection,
                    config.query,
                    params,
                    max_rows=min(
                        config.max_rows, self._settings.database_node_max_rows
                    ),
                    timeout_seconds=min(
                        config.timeout_seconds,
                        self._settings.database_node_timeout_seconds,
                    ),
                )
            except DatabaseNodeError as exc:
                raise NodeFailure(exc.code, exc.message) from None
        return output, f"database {connection_name}"

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
        pending = self._pending_reviews.get(node.id)
        if pending is not None:
            try:
                review_id = UUID(str(pending.get("review_id", "")))
            except ValueError:
                review_id = None
            if review_id is not None:
                async with SessionLocal() as session:
                    review = await session.get(WorkflowReview, review_id)
                    if review is not None and review.node_run_id is not None:
                        return review.node_run_id
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

    async def _save_checkpoint(self) -> None:
        if self._live_states is None or self._live_edge_state is None:
            return
        pending_reviews = list(self._pending_reviews.values())
        node_states = dict(self._live_states)
        for pending in pending_reviews:
            node_states[pending["node_id"]] = "waiting_review"
        payload: dict[str, object] = {
            "outputs": dict(self._outputs),
            "node_states": node_states,
            "edge_state": {
                f"{source}->{target}": value
                for (source, target), value in self._live_edge_state.items()
            },
        }
        if pending_reviews:
            payload["pending_reviews"] = [dict(item) for item in pending_reviews]
        try:
            async with SessionLocal() as session:
                run = await session.get(WorkflowRun, self._run_id)
                if run is None:
                    return
                run.checkpoint = payload
                run.paused_at = datetime.now(UTC) if pending_reviews else None
                await session.commit()
        except Exception:
            logger.warning("failed to save workflow checkpoint", exc_info=True)

    async def _finish_run(
        self,
        status: str,
        total_ms: float,
        error_code: str | None,
        *,
        preserve_checkpoint: bool = False,
    ) -> None:
        try:
            async with SessionLocal() as session:
                run = await session.get(WorkflowRun, self._run_id)
                if run is None:
                    return
                run.prompt_tokens = self._prompt_tokens
                run.completion_tokens = self._completion_tokens
                run.cost = round(self._cost, 6)
                if not preserve_checkpoint:
                    run.status = status
                    run.error_code = error_code
                    run.total_ms = total_ms
                    run.finished_at = datetime.now(UTC)
                    run.checkpoint = {}
                    run.paused_at = None
                    await session.execute(
                        update(WorkflowReview)
                        .where(
                            WorkflowReview.run_id == self._run_id,
                            WorkflowReview.status == "pending",
                        )
                        .values(
                            status="cancelled",
                            decision="cancelled",
                            resolved_at=datetime.now(UTC),
                        )
                    )
                await session.commit()
                if preserve_checkpoint:
                    return
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
                if status == "completed":
                    enabled = await session.scalar(
                        select(Workflow.memory_extract_enabled).where(
                            Workflow.id == run.workflow_id
                        )
                    )
                    if enabled:
                        from app.services.memory_extraction import (
                            schedule_workflow_memory_extraction,
                        )

                        await schedule_workflow_memory_extraction(run.id)
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


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _redact_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    if not parsed.query:
        return url
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "<redacted>", ""))


def _parse_loop_items(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass
    return [line.strip() for line in text.splitlines() if line.strip()]


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
