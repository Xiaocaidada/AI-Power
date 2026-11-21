import json
import re
from dataclasses import dataclass

PROTOCOL_HINT = (
    "Reply with exactly one JSON object and nothing else. "
    'To call a tool: {"action": "tool", "tool": "<tool_name>", "arguments": {...}}. '
    'To answer the user: {"action": "final", "answer": "<answer>"}. '
    "Never wrap the JSON in prose or code fences."
)

_FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


@dataclass(frozen=True, slots=True)
class ToolCall:
    tool: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class FinalAnswer:
    content: str


def parse_agent_output(text: str) -> ToolCall | FinalAnswer:
    """Parse one model turn; anything that is not a valid tool call is an answer."""
    stripped = _strip_fence(text.strip())
    payload = _load_object(stripped)
    if payload is not None:
        action = payload.get("action")
        if action == "tool":
            tool = payload.get("tool")
            arguments = payload.get("arguments", {})
            if isinstance(tool, str) and isinstance(arguments, dict):
                return ToolCall(tool=tool, arguments=arguments)
        elif action == "final":
            answer = payload.get("answer")
            if isinstance(answer, str):
                return FinalAnswer(answer)
    return FinalAnswer(stripped)


def _strip_fence(text: str) -> str:
    match = _FENCE.match(text)
    return match.group(1).strip() if match is not None else text


def _load_object(text: str) -> dict[str, object] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return value if isinstance(value, dict) else None
