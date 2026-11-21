import json
from uuid import UUID, uuid4

import pytest

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


def _tool(name: str, **arguments: object) -> str:
    return json.dumps({"action": "tool", "tool": name, "arguments": arguments})


def _final(answer: str) -> str:
    return json.dumps({"action": "final", "answer": answer})


class ScriptedProvider:
    id = "fake"

    def __init__(self) -> None:
        self.outputs: list[str] = []
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


@pytest.fixture
def scripted():
    from app.deps import get_registry
    from app.main import app
    from app.providers.registry import ProviderRegistry

    script = ScriptedProvider()
    provider_registry = ProviderRegistry({"fake": script})
    app.dependency_overrides[get_registry] = lambda: provider_registry
    yield script
    app.dependency_overrides.pop(get_registry, None)


async def _create_kb(client, headers, name="Agent KB"):
    return await client.post("/knowledge-bases", json={"name": name}, headers=headers)


async def _upload(client, headers, kb_id, content=b"hello world"):
    return await client.post(
        f"/knowledge-bases/{kb_id}/documents",
        files={"file": ("note.txt", content, "text/plain")},
        headers=headers,
    )


async def _create_agent_conversation(client, headers, kb_id=None):
    payload: dict[str, object] = {
        "provider_id": "fake",
        "model": "fake-model",
        "agent": True,
    }
    if kb_id is not None:
        payload["kb_id"] = kb_id
    return await client.post("/conversations", json=payload, headers=headers)


async def _send(client, headers, conversation_id, content="find it"):
    return await client.post(
        f"/conversations/{conversation_id}/messages",
        json={"content": content},
        headers=headers,
    )


async def test_retrieval_agent_searches_kb_and_persists_citations(
    client, api, scripted, fake_ingestion, fake_retrieval
):
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Chunk

    headers = await api.headers("agent-kb@example.com")
    kb = await _create_kb(client, headers)
    await _upload(client, headers, kb.json()["id"])
    conversation = await _create_agent_conversation(client, headers, kb.json()["id"])
    scripted.outputs = [
        _tool("delegate_to_agent", agent="retrieval", task="search the KB for hello"),
        _tool("kb_search", query="hello"),
        _final("found [1]"),
        _final("The document says hello [1]"),
    ]

    response = await _send(client, headers, conversation.json()["id"])

    events = _parse_sse(response.text)
    kinds = [event for event, _ in events]
    assert "tool_call" in kinds
    assert "citation" in kinds
    tool_result = next(data for event, data in events if event == "tool_result")
    assert tool_result["ok"] is True
    assert tool_result["tool"] == "kb_search"
    assert "hello world" in tool_result["output"]
    citation = next(data for event, data in events if event == "citation")
    async with SessionLocal() as session:
        chunk = (await session.execute(select(Chunk))).scalars().first()
    assert chunk is not None
    assert citation["chunk_id"] == str(chunk.id)
    assert citation["snippet"] == "hello world"
    delta = "".join(data["text"] for event, data in events if event == "delta")
    assert delta == "The document says hello [1]"

    detail = await client.get(f"/conversations/{conversation.json()['id']}", headers=headers)
    assert detail.json()["messages"][-1]["citations"] == [citation]

    first_messages = scripted.calls[0]
    assert first_messages[0].role == "system"
    assert "<reference_material>" not in first_messages[0].content

    request_id = detail.json()["messages"][-1]["request_id"]
    trace = await client.get(f"/traces/{request_id}", headers=headers)
    assert "kb_search" in [entry["tool"] for entry in trace.json()["agents"]]


async def test_kb_search_without_knowledge_base_returns_typed_error(
    client, api, scripted, fake_retrieval
):
    headers = await api.headers("agent-no-kb@example.com")
    conversation = await _create_agent_conversation(client, headers)
    scripted.outputs = [
        _tool("delegate_to_agent", agent="retrieval", task="search"),
        _tool("kb_search", query="hello"),
        _final("no KB"),
        _final("done"),
    ]

    response = await _send(client, headers, conversation.json()["id"])

    events = _parse_sse(response.text)
    tool_result = next(data for event, data in events if event == "tool_result")
    assert tool_result["ok"] is False
    assert tool_result["error_code"] == "no_knowledge_base"
    detail = await client.get(f"/conversations/{conversation.json()['id']}", headers=headers)
    assert detail.json()["messages"][-1]["status"] == "completed"


async def test_kb_search_is_scoped_to_the_active_workspace(
    client, api, fake_ingestion, fake_retrieval
):
    from app.tools.base import ToolContext
    from app.tools.registry import build_tool_registry

    alice = await api.headers("agent-kb-alice@example.com")
    bob = await api.headers("agent-kb-bob@example.com")
    kb = await _create_kb(client, alice)
    await _upload(client, alice, kb.json()["id"])
    me = await client.get("/auth/me", headers=bob)
    workspaces = await client.get("/workspaces", headers=bob)
    context = ToolContext(
        workspace_id=UUID(workspaces.json()[0]["id"]),
        user_id=UUID(me.json()["id"]),
        kb_id=UUID(kb.json()["id"]),
        citations=[],
    )

    result = await build_tool_registry().execute("kb_search", {"query": "hello"}, context)

    assert result.ok is True
    assert "No matching material" in result.output
    assert context.citations == []


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 + 2 * 3", "7"),
        ("(2+3)/2", "2.5"),
        ("2 ** 10", "1024"),
        ("-(3)", "-3"),
    ],
)
async def test_calculator_evaluates_safe_expressions(expression, expected):
    from app.tools.base import ToolContext
    from app.tools.registry import build_tool_registry

    result = await build_tool_registry().execute(
        "calculator",
        {"expression": expression},
        ToolContext(workspace_id=uuid4(), user_id=uuid4()),
    )

    assert result.ok is True
    assert result.output == expected


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os')",
        "(1).__class__",
        "abs(-1)",
        "a + 1",
        "9 ** 9 ** 9",
        "1" * 300,
    ],
)
async def test_calculator_rejects_unsafe_expressions(expression):
    from app.tools.base import ToolContext
    from app.tools.registry import build_tool_registry

    result = await build_tool_registry().execute(
        "calculator",
        {"expression": expression},
        ToolContext(workspace_id=uuid4(), user_id=uuid4()),
    )

    assert result.ok is False
    assert result.error_code == "invalid_expression"


async def test_calculator_reports_division_by_zero():
    from app.tools.base import ToolContext
    from app.tools.registry import build_tool_registry

    result = await build_tool_registry().execute(
        "calculator",
        {"expression": "1/0"},
        ToolContext(workspace_id=uuid4(), user_id=uuid4()),
    )

    assert result.ok is False
    assert result.error_code == "calculation_error"


async def test_math_agent_uses_calculator(client, api, scripted):
    headers = await api.headers("agent-math@example.com")
    conversation = await _create_agent_conversation(client, headers)
    scripted.outputs = [
        _tool("delegate_to_agent", agent="math", task="what is 2+2"),
        _tool("calculator", expression="2+2"),
        _final("4"),
        _final("It is 4"),
    ]

    response = await _send(client, headers, conversation.json()["id"], "what is 2+2")

    events = _parse_sse(response.text)
    tool_result = next(data for event, data in events if event == "tool_result")
    assert tool_result["tool"] == "calculator"
    assert tool_result["ok"] is True
    assert tool_result["output"] == "4"
    delta = "".join(data["text"] for event, data in events if event == "delta")
    assert delta == "It is 4"
