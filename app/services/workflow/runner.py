import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.clients import RedisLike
from app.config import get_settings
from app.db import SessionLocal
from app.models import WorkflowNodeRun, WorkflowRun
from app.providers.base import ChatMessage, ProviderError, Usage
from app.providers.registry import ProviderRegistry
from app.services.costs import compute_cost, price_snapshot
from app.services.workflow.schema import (
    KbSearchNodeConfig,
    LLMNodeConfig,
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


class NodeFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


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
        workspace_id: UUID,
        user_id: UUID,
        kb_id: UUID | None,
        redis: RedisLike,
        input_text: str,
    ) -> None:
        self._run_id = run_id
        self._workflow_id = workflow_id
        self._version = version
        self._definition = definition
        self._providers = provider_registry
        self._tools = tool_registry
        self._workspace_id = workspace_id
        self._user_id = user_id
        self._kb_id = kb_id
        self._redis = redis
        self._input = input_text
        self._settings = get_settings()
        self._outputs: dict[str, str] = {}
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._cost = 0.0
        self._current_node_run: UUID | None = None

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
            for node in self._definition.ordered_nodes():
                async for event in self._run_node(node):
                    yield event
        except asyncio.CancelledError:
            await self._mark_cancelled()
            raise
        except NodeFailure as exc:
            total_ms = _elapsed_ms(started)
            await self._finish_run("failed", total_ms, exc.code)
            yield WorkflowEvent(
                "workflow_end",
                {
                    "run_id": str(self._run_id),
                    "status": "failed",
                    "error_code": exc.code,
                    "total_ms": total_ms,
                    "prompt_tokens": self._prompt_tokens,
                    "completion_tokens": self._completion_tokens,
                    "cost": self._cost,
                },
            )
            return
        except Exception:
            logger.exception("workflow run %s failed unexpectedly", self._run_id)
            total_ms = _elapsed_ms(started)
            await self._finish_run("failed", total_ms, "internal_error")
            yield WorkflowEvent(
                "workflow_end",
                {
                    "run_id": str(self._run_id),
                    "status": "failed",
                    "error_code": "internal_error",
                    "total_ms": total_ms,
                    "prompt_tokens": self._prompt_tokens,
                    "completion_tokens": self._completion_tokens,
                    "cost": self._cost,
                },
            )
            return

        total_ms = _elapsed_ms(started)
        await self._finish_run("completed", total_ms, None)
        yield WorkflowEvent(
            "workflow_end",
            {
                "run_id": str(self._run_id),
                "status": "completed",
                "total_ms": total_ms,
                "prompt_tokens": self._prompt_tokens,
                "completion_tokens": self._completion_tokens,
                "cost": self._cost,
            },
        )

    async def _run_node(self, node: WorkflowNode) -> AsyncIterator[WorkflowEvent]:
        yield WorkflowEvent(
            "node_start",
            {"run_id": str(self._run_id), "node_id": node.id, "node_type": node.type},
        )
        started = time.perf_counter()
        attempts = 0
        last_error: NodeFailure | None = None
        output = ""
        input_summary = ""
        while attempts < self._settings.workflow_node_attempts:
            attempts += 1
            try:
                output, input_summary = await asyncio.wait_for(
                    self._execute_node(node),
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
            node_run_id = await self._start_node_run(node, input_summary)
            await self._finish_node_run(
                node_run_id, "failed", attempts, duration_ms, "", last_error.code
            )
            yield WorkflowEvent(
                "node_end",
                {
                    "run_id": str(self._run_id),
                    "node_id": node.id,
                    "status": "failed",
                    "attempts": attempts,
                    "duration_ms": duration_ms,
                    "error_code": last_error.code,
                },
            )
            raise last_error

        self._outputs[node.id] = output
        node_run_id = await self._start_node_run(node, input_summary)
        await self._finish_node_run(node_run_id, "completed", attempts, duration_ms, output, None)
        yield WorkflowEvent(
            "node_end",
            {
                "run_id": str(self._run_id),
                "node_id": node.id,
                "status": "completed",
                "attempts": attempts,
                "duration_ms": duration_ms,
                "output": _truncate(output, SUMMARY_MAX_CHARS),
            },
        )

    async def _execute_node(self, node: WorkflowNode) -> tuple[str, str]:
        values = {"input": self._input, **self._outputs}
        if node.type == "llm":
            config = LLMNodeConfig.model_validate(node.config)
            prompt = render_template(config.prompt, values)
            system_prompt = (
                render_template(config.system_prompt, values) if config.system_prompt else None
            )
            output, usage = await self._call_llm(config, prompt, system_prompt)
            await self._record_usage(config.provider_id, config.model, usage)
            return output, prompt
        if node.type == "kb_search":
            config = KbSearchNodeConfig.model_validate(node.config)
            query = render_template(config.query, values)
            output = await self._search_knowledge(query)
            return output, query
        raise NodeFailure("unsupported_node_type", f"Unsupported node type: {node.type}")

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

    async def _search_knowledge(self, query: str) -> str:
        if self._kb_id is None:
            raise NodeFailure("no_knowledge_base", "A kb_search node requires a kb_id on the run")
        result = await self._tools.execute(
            "kb_search",
            {"query": query},
            ToolContext(
                workspace_id=self._workspace_id,
                user_id=self._user_id,
                kb_id=self._kb_id,
                redis=self._redis,
            ),
        )
        if not result.ok:
            raise NodeFailure(result.error_code or "tool_error", result.error or "Tool failed")
        return result.output

    async def _record_usage(self, provider_id: str, model: str, usage: Usage) -> None:
        self._prompt_tokens += usage.prompt_tokens or 0
        self._completion_tokens += usage.completion_tokens or 0
        try:
            async with SessionLocal() as session:
                input_price, output_price = await price_snapshot(session, provider_id, model)
        except Exception:
            logger.warning("failed to read model price for workflow node", exc_info=True)
            return
        self._cost += compute_cost(
            usage.prompt_tokens, usage.completion_tokens, input_price, output_price
        )

    async def _start_node_run(self, node: WorkflowNode, input_summary: str) -> UUID:
        try:
            async with SessionLocal() as session:
                record = WorkflowNodeRun(
                    run_id=self._run_id,
                    node_id=node.id,
                    node_type=node.type,
                    status="running",
                    input_summary=_truncate(input_summary, SUMMARY_MAX_CHARS),
                )
                session.add(record)
                await session.commit()
                await session.refresh(record)
                self._current_node_run = record.id
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
                record.output_summary = _truncate(output, SUMMARY_MAX_CHARS)
                record.error_code = error_code
                await session.commit()
        except Exception:
            logger.exception("failed to finalize workflow node run")

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
                run.finished_at = _utcnow()
                await session.commit()
        except Exception:
            logger.exception("failed to finalize workflow run")

    async def _mark_cancelled(self) -> None:
        await self._finish_run("cancelled", 0.0, "cancelled")
        if self._current_node_run is not None:
            try:
                async with SessionLocal() as session:
                    record = await session.get(WorkflowNodeRun, self._current_node_run)
                    if record is not None and record.status == "running":
                        record.status = "cancelled"
                        await session.commit()
            except Exception:
                logger.warning("failed to mark workflow node cancelled", exc_info=True)


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


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _utcnow() -> datetime:
    return datetime.now(UTC)
