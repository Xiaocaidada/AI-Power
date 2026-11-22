import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select

from app.agents.registry import AgentRegistry
from app.clients import RedisLike
from app.config import get_settings
from app.db import SessionLocal
from app.metrics import record_usage_metrics
from app.models import CollaborationRun, CollaborationStep
from app.providers.base import ChatMessage, ProviderError, Usage
from app.providers.registry import ProviderRegistry
from app.services.agent import AgentFailure, AgentRunner
from app.services.budget import check_workspace_budget
from app.services.usage_ledger import SOURCE_COLLABORATION, write_usage_event
from app.services.webhooks import enqueue_event
from app.tools.base import ToolContext, ToolRegistry

logger = logging.getLogger(__name__)

SUMMARY_MAX_CHARS = 500
PLANNER_SYSTEM = (
    "You are the planner. Split the user's request into 2-4 self-contained subtasks. "
    'Reply with only JSON: {"tasks":[{"id":"t1","agent":"retrieval|math|general",'
    '"task":"..."}]}. Use retrieval for knowledge-base lookups, math for arithmetic, '
    "general otherwise."
)
CRITIC_SYSTEM = (
    "You are the critic. Review the worker results against the user's request. "
    'Reply with only JSON: {"verdict":"accept|revise","final_answer":"...",'
    '"feedback":"..."}. Use accept only when a complete answer can be given; otherwise '
    "explain what to fix in feedback."
)


@dataclass(frozen=True, slots=True)
class CollaborationEvent:
    kind: str
    data: dict[str, object]


class RunCancelled(Exception):
    """Raised at a step boundary after a cancellation request."""

    def __init__(self) -> None:
        super().__init__("Run cancelled")


class PlanTask(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,49}$")
    agent: Literal["retrieval", "math", "general"]
    task: str = Field(min_length=1, max_length=4000)


class Plan(BaseModel):
    tasks: list[PlanTask] = Field(min_length=2)

    @model_validator(mode="after")
    def _max_tasks(self) -> "Plan":
        limit = get_settings().collaboration_max_tasks
        if len(self.tasks) > limit:
            raise ValueError(f"At most {limit} tasks are allowed")
        ids = [task.id for task in self.tasks]
        if len(set(ids)) != len(ids):
            raise ValueError("Task ids must be unique")
        return self


class Critique(BaseModel):
    verdict: Literal["accept", "revise"]
    final_answer: str = ""
    feedback: str = ""

    @model_validator(mode="after")
    def _answer_required(self) -> "Critique":
        if self.verdict == "accept" and not self.final_answer.strip():
            raise ValueError("accept requires final_answer")
        if self.verdict == "revise" and not self.feedback.strip():
            raise ValueError("revise requires feedback")
        return self


