import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from fastapi import HTTPException

from app.agents.base import AgentSpec
from app.agents.protocol import PROTOCOL_HINT, FinalAnswer, parse_agent_output
from app.agents.registry import (
    DELEGATE_TOOL,
    MAX_AGENT_DEPTH,
    SUPERVISOR_AGENT,
    AgentRegistry,
)
from app.config import get_settings
from app.providers.base import ChatMessage, LLMProvider, Usage
from app.tools.base import ToolContext, ToolRegistry, ToolResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentEvent:
    kind: str
    data: dict[str, object]


class AgentFailure(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class _Outcome:
    content: str = ""


@dataclass
class _ToolOutcome:
    result: ToolResult = field(default_factory=lambda: ToolResult(ok=False))
    observation: str = ""


class AgentRunner:
    """Supervisor + specialist agents; every LLM step shares one step budget."""

    def __init__(
        self,
        *,
        provider: LLMProvider,
        model: str,
        tool_registry: ToolRegistry,
        agent_registry: AgentRegistry,
        context: ToolContext,
        quota_guard: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        settings = get_settings()
        self._provider = provider
        self._model = model
        self._tool_registry = tool_registry
        self._agent_registry = agent_registry
        self._context = context
        self._quota_guard = quota_guard
        self._max_steps = settings.agent_max_steps
        self._observation_max_chars = settings.agent_tool_output_max_chars
        self._steps = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._saw_usage = False
        self._tool_records: list[dict[str, object]] = []

    @property
    def usage(self) -> Usage:
        return Usage(
            prompt_tokens=self._prompt_tokens if self._saw_usage else None,
            completion_tokens=self._completion_tokens if self._saw_usage else None,
        )

    @property
    def tool_records(self) -> list[dict[str, object]]:
        return list(self._tool_records)

    async def run(self, history: Sequence[ChatMessage]) -> AsyncIterator[AgentEvent]:
        spec = self._agent_registry.get(SUPERVISOR_AGENT)
        outcome = _Outcome()
        started = time.perf_counter()
        yield AgentEvent("agent_start", {"agent": spec.name, "depth": 0})
        try:
            async for event in self._agent_loop(spec, history, 0, outcome):
                yield event
        except Exception:
            yield AgentEvent(
                "agent_end",
                {
                    "agent": spec.name,
                    "depth": 0,
                    "status": "failed",
                    "duration_ms": _elapsed_ms(started),
                },
            )
            raise
        yield AgentEvent("delta", {"text": outcome.content})
        yield AgentEvent(
            "agent_end",
            {
                "agent": spec.name,
                "depth": 0,
                "status": "completed",
                "duration_ms": _elapsed_ms(started),
            },
        )

    async def _agent_loop(
        self,
        spec: AgentSpec,
        history: Sequence[ChatMessage],
        depth: int,
        outcome: _Outcome,
    ) -> AsyncIterator[AgentEvent]:
        exchanges: list[tuple[str, str]] = []
        while True:
            await self._begin_step()
            messages = self._build_messages(spec, history, exchanges)
            raw, usage = await self._complete(messages)
            if usage.prompt_tokens is not None or usage.completion_tokens is not None:
                self._saw_usage = True
                self._prompt_tokens += usage.prompt_tokens or 0
                self._completion_tokens += usage.completion_tokens or 0
            parsed = parse_agent_output(raw)
            if isinstance(parsed, FinalAnswer):
                outcome.content = parsed.content
                return
            holder = _ToolOutcome()
            async for event in self._run_tool(spec, parsed.tool, parsed.arguments, depth, holder):
                yield event
            exchanges.append((raw, holder.observation))

    async def _begin_step(self) -> None:
        if self._steps >= self._max_steps:
            raise AgentFailure(
                "agent_step_limit", f"Agent exceeded the {self._max_steps}-step limit"
            )
        self._steps += 1
        if self._quota_guard is None:
            return
        try:
            await self._quota_guard()
        except HTTPException as exc:
            detail = exc.detail
            code = detail.get("code") if isinstance(detail, dict) else None
            raise AgentFailure(str(code or "quota_exceeded"), "Quota exceeded") from None

    def _build_messages(
        self,
        spec: AgentSpec,
        history: Sequence[ChatMessage],
        exchanges: Sequence[tuple[str, str]],
    ) -> list[ChatMessage]:
        messages = [ChatMessage(role="system", content=self._system_prompt(spec)), *history]
        for raw, observation in exchanges:
            messages.append(ChatMessage(role="assistant", content=raw))
            messages.append(ChatMessage(role="user", content=observation))
        return messages

    def _system_prompt(self, spec: AgentSpec) -> str:
        lines = [spec.system_prompt, "", PROTOCOL_HINT]
        available = [
            tool for name in spec.tools if (tool := self._tool_registry.get(name)) is not None
        ]
        if available:
            lines += [
                "",
                "Available tools (JSON schema):",
                json.dumps([tool.prompt_descriptor() for tool in available], ensure_ascii=False),
            ]
        if spec.name == SUPERVISOR_AGENT:
            lines += [
                "",
                f'To delegate, call the built-in tool "{DELEGATE_TOOL}" with arguments '
                '{"agent": "retrieval" or "math", "task": "<self-contained instructions>"}. '
                "Sub-agents cannot delegate.",
            ]
        return "\n".join(lines)

    async def _complete(self, messages: Sequence[ChatMessage]) -> tuple[str, Usage]:
        parts: list[str] = []
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        async for chunk in self._provider.stream_chat(list(messages), self._model):
            if chunk.delta:
                parts.append(chunk.delta)
            if chunk.usage is not None:
                prompt_tokens = (prompt_tokens or 0) + (chunk.usage.prompt_tokens or 0)
                completion_tokens = (completion_tokens or 0) + (chunk.usage.completion_tokens or 0)
        return "".join(parts), Usage(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )

    async def _run_tool(
        self,
        spec: AgentSpec,
        tool: str,
        arguments: dict[str, object],
        depth: int,
        holder: _ToolOutcome,
    ) -> AsyncIterator[AgentEvent]:
        if tool == DELEGATE_TOOL:
            async for event in self._delegate(spec, arguments, depth, holder):
                yield event
            return

        yield AgentEvent("tool_call", {"agent": spec.name, "tool": tool, "arguments": arguments})
        started = time.perf_counter()
        if tool not in spec.tools or not self._tool_registry.has(tool):
            result = ToolResult(
                ok=False,
                error_code="tool_not_allowed",
                error=f"Tool {tool} is not available to agent {spec.name}",
            )
        else:
            result = await self._tool_registry.execute(tool, arguments, self._context)
        duration_ms = _elapsed_ms(started)
        self._record_tool(spec.name, tool, result.ok, duration_ms, depth)
        holder.result = result
        holder.observation = _observation(result, self._observation_max_chars)
        yield AgentEvent(
            "tool_result",
            {
                "agent": spec.name,
                "tool": tool,
                "ok": result.ok,
                "output": _truncate(result.output, 500),
                "error_code": result.error_code,
                "duration_ms": duration_ms,
            },
        )

    async def _delegate(
        self,
        spec: AgentSpec,
        arguments: dict[str, object],
        depth: int,
        holder: _ToolOutcome,
    ) -> AsyncIterator[AgentEvent]:
        started = time.perf_counter()
        target = arguments.get("agent")
        task = arguments.get("task")
        if spec.name != SUPERVISOR_AGENT:
            result = ToolResult(
                ok=False,
                error_code="delegation_not_allowed",
                error="Only the supervisor agent can delegate",
            )
        elif depth + 1 >= MAX_AGENT_DEPTH:
            result = ToolResult(
                ok=False,
                error_code="delegation_depth_exceeded",
                error="Maximum delegation depth reached",
            )
        elif (
            not isinstance(target, str)
            or target == SUPERVISOR_AGENT
            or target not in self._agent_registry.names()
        ):
            result = ToolResult(
                ok=False,
                error_code="invalid_delegation",
                error="Unknown or invalid sub-agent",
            )
        elif not isinstance(task, str) or not task.strip():
            result = ToolResult(
                ok=False,
                error_code="invalid_delegation",
                error="Delegation task must be a non-empty string",
            )
        else:
            sub = self._agent_registry.get(target)
            yield AgentEvent("agent_start", {"agent": sub.name, "depth": depth + 1})
            sub_outcome = _Outcome()
            sub_started = time.perf_counter()
            try:
                async for event in self._agent_loop(
                    sub,
                    [ChatMessage(role="user", content=task)],
                    depth + 1,
                    sub_outcome,
                ):
                    yield event
            except Exception:
                yield AgentEvent(
                    "agent_end",
                    {
                        "agent": sub.name,
                        "depth": depth + 1,
                        "status": "failed",
                        "duration_ms": _elapsed_ms(sub_started),
                    },
                )
                raise
            duration_ms = _elapsed_ms(sub_started)
            yield AgentEvent(
                "agent_end",
                {
                    "agent": sub.name,
                    "depth": depth + 1,
                    "status": "completed",
                    "duration_ms": duration_ms,
                },
            )
            self._record_tool(spec.name, DELEGATE_TOOL, True, duration_ms, depth, target=sub.name)
            holder.result = ToolResult(ok=True, output=sub_outcome.content)
            holder.observation = (
                f'<sub_agent_result agent="{sub.name}">\n'
                f"{_truncate(sub_outcome.content, self._observation_max_chars)}\n"
                "</sub_agent_result>"
            )
            return

        duration_ms = _elapsed_ms(started)
        self._record_tool(
            spec.name,
            DELEGATE_TOOL,
            False,
            duration_ms,
            depth,
            target=target if isinstance(target, str) else None,
        )
        holder.result = result
        holder.observation = _observation(result, self._observation_max_chars)
        yield AgentEvent(
            "tool_call",
            {"agent": spec.name, "tool": DELEGATE_TOOL, "arguments": arguments},
        )
        yield AgentEvent(
            "tool_result",
            {
                "agent": spec.name,
                "tool": DELEGATE_TOOL,
                "ok": False,
                "output": "",
                "error_code": result.error_code,
                "duration_ms": duration_ms,
            },
        )

    def _record_tool(
        self,
        agent: str,
        tool: str,
        ok: bool,
        duration_ms: float,
        depth: int,
        *,
        target: str | None = None,
    ) -> None:
        record: dict[str, object] = {
            "agent": agent,
            "tool": tool,
            "ok": ok,
            "duration_ms": duration_ms,
            "depth": depth,
        }
        if target is not None:
            record["target"] = target
        self._tool_records.append(record)


def _observation(result: ToolResult, max_chars: int) -> str:
    if result.ok:
        return f"<tool_output>\n{_truncate(result.output, max_chars)}\n</tool_output>"
    return (
        f'<tool_error code="{result.error_code}">\n'
        f"{_truncate(result.error or '', 500)}\n"
        "</tool_error>"
    )


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
