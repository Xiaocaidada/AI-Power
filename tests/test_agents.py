import asyncio
import json
from uuid import uuid4

import pytest
from pydantic import BaseModel

from app.deps import get_agent_registry, get_registry, get_tool_registry
from app.main import app
from app.providers.base import ChatChunk, ModelInfo, Usage


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.splitlines()
        event = next(line[len("event: ") :] for line in lines if line.startswith("event: "))
        data = json.loads(
            next(line[len("data: ") :] for line in lines if line.startswith("data: "))
        )
        events.append((event, data))
    return events


def _tool(action_tool: str, **arguments: object) -> str:
    return json.dumps({"action": "tool", "tool": action_tool, "arguments": arguments})


def _final(answer: str) -> str:
    return json.dumps({"action": "final", "answer": answer})


class ScriptedProvider:
    id = "fake"

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls: list[list[object]] = []
        self.models = [ModelInfo(id="fake-model", provider_id="fake")]

    async def list_models(self):
        return list(self.models)

    async def stream_chat(self, messages, model, **_opts):
        self.calls.append(list(messages))
        output = self.outputs.pop(0) if self.outputs else _final("out of script")
        yield ChatChunk(delta=output)
        yield ChatChunk(usage=Usage(prompt_tokens=10, completion_tokens=5))
        yield ChatChunk(finish_reason="stop")


class EchoArgs(BaseModel):
    text: str


def _echo_spec(fail_on: str | None = None):
    from app.tools.base import ToolSpec

    async def handler(context, args: EchoArgs) -> str:
        if fail_on is not None and args.text == fail_on:
            raise ValueError("boom")
        return f"echo:{args.text}"

    return ToolSpec(
        name="echo",
        description="Echo the given text.",
        args_model=EchoArgs,
        handler=handler,
    )


def _agent_registry(tools=("echo",)):
    from app.agents.base import AgentSpec
    from app.agents.registry import AgentRegistry

    return AgentRegistry(
        [
            AgentSpec(name="supervisor", system_prompt="Supervise.", tools=()),
            AgentSpec(name="retrieval", system_prompt="Retrieve.", tools=tools),
            AgentSpec(name="math", system_prompt="Calculate.", tools=()),
        ]
    )


@pytest.fixture
def scripted():
    from app.providers.registry import ProviderRegistry
    from app.tools.base import ToolRegistry

    script = ScriptedProvider([])
    provider_registry = ProviderRegistry({"fake": script})
    tool_registry = ToolRegistry([_echo_spec(fail_on="fail")])
    app.dependency_overrides[get_registry] = lambda: provider_registry
    app.dependency_overrides[get_tool_registry] = lambda: tool_registry
    app.dependency_overrides[get_agent_registry] = lambda: _agent_registry()
    yield script
    app.dependency_overrides.pop(get_registry, None)
    app.dependency_overrides.pop(get_tool_registry, None)
    app.dependency_overrides.pop(get_agent_registry, None)


async def _new_agent_conversation(client, headers):
    created = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model", "agent": True},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def test_multi_agent_delegates_and_runs_tool(client, api, scripted):
    scripted.outputs = [
        _tool("delegate_to_agent", agent="retrieval", task="find X"),
        _tool("echo", text="X"),
        _final("retrieved X"),
        _final("answer: retrieved X"),
    ]
    headers = await api.headers("agent-flow@example.com")
    conversation_id = await _new_agent_conversation(client, headers)

    response = await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "What is X?"},
        headers=headers,
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    kinds = [event for event, _ in events]
    assert kinds == [
        "meta",
        "agent_start",
        "agent_start",
        "tool_call",
        "tool_result",
        "agent_end",
        "delta",
        "agent_end",
        "usage",
        "done",
    ]
    starts = [data for event, data in events if event == "agent_start"]
    assert [(item["agent"], item["depth"]) for item in starts] == [
        ("supervisor", 0),
        ("retrieval", 1),
    ]
    tool_call = next(data for event, data in events if event == "tool_call")
    assert tool_call == {"agent": "retrieval", "tool": "echo", "arguments": {"text": "X"}}
    tool_result = next(data for event, data in events if event == "tool_result")
    assert tool_result["ok"] is True
    assert tool_result["output"] == "echo:X"
    delta = "".join(data["text"] for event, data in events if event == "delta")
    assert delta == "answer: retrieved X"
    usage = next(data for event, data in events if event == "usage")
    assert usage == {"prompt_tokens": 40, "completion_tokens": 20}
    assert len(scripted.calls) == 4

    detail = await client.get(f"/conversations/{conversation_id}", headers=headers)
    assistant = detail.json()["messages"][-1]
    assert assistant["content"] == "answer: retrieved X"
    assert assistant["status"] == "completed"
    assert assistant["prompt_tokens"] == 40
    assert assistant["completion_tokens"] == 20

    trace = await client.get(f"/traces/{assistant['request_id']}", headers=headers)
    assert trace.status_code == 200
    agents = trace.json()["agents"]
    tools = [entry["tool"] for entry in agents]
    assert "delegate_to_agent" in tools
    assert "echo" in tools