class CollaborationRunner:
    def __init__(
        self,
        *,
        run_id: UUID,
        workspace_id: UUID,
        user_id: UUID,
        provider_id: str,
        model: str,
        kb_id: UUID | None,
        redis: RedisLike,
        input_text: str,
        provider_registry: ProviderRegistry,
        tool_registry: ToolRegistry,
        agent_registry: AgentRegistry,
        quota_guard,
        api_key_id: UUID | None = None,
    ) -> None:
        self._run_id = run_id
        self._workspace_id = workspace_id
        self._user_id = user_id
        self._provider_id = provider_id
        self._model = model
        self._kb_id = kb_id
        self._redis = redis
        self._input = input_text
        self._providers = provider_registry
        self._tools = tool_registry
        self._agents = agent_registry
        self._quota_guard = quota_guard
        self._api_key_id = api_key_id
        self._settings = get_settings()
        self._budget = self._settings.collaboration_max_steps
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._cost = 0.0
        self._rounds = 0
        self._outputs: dict[str, str] = {}
        self._last_outputs: dict[str, str] = {}

    async def run(self) -> AsyncIterator[CollaborationEvent]:
        started = time.perf_counter()
        yield CollaborationEvent(
            "collaboration_start",
            {"run_id": str(self._run_id), "input": self._input},
        )
        try:
            await self._check_cancel()
            yield CollaborationEvent("planner_start", {"run_id": str(self._run_id)})
            plan = await self._plan()
            yield CollaborationEvent(
                "planner_end",
                {
                    "run_id": str(self._run_id),
                    "tasks": [task.model_dump() for task in plan.tasks],
                },
            )
            feedback = ""
            final_answer = ""
            while True:
                await self._check_cancel()
                async for event in self._run_workers(plan, feedback):
                    yield event
                await self._check_cancel()
                outputs = self._last_outputs
                self._rounds += 1
                yield CollaborationEvent(
                    "critic_start",
                    {"run_id": str(self._run_id), "round": self._rounds},
                )
                critic_started = time.perf_counter()
                critique = await self._critique(plan, outputs, self._rounds)
                yield CollaborationEvent(
                    "critic_end",
                    {
                        "run_id": str(self._run_id),
                        "round": self._rounds,
                        "verdict": critique.verdict,
                        "duration_ms": _elapsed_ms(critic_started),
                        "feedback": _truncate(critique.feedback, SUMMARY_MAX_CHARS),
                    },
                )
                if critique.verdict == "accept":
                    final_answer = critique.final_answer
                    break
                if self._rounds >= self._settings.collaboration_max_rounds:
                    final_answer = "\n\n".join(outputs.values())
                    break
                feedback = critique.feedback
            await self._check_cancel()
            total_ms = _elapsed_ms(started)
            await self._finish_run(
                "completed", total_ms, round_count=self._rounds, final=final_answer
            )
            yield CollaborationEvent(
                "collaboration_end",
                {
                    "run_id": str(self._run_id),
                    "status": "completed",
                    "rounds": self._rounds,
                    "total_ms": total_ms,
                    "prompt_tokens": self._prompt_tokens,
                    "completion_tokens": self._completion_tokens,
                    "cost": self._cost,
                    "output": _truncate(final_answer, SUMMARY_MAX_CHARS),
                },
            )
        except asyncio.CancelledError:
            await self._finish_run("cancelled", 0.0, round_count=self._rounds)
            raise
        except RunCancelled:
            total_ms = _elapsed_ms(started)
            await self._finish_run("cancelled", total_ms, error_code="cancelled")
            yield self._end_event("cancelled", total_ms, "cancelled")
            return
        except (AgentFailure, ProviderError) as exc:
            code = getattr(exc, "code", "provider_error")
            total_ms = _elapsed_ms(started)
            await self._finish_run("failed", total_ms, error_code=code)
            yield self._end_event("failed", total_ms, code)
        except Exception:
            logger.exception("collaboration run %s failed", self._run_id)
            total_ms = _elapsed_ms(started)
            await self._finish_run("failed", total_ms, error_code="internal_error")
            yield self._end_event("failed", total_ms, "internal_error")

    def _end_event(self, status: str, total_ms: float, error_code: str) -> CollaborationEvent:
        return CollaborationEvent(
            "collaboration_end",
            {
                "run_id": str(self._run_id),
                "status": status,
                "rounds": self._rounds,
                "total_ms": total_ms,
                "error_code": error_code,
            },
        )

    async def _check_cancel(self) -> None:
        try:
            async with SessionLocal() as session:
                requested = (
                    await session.execute(
                        select(CollaborationRun.cancel_requested_at).where(
                            CollaborationRun.id == self._run_id
                        )
                    )
                ).scalar_one_or_none()
        except Exception:
            logger.warning("failed to check collaboration cancellation", exc_info=True)
            return
        if requested is not None:
            raise RunCancelled()

    def _consume_budget(self) -> None:
        if self._budget <= 0:
            raise AgentFailure("collaboration_step_limit", "Collaboration step budget exhausted")
        self._budget -= 1

    async def _plan(self) -> Plan:
        step_id = await self._start_step("planner", "plan", self._input)
        try:
            text, usage = await self._complete(PLANNER_SYSTEM, self._input)
        except (AgentFailure, ProviderError) as exc:
            await self._finish_step(step_id, "failed", "", Usage(), getattr(exc, "code", None))
            raise
        plan = _parse_plan(text)
        cost = await self._record_usage(usage, step_id)
        await self._finish_step(step_id, "completed", text, usage, None, cost)
        await self._save_plan(plan)
        return plan

    async def _run_workers(self, plan: Plan, feedback: str) -> AsyncIterator[CollaborationEvent]:
        semaphore = asyncio.Semaphore(self._settings.collaboration_parallel_limit)
        self._last_outputs = {}

        async def worker(task: PlanTask):
            async with semaphore:
                try:
                    return await asyncio.wait_for(
                        self._run_worker(task, feedback),
                        timeout=self._settings.collaboration_task_timeout_seconds,
                    )
                except TimeoutError:
                    raise AgentFailure("task_timeout", f"Worker {task.id} timed out") from None

        tasks = {asyncio.create_task(worker(task)): task for task in plan.tasks}
        for task in tasks.values():
            yield CollaborationEvent(
                "worker_start",
                {
                    "run_id": str(self._run_id),
                    "task_id": task.id,
                    "agent": task.agent,
                    "task": _truncate(task.task, SUMMARY_MAX_CHARS),
                },
            )
        try:
            for completed in asyncio.as_completed(tasks):
                task_id, output, duration_ms = await completed
                self._last_outputs[task_id] = output
                self._outputs[task_id] = output
                yield CollaborationEvent(
                    "worker_end",
                    {
                        "run_id": str(self._run_id),
                        "task_id": task_id,
                        "status": "completed",
                        "duration_ms": duration_ms,
                        "output": _truncate(output, SUMMARY_MAX_CHARS),
                    },
                )
        except Exception:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

    async def _run_worker(self, task: PlanTask, feedback: str) -> tuple[str, str, float]:
        started = time.perf_counter()
        prompt = task.task
        if feedback:
            prompt = (
                f"{task.task}\n\nPrevious answer:\n{self._outputs.get(task.id, '')}\n\n"
                f"Critic feedback:\n{feedback}\nRevise the answer."
            )
        step_id = await self._start_step("worker", task.id, prompt)
        root_agent = "supervisor" if task.agent == "general" else task.agent
        provider = self._providers.get(self._provider_id)
        runner = AgentRunner(
            provider=provider,
            model=self._model,
            tool_registry=self._tools,
            agent_registry=self._agents,
            context=ToolContext(
                workspace_id=self._workspace_id,
                user_id=self._user_id,
                kb_id=self._kb_id,
                redis=self._redis,
            ),
            quota_guard=self._quota_guard,
            root_agent=root_agent,
            step_guard=self._consume_budget,
        )
        parts: list[str] = []
        try:
            async for event in runner.run([ChatMessage(role="user", content=prompt)]):
                if event.kind == "delta":
                    parts.append(str(event.data.get("text", "")))
        except AgentFailure as exc:
            cost = await self._record_failed_usage(runner.usage, step_id)
            await self._finish_step(step_id, "failed", "", runner.usage, exc.code, cost)
            raise
        except ProviderError as exc:
            cost = await self._record_failed_usage(runner.usage, step_id)
            await self._finish_step(step_id, "failed", "", runner.usage, exc.code, cost)
            raise
        output = "".join(parts)
        usage = runner.usage
        cost = await self._record_usage(usage, step_id)
        await self._finish_step(step_id, "completed", output, usage, None, cost)
        return task.id, output, _elapsed_ms(started)

    async def _critique(self, plan: Plan, outputs: dict[str, str], round_no: int) -> Critique:
        step_id = await self._start_step("critic", f"round-{round_no}", self._input)
        prompt = f"User request:\n{self._input}\n\n"
        for task in plan.tasks:
            prompt += f"[{task.id}] {task.task}\n{outputs.get(task.id, '')}\n\n"
        try:
            text, usage = await self._complete(CRITIC_SYSTEM, prompt)
        except (AgentFailure, ProviderError) as exc:
            await self._finish_step(step_id, "failed", "", Usage(), getattr(exc, "code", None))
            raise
        critique = _parse_critique(text)
        cost = await self._record_usage(usage, step_id)
        await self._finish_step(step_id, "completed", text, usage, None, cost)
        return critique

    async def _complete(self, system: str, user: str) -> tuple[str, Usage]:
        self._consume_budget()
        if self._quota_guard is not None:
            try:
                await self._quota_guard()
            except HTTPException as exc:
                detail = exc.detail
                code = detail.get("code") if isinstance(detail, dict) else None
                raise AgentFailure(str(code or "quota_exceeded"), "Quota exceeded") from None
        provider = self._providers.get(self._provider_id)
        parts: list[str] = []
        prompt_tokens: int | None = None
        completion_tokens: int | None = None
        async for chunk in provider.stream_chat(
            [ChatMessage(role="system", content=system), ChatMessage(role="user", content=user)],
            self._model,
        ):
            if chunk.delta:
                parts.append(chunk.delta)
            if chunk.usage is not None:
                prompt_tokens = (prompt_tokens or 0) + (chunk.usage.prompt_tokens or 0)
                completion_tokens = (completion_tokens or 0) + (chunk.usage.completion_tokens or 0)
        return "".join(parts), Usage(
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )

    async def _record_failed_usage(self, usage: Usage, step_id: UUID) -> float:
        """Bill a failed step only when the provider actually reported tokens."""
        if not usage.prompt_tokens and not usage.completion_tokens:
            return 0.0
        return await self._record_usage(usage, step_id)

    async def _record_usage(self, usage: Usage, step_id: UUID) -> float:
        self._prompt_tokens += usage.prompt_tokens or 0
        self._completion_tokens += usage.completion_tokens or 0
        try:
            async with SessionLocal() as session:
                written = await write_usage_event(
                    session,
                    workspace_id=self._workspace_id,
                    user_id=self._user_id,
                    source=SOURCE_COLLABORATION,
                    provider_id=self._provider_id,
                    model=self._model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    api_key_id=self._api_key_id,
                    collaboration_step_id=step_id,
                )
                await session.commit()
        except Exception:
            logger.exception("failed to record collaboration step usage")
            return 0.0
        if written is None:
            return 0.0
        self._cost += written.cost
        record_usage_metrics(
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost=written.cost,
            provider_id=self._provider_id,
            model=self._model,
            source=SOURCE_COLLABORATION,
        )
        return written.cost

    async def _start_step(self, role: str, key: str, input_summary: str) -> UUID:
        try:
            async with SessionLocal() as session:
                step = CollaborationStep(
                    run_id=self._run_id,
                    role=role,
                    step_key=key,
                    status="running",
                    input_summary=_truncate(input_summary, SUMMARY_MAX_CHARS),
                )
                session.add(step)
                await session.commit()
                await session.refresh(step)
                return step.id
        except Exception:
            logger.exception("failed to create collaboration step")
            return UUID(int=0)

    async def _finish_step(
        self,
        step_id: UUID,
        status: str,
        output: str,
        usage: Usage,
        error_code: str | None,
        cost: float = 0.0,
    ) -> None:
        if step_id == UUID(int=0):
            return
        try:
            async with SessionLocal() as session:
                step = await session.get(CollaborationStep, step_id)
                if step is None:
                    return
                step.status = status
                step.output_summary = _truncate(output, SUMMARY_MAX_CHARS)
                step.prompt_tokens = usage.prompt_tokens or 0
                step.completion_tokens = usage.completion_tokens or 0
                step.cost = cost
                step.error_code = error_code
                await session.commit()
        except Exception:
            logger.exception("failed to finalize collaboration step")

    async def _save_plan(self, plan: Plan) -> None:
        try:
            async with SessionLocal() as session:
                run = await session.get(CollaborationRun, self._run_id)
                if run is None:
                    return
                run.plan = [task.model_dump() for task in plan.tasks]
                await session.commit()
        except Exception:
            logger.exception("failed to save collaboration plan")

    async def _finish_run(
        self,
        status: str,
        total_ms: float,
        *,
        round_count: int | None = None,
        error_code: str | None = None,
        final: str = "",
    ) -> None:
        try:
            async with SessionLocal() as session:
                run = await session.get(CollaborationRun, self._run_id)
                if run is None:
                    return
                run.status = status
                run.error_code = error_code
                run.rounds = round_count if round_count is not None else self._rounds
                run.final_output = final
                run.prompt_tokens = self._prompt_tokens
                run.completion_tokens = self._completion_tokens
                run.cost = round(self._cost, 6)
                run.total_ms = total_ms
                run.finished_at = datetime.now(UTC)
                await session.commit()
                try:
                    await check_workspace_budget(session, self._redis, self._workspace_id)
                    await session.commit()
                except Exception:
                    logger.warning("collaboration budget check failed", exc_info=True)
                await enqueue_event(
                    run.workspace_id,
                    "collaboration.completed",
                    {
                        "run_id": str(run.id),
                        "status": run.status,
                        "error_code": run.error_code,
                        "rounds": run.rounds,
                        "total_ms": run.total_ms,
                        "prompt_tokens": run.prompt_tokens,
                        "completion_tokens": run.completion_tokens,
                        "cost": run.cost,
                    },
                )
        except Exception:
            logger.exception("failed to finalize collaboration run")


def _parse_json_object(text: str) -> dict[str, object] | None:
    cleaned = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(1).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None


def _parse_plan(text: str) -> Plan:
    payload = _parse_json_object(text)
    if payload is None:
        raise AgentFailure("invalid_plan", "Planner did not return a JSON plan")
    try:
        return Plan.model_validate(payload)
    except ValidationError as exc:
        raise AgentFailure("invalid_plan", f"Invalid plan: {exc.errors()[0]['msg']}") from None


def _parse_critique(text: str) -> Critique:
    payload = _parse_json_object(text)
    if payload is None:
        raise AgentFailure("invalid_critique", "Critic did not return JSON")
    try:
        return Critique.model_validate(payload)
    except ValidationError as exc:
        raise AgentFailure(
            "invalid_critique", f"Invalid critique: {exc.errors()[0]['msg']}"
        ) from None


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
