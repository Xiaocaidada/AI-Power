"""Built-in Agent workflow templates and atomic create-from-template."""

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CustomAgent, ModelCatalog, Workflow, WorkflowVersion
from app.services.workflow.schema import (
    WorkflowValidationError,
    validate_definition,
)


class AgentTemplateError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _template(
    *,
    template_id: str,
    name: str,
    description: str,
    icon: str,
    instructions: str,
    tools: list[str],
    mode: str,
    definition: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": template_id,
        "name": name,
        "description": description,
        "icon": icon,
        "instructions": instructions,
        "tools": tools,
        "mode": mode,
        "definition": definition,
    }


AGENT_TEMPLATES: list[dict[str, Any]] = [
    _template(
        template_id="assistant",
        name="通用助手",
        description="单 Agent 自主完成输入任务，可调用时间工具，适合通用问答与轻量任务。",
        icon="🤖",
        instructions="你是一个可靠的通用助手。理解用户目标，必要时使用工具，最后给出简洁明确的答案。",
        tools=["current_time"],
        mode="hybrid",
        definition={
            "nodes": [
                {"id": "start", "type": "start", "config": {}, "ui": {"x": 80, "y": 160}},
                {
                    "id": "assistant",
                    "type": "agent",
                    "config": {
                        "task": "{{input}}",
                        "tools": ["current_time"],
                    },
                    "ui": {"x": 320, "y": 160},
                },
                {"id": "out", "type": "output", "config": {}, "ui": {"x": 620, "y": 160}},
            ],
            "edges": [
                {"from": "start", "to": "assistant"},
                {"from": "assistant", "to": "out"},
            ],
        },
    ),
    _template(
        template_id="research",
        name="知识库研究",
        description="先检索知识库，再让模型基于检索材料作答，适合文档问答与研究。",
        icon="📚",
        instructions="你是一名研究助手。先检索知识库，再基于材料回答，并说明不确定之处。",
        tools=["kb_search"],
        mode="hybrid",
        definition={
            "nodes": [
                {"id": "start", "type": "start", "config": {}, "ui": {"x": 80, "y": 160}},
                {
                    "id": "retrieve",
                    "type": "kb_search",
                    "config": {"query": "{{input}}", "kb_ids": []},
                    "ui": {"x": 300, "y": 160},
                },
                {
                    "id": "answer",
                    "type": "llm",
                    "config": {
                        "provider_id": "",
                        "model": "",
                        "prompt": (
                            "请基于以下检索材料回答问题。\n\n"
                            "问题：{{input}}\n\n材料：\n{{retrieve}}"
                        ),
                    },
                    "ui": {"x": 540, "y": 160},
                },
                {"id": "out", "type": "output", "config": {}, "ui": {"x": 820, "y": 160}},
            ],
            "edges": [
                {"from": "start", "to": "retrieve"},
                {"from": "retrieve", "to": "answer"},
                {"from": "answer", "to": "out"},
            ],
        },
    ),
    _template(
        template_id="reviewed",
        name="人工审核助手",
        description="Agent 生成初稿后进入人工审核，通过后再输出，适合对外内容与高风险操作。",
        icon="🛡️",
        instructions="你是一个谨慎的内容助手。生成可审核的初稿，清楚标注依据与风险。",
        tools=["current_time"],
        mode="hybrid",
        definition={
            "nodes": [
                {"id": "start", "type": "start", "config": {}, "ui": {"x": 80, "y": 160}},
                {
                    "id": "draft",
                    "type": "agent",
                    "config": {"task": "{{input}}", "tools": ["current_time"]},
                    "ui": {"x": 300, "y": 160},
                },
                {
                    "id": "review",
                    "type": "review",
                    "config": {
                        "prompt": "请审核以下初稿，通过后继续输出：\n\n{{draft}}",
                        "timeout_seconds": 3600,
                    },
                    "ui": {"x": 540, "y": 160},
                },
                {"id": "out", "type": "output", "config": {}, "ui": {"x": 800, "y": 160}},
            ],
            "edges": [
                {"from": "start", "to": "draft"},
                {"from": "draft", "to": "review"},
                {"from": "review", "to": "out"},
            ],
        },
    ),
]

TEMPLATE_BY_ID = {item["id"]: item for item in AGENT_TEMPLATES}


def list_agent_templates() -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "description": item["description"],
            "icon": item["icon"],
            "definition": json.loads(json.dumps(item["definition"])),
        }
        for item in AGENT_TEMPLATES
    ]


async def _default_model_pair(
    session: AsyncSession,
) -> tuple[str, str] | None:
    row = (
        await session.execute(
            select(ModelCatalog)
            .where(ModelCatalog.enabled.is_(True))
            .order_by(ModelCatalog.priority, ModelCatalog.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return row.provider_id, row.model_id


def _fill_template_models(
    definition: dict[str, Any], provider_id: str, model: str
) -> dict[str, Any]:
    copied = json.loads(json.dumps(definition))
    for node in copied.get("nodes", []):
        if not isinstance(node, dict):
            continue
        if node.get("type") not in {"llm", "agent", "loop"}:
            continue
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        if not config.get("provider_id") or not config.get("model"):
            config["provider_id"] = provider_id
            config["model"] = model
    return copied


async def create_agent_from_template(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    template_id: str,
    name: str,
    description: str = "",
    category: str = "general",
    provider_id: str | None = None,
    model: str | None = None,
) -> CustomAgent:
    template = TEMPLATE_BY_ID.get(template_id)
    if template is None:
        raise AgentTemplateError("unknown_template", "Unknown Agent template")
    existing = (
        await session.execute(
            select(CustomAgent.id).where(
                CustomAgent.workspace_id == workspace_id,
                CustomAgent.name == name,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AgentTemplateError("duplicate", "Agent name already exists")

    resolved_provider = provider_id
    resolved_model = model
    if not resolved_provider or resolved_provider == "auto" or not resolved_model:
        pair = await _default_model_pair(session)
        if pair is None:
            raise AgentTemplateError(
                "model_required", "Configure a model before creating this template"
            )
        resolved_provider, resolved_model = pair

    definition = _fill_template_models(
        template["definition"], resolved_provider, resolved_model
    )
    try:
        parsed = validate_definition(definition)
    except WorkflowValidationError as exc:
        raise AgentTemplateError("invalid_template", str(exc)) from None

    workflow = Workflow(
        workspace_id=workspace_id,
        created_by=user_id,
        name=name[:120],
        description=description[:500] or template["description"],
        kind="agent",
    )
    session.add(workflow)
    await session.flush()
    session.add(
        WorkflowVersion(
            workflow_id=workflow.id,
            version=1,
            definition=parsed.model_dump(by_alias=True),
        )
    )
    agent = CustomAgent(
        workspace_id=workspace_id,
        owner_user_id=user_id,
        name=name,
        description=description or template["description"],
        instructions=template["instructions"],
        category=category,
        mode=template["mode"],
        icon=template["icon"],
        welcome_message=f"使用「{template['name']}」开始。",
        examples=[],
        usage_instructions=template["description"],
        generation_settings={},
        default_provider_id=resolved_provider,
        default_model=resolved_model,
        kb_ids=[],
        tools=list(template["tools"]),
        plugin_ids=[],
        workflow_id=workflow.id,
        visibility="private",
    )
    session.add(agent)
    await session.flush()
    return agent