async def test_agent_tool_error_is_reported_and_run_completes(client, api, scripted):
    scripted.outputs = [
        _tool("delegate_to_agent", agent="retrieval", task="find X"),
        _tool("echo", text="fail"),
        _final("retrieval failed"),
        _final("recovered"),
    ]
    headers = await api.headers("agent-tool-error@example.com")
    conversation_id = await _new_agent_conversation(client, headers)

    response = await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "What is X?"},
        headers=headers,
    )

    events = _parse_sse(response.text)
    tool_result = next(data for event, data in events if event == "tool_result")
    assert tool_result["ok"] is False
    assert tool_result["error_code"] == "tool_error"
    delta = "".join(data["text"] for event, data in events if event == "delta")
    assert delta == "recovered"
    detail = await client.get(f"/conversations/{conversation_id}", headers=headers)
    assert detail.json()["messages"][-1]["status"] == "completed"


async def test_subagent_cannot_delegate(client, api, scripted):
    scripted.outputs = [
        _tool("delegate_to_agent", agent="retrieval", task="find X"),
        _tool("delegate_to_agent", agent="math", task="1+1"),
        _final("retrieved X"),
        _final("answer"),
    ]
    headers = await api.headers("agent-nested@example.com")
    conversation_id = await _new_agent_conversation(client, headers)

    response = await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "What is X?"},
        headers=headers,
    )

    events = _parse_sse(response.text)
    tool_result = next(data for event, data in events if event == "tool_result")
    assert tool_result["ok"] is False
    assert tool_result["error_code"] == "delegation_not_allowed"


async def test_agent_step_limit_emits_error(client, api, scripted):
    scripted.outputs = [_tool("echo", text="x") for _ in range(8)]
    headers = await api.headers("agent-limit@example.com")
    conversation_id = await _new_agent_conversation(client, headers)

    response = await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "loop"},
        headers=headers,
    )

    events = _parse_sse(response.text)
    error = next(data for event, data in events if event == "error")
    assert error["code"] == "agent_step_limit"
    detail = await client.get(f"/conversations/{conversation_id}", headers=headers)
    assert detail.json()["messages"][-1]["status"] == "failed"


async def test_plain_text_output_falls_back_to_final_answer(client, api, scripted):
    scripted.outputs = ["hello there"]
    headers = await api.headers("agent-plain@example.com")
    conversation_id = await _new_agent_conversation(client, headers)

    response = await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": "hi"},
        headers=headers,
    )

    events = _parse_sse(response.text)
    assert [event for event, _ in events] == [
        "meta",
        "agent_start",
        "delta",
        "agent_end",
        "usage",
        "done",
    ]
    assert events[2][1] == {"text": "hello there"}


async def test_conversation_persists_agent_flag(client, api, scripted):
    headers = await api.headers("agent-flag@example.com")
    conversation_id = await _new_agent_conversation(client, headers)
    plain = await client.post(
        "/conversations",
        json={"provider_id": "fake", "model": "fake-model"},
        headers=headers,
    )

    detail = await client.get(f"/conversations/{conversation_id}", headers=headers)

    assert detail.json()["agent"] is True
    assert plain.json()["agent"] is False


async def test_tool_registry_rejects_invalid_arguments():
    from app.tools.base import ToolContext, ToolRegistry

    registry = ToolRegistry([_echo_spec()])
    result = await registry.execute(
        "echo", {"nope": "x"}, ToolContext(workspace_id=uuid4(), user_id=uuid4())
    )

    assert result.ok is False
    assert result.error_code == "invalid_arguments"


async def test_tool_registry_times_out():
    from app.tools.base import ToolContext, ToolRegistry, ToolSpec

    class SlowArgs(BaseModel):
        pass

    async def slow(context, args) -> str:
        await asyncio.sleep(0.2)
        return "late"

    registry = ToolRegistry(
        [ToolSpec(name="slow", description="slow", args_model=SlowArgs, handler=slow)],
        timeout_seconds=0.01,
    )
    result = await registry.execute("slow", {}, ToolContext(workspace_id=uuid4(), user_id=uuid4()))

    assert result.ok is False
    assert result.error_code == "tool_timeout"
