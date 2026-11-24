import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.clients import RedisLike
from app.config import get_settings
from app.services.memory_permissions import MemoryAccess
from app.services.retrieval import Citation

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ToolContext:
    workspace_id: UUID
    user_id: UUID
    kb_id: UUID | None = None
    kb_ids: list[UUID] | None = None
    conversation_id: UUID | None = None
    agent_id: UUID | None = None
    project_id: UUID | None = None
    memory_access: MemoryAccess | None = None
    redis: RedisLike | None = None
    citations: list[Citation] | None = None


class ToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


ToolHandler = Callable[[ToolContext, BaseModel], Awaitable[str]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: ToolHandler
    # MCP tools expose their remote JSON schema while still validating arguments
    # through a permissive model.
    parameters_schema_override: dict[str, Any] | None = None

    def parameters_schema(self) -> dict[str, Any]:
        if self.parameters_schema_override is not None:
            return self.parameters_schema_override
        return self.args_model.model_json_schema()

    def prompt_descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema(),
        }


@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    output: str = ""
    error_code: str | None = None
    error: str | None = None


class ToolRegistry:
    def __init__(
        self,
        tools: Sequence[ToolSpec] = (),
        *,
        timeout_seconds: float | None = None,
        max_output_chars: int | None = None,
    ) -> None:
        settings = get_settings()
        self.tools = tuple(tools)
        self.timeout_seconds = (
            settings.agent_tool_timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        self.max_output_chars = (
            settings.agent_tool_output_max_chars if max_output_chars is None else max_output_chars
        )

    def get(self, name: str) -> ToolSpec | None:
        return next((spec for spec in self.tools if spec.name == name), None)

    def with_tools(self, tools: Sequence[ToolSpec]) -> "ToolRegistry":
        existing = {spec.name for spec in self.tools}
        return ToolRegistry(
            [*self.tools, *(spec for spec in tools if spec.name not in existing)],
            timeout_seconds=self.timeout_seconds,
            max_output_chars=self.max_output_chars,
        )

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def names(self) -> list[str]:
        return [spec.name for spec in self.tools]

    def descriptors(self) -> list[dict[str, Any]]:
        return [spec.prompt_descriptor() for spec in self.tools]

    async def execute(
        self, name: str, arguments: dict[str, object], context: ToolContext
    ) -> ToolResult:
        spec = self.get(name)
        if spec is None:
            return ToolResult(ok=False, error_code="tool_not_found", error=f"Unknown tool: {name}")
        try:
            parsed = spec.args_model.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult(ok=False, error_code="invalid_arguments", error=_short(str(exc)))
        try:
            output = await asyncio.wait_for(
                spec.handler(context, parsed),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            return ToolResult(
                ok=False,
                error_code="tool_timeout",
                error=f"Tool {name} timed out",
            )
        except ToolError as exc:
            return ToolResult(ok=False, error_code=exc.code, error=exc.message)
        except Exception as exc:
            logger.warning("tool %s failed: %s", name, type(exc).__name__)
            return ToolResult(ok=False, error_code="tool_error", error=_short(str(exc)))
        return ToolResult(ok=True, output=_truncate(str(output), self.max_output_chars))


def _short(text: str) -> str:
    return _truncate(text, 300)


def _truncate(text: str, limit: int | None) -> str:
    if limit is None or len(text) <= limit:
        return text
    return text[:limit]
