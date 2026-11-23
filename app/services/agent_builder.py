import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentBuilderSession,
    CustomAgent,
    KnowledgeBase,
    McpServer,
    ModelCatalog,
    PluginConfig,
    PluginDefinition,
    ProviderConfig,
    ProviderModel,
    Workflow,
    WorkflowNodeRun,
    WorkflowRun,
)
from app.providers.base import ChatMessage
from app.providers.registry import ProviderRegistry
from app.services.model_stream import ModelCompletion
from app.services.usage_ledger import SOURCE_AGENT_BUILDER
from app.services.workflow.catalog import builder_manifest
from app.services.workflow.schema import WorkflowValidationError, validate_definition


class AgentBuilderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class AgentBuilderResult:
    message: str
    definition: dict[str, Any] | None
    summary: str
    missing_resources: list[str]
    suggestions: list[str]
    diff: dict[str, Any] | None


async def _resource_catalog(
    session: AsyncSession, workspace_id: UUID, user_id: UUID
) -> dict[str, Any]:
    platform_models = list(
        (
            await session.execute(
                select(ModelCatalog).where(ModelCatalog.enabled.is_(True))
            )
        ).scalars()
    )
    personal_models = list(
        (
            await session.execute(
                select(ProviderModel, ProviderConfig)
                .join(ProviderConfig, ProviderConfig.id == ProviderModel.config_id)
                .where(
                    ProviderConfig.workspace_id == workspace_id,
                    ProviderConfig.deleted_at.is_(None),
                    or_(
                        ProviderConfig.owner_user_id == user_id,
                        ProviderConfig.shared.is_(True),
                    ),
                    ProviderModel.enabled.is_(True),
                )
            )
        ).all()
    )
    kbs = list(
        (
            await session.execute(
                select(KnowledgeBase).where(
                    KnowledgeBase.workspace_id == workspace_id,
                    KnowledgeBase.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    agents = list(
        (
            await session.execute(
                select(CustomAgent).where(
                    CustomAgent.workspace_id == workspace_id,
                    CustomAgent.archived_at.is_(None),
                    or_(
                        CustomAgent.owner_user_id == user_id,
                        CustomAgent.visibility == "shared",
                    ),
                )
            )
        ).scalars()
    )
    plugins = list(
        (
            await session.execute(
                select(PluginDefinition)
                .join(
                    PluginConfig,
                    (PluginConfig.plugin_id == PluginDefinition.id)
                    & (PluginConfig.workspace_id == workspace_id)
                    & (PluginConfig.enabled.is_(True)),
                )
                .where(PluginDefinition.enabled.is_(True))
            )
        ).scalars()
    )
    mcp_servers = list(
        (
            await session.execute(
                select(McpServer).where(McpServer.enabled.is_(True)).order_by(McpServer.name)
            )
        ).scalars()
    )
    models = [
        {
            "provider_id": item.provider_id,
            "model": item.model_id,
            "label": item.display_name,
        }
        for item in platform_models
    ]
    models.extend(
        {
            "provider_id": str(config.id),
            "model": model.model_id,
            "label": model.display_name or model.model_id,
        }
        for model, config in personal_models
    )
    return {
        "models": models,
        "knowledge_bases": [
            {"id": str(item.id), "name": item.name, "description": item.description}
            for item in kbs
        ],
        "agents": [
            {
                "id": str(item.id),
                "name": item.name,
                "description": item.description,
                "mode": item.mode,
            }
            for item in agents
        ],
        "plugins": [
            {"id": str(item.id), "name": item.name, "description": item.description}
            for item in plugins
        ],
        "mcp_servers": [
            {"id": str(item.id), "name": item.name, "description": item.description}
            for item in mcp_servers
        ],
        "allowed_pairs": {(item["provider_id"], item["model"]) for item in models},
        "allowed_kbs": {str(item.id) for item in kbs},
        "allowed_agents": {str(item.id) for item in agents},
        "allowed_mcp": {str(item.id) for item in mcp_servers},
    }


def _parse_json(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match is None:
        return None
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _prompt_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        key: catalog[key]
        for key in ("models", "knowledge_bases", "agents", "plugins", "mcp_servers")
    }


def _missing_resources(
    definition: dict[str, Any],
    catalog: dict[str, Any],
    reported: Sequence[object],
) -> list[str]:
    missing: list[str] = [str(item) for item in reported if str(item).strip()]
    allowed_pairs = catalog["allowed_pairs"]
    allowed_kbs = catalog["allowed_kbs"]
    allowed_agents = catalog["allowed_agents"]
    allowed_mcp = catalog["allowed_mcp"]
    for node in definition.get("nodes", []):
        if not isinstance(node, dict):
            continue
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        provider_id = config.get("provider_id")
        model = config.get("model")
        if (
            isinstance(provider_id, str)
            and isinstance(model, str)
            and provider_id != "auto"
            and (provider_id, model) not in allowed_pairs
        ):
            missing.append(f"模型 {provider_id}/{model}")
        for kb_id in config.get("kb_ids") or []:
            if str(kb_id) not in allowed_kbs:
                missing.append(f"知识库 {kb_id}")
        agent_id = config.get("agent_id")
        if agent_id is not None and str(agent_id) not in allowed_agents:
            missing.append(f"Agent {agent_id}")
        server_id = config.get("server_id")
        if server_id is not None and str(server_id) not in allowed_mcp:
            missing.append(f"MCP 服务器 {server_id}")
    return list(dict.fromkeys(missing))


def _edge_view(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "from": str(edge.get("from", "")),
        "to": str(edge.get("to", "")),
        "when": edge.get("when"),
    }


def diff_definitions(
    old: dict[str, Any], new: dict[str, Any]
) -> dict[str, Any]:
    old_nodes = {
        str(node.get("id")): node
        for node in old.get("nodes", [])
        if isinstance(node, dict) and node.get("id") is not None
    }
    new_nodes = {
        str(node.get("id")): node
        for node in new.get("nodes", [])
        if isinstance(node, dict) and node.get("id") is not None
    }
    added_nodes = [
        {"id": node_id, "type": new_nodes[node_id].get("type", "")}
        for node_id in new_nodes
        if node_id not in old_nodes
    ]
    removed_nodes = [
        {"id": node_id, "type": old_nodes[node_id].get("type", "")}
        for node_id in old_nodes
        if node_id not in new_nodes
    ]
    updated_nodes: list[dict[str, Any]] = []
    for node_id in sorted(set(old_nodes) & set(new_nodes)):
        before = old_nodes[node_id]
        after = new_nodes[node_id]
        changes: list[dict[str, Any]] = []
        if before.get("type") != after.get("type"):
            changes.append(
                {
                    "field": "type",
                    "before": before.get("type"),
                    "after": after.get("type"),
                }
            )
        before_config = before.get("config") if isinstance(before.get("config"), dict) else {}
        after_config = after.get("config") if isinstance(after.get("config"), dict) else {}
        for key in sorted(set(before_config) | set(after_config)):
            if before_config.get(key) != after_config.get(key):
                changes.append(
                    {
                        "field": f"config.{key}",
                        "before": before_config.get(key),
                        "after": after_config.get(key),
                    }
                )
        if before.get("ui") != after.get("ui"):
            changes.append(
                {"field": "ui", "before": before.get("ui"), "after": after.get("ui")}
            )
        if changes:
            updated_nodes.append(
                {"id": node_id, "type": after.get("type", ""), "changes": changes}
            )

    old_edges = {
        json.dumps(_edge_view(edge), sort_keys=True): _edge_view(edge)
        for edge in old.get("edges", [])
        if isinstance(edge, dict)
    }
    new_edges = {
        json.dumps(_edge_view(edge), sort_keys=True): _edge_view(edge)
        for edge in new.get("edges", [])
        if isinstance(edge, dict)
    }
    added_edges = [value for key, value in new_edges.items() if key not in old_edges]
    removed_edges = [value for key, value in old_edges.items() if key not in new_edges]
    return {
        "added_nodes": added_nodes,
        "removed_nodes": removed_nodes,
        "updated_nodes": updated_nodes,
        "added_edges": added_edges,
        "removed_edges": removed_edges,
    }


def _mode_instruction(kind: str) -> str:
    if kind == "explain":
        return (
            "Explain the current workflow clearly and suggest concrete optimizations. "
            "Do NOT rewrite the workflow unless the user explicitly asks; include a full "
            "definition only when proposing a concrete improved version."
        )
    if kind == "fix":
        return (
            "Analyze the failed run and node errors. Return a corrected full definition "
            "that addresses the failure, plus a message explaining the fix."
        )
    if kind == "modify":
        return (
            "Apply the user's requested change to the current definition. Preserve valid "
            "configuration and return the complete updated definition."
        )
    return "Create a new workflow from the requirement and return the complete definition."


def _run_context_text(run_context: dict[str, Any] | None) -> str:
    if not run_context:
        return ""
    return (
        "\n\nFailed run context:\n"
        + json.dumps(run_context, ensure_ascii=False)
    )


async def _agent_context(
    session: AsyncSession, workspace_id: UUID, raw_agent_id: str | None
) -> str:
    if not raw_agent_id:
        return ""
    try:
        agent = await session.get(CustomAgent, UUID(raw_agent_id))
    except ValueError:
        return ""
    if agent is None or agent.workspace_id != workspace_id:
        return ""
    return f"\nCurrent agent:\n{agent.name}\n{agent.description}\n{agent.instructions}"


async def run_builder_turn(
    session: AsyncSession,
    registry: ProviderRegistry,
    *,
    workspace_id: UUID,
    user_id: UUID,
    kind: str,
    prompt: str,
    provider_id: str,
    model: str,
    current_definition: dict | None = None,
    raw_agent_id: str | None = None,
    run_context: dict[str, Any] | None = None,
) -> AgentBuilderResult:
    try:
        provider = registry.get(provider_id)
    except Exception:
        raise AgentBuilderError(
            "provider_not_found", "Builder provider is not available"
        ) from None
    catalog = await _resource_catalog(session, workspace_id, user_id)
    agent_context = await _agent_context(session, workspace_id, raw_agent_id)
    system = (
        "You are the AI Power workflow architect. Work only with the AI Power node "
        "manifest and resource catalog below.\n"
        "Return ONLY one JSON object with keys: message (string), summary (string), "
        "definition (optional for explain), missing_resources (string array), "
        "suggestions (string array).\n"
        "Every node is {id, type, config, ui?}. Every edge is {from, to, when?}.\n"
        "Use only listed node types and resource IDs. Do not invent IDs or credentials.\n"
        "Keep the graph acyclic with exactly one entry node and at most 20 nodes. "
        "New flows start with a start node and end with an output node.\n"
        f"{_mode_instruction(kind)}\n"
        f"{builder_manifest()}\n"
        "Resource catalog:\n"
        f"{json.dumps(_prompt_catalog(catalog), ensure_ascii=False)}"
        f"{agent_context}"
    )
    user_content = f"Task ({kind}):\n{prompt}"
    if current_definition:
        user_content += (
            "\n\nCurrent definition:\n"
            + json.dumps(current_definition, ensure_ascii=False)
        )
    user_content += _run_context_text(run_context)
    messages = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=user_content),
    ]
    last_error = ""
    for _attempt in range(3):
        last_error = ""
        completion = ModelCompletion(
            provider=provider,
            model=model,
            messages=messages,
            opts={"temperature": 0.1, "max_tokens": 6000},
            workspace_id=workspace_id,
            user_id=user_id,
            source=SOURCE_AGENT_BUILDER,
        )
        metrics = await completion.run()
        if metrics.status != "completed":
            raise AgentBuilderError(
                metrics.error_code or "builder_failed", "Workflow generation failed"
            )
        payload = _parse_json(metrics.content)
        if payload is None:
            last_error = "Model did not return valid JSON."
        else:
            raw_definition = payload.get("definition")
            definition: dict[str, Any] | None = None
            if raw_definition is not None and not isinstance(raw_definition, dict):
                last_error = "definition must be an object."
            elif raw_definition is None and kind != "explain":
                last_error = "Model response is missing definition."
            elif isinstance(raw_definition, dict):
                try:
                    validated = validate_definition(raw_definition)
                except WorkflowValidationError as exc:
                    last_error = str(exc)
                else:
                    definition = validated.model_dump(by_alias=True)
            if last_error:
                pass
            else:
                message = str(
                    payload.get("message") or payload.get("summary") or ""
                )[:4000]
                if kind == "explain" and definition is None and message == "":
                    last_error = "Explain response is empty."
                else:
                    reported = payload.get("missing_resources") or []
                    missing = (
                        _missing_resources(
                            definition,
                            catalog,
                            reported if isinstance(reported, list) else [],
                        )
                        if definition is not None
                        else []
                    )
                    suggestions = [
                        str(item)
                        for item in (payload.get("suggestions") or [])
                        if str(item).strip()
                    ][:20]
                    summary = str(payload.get("summary") or message)[:2000]
                    diff = (
                        diff_definitions(current_definition, definition)
                        if definition is not None and current_definition
                        else None
                    )
                    return AgentBuilderResult(
                        message=message or summary,
                        definition=definition,
                        summary=summary,
                        missing_resources=missing,
                        suggestions=suggestions,
                        diff=diff,
                    )
        messages.append(
            ChatMessage(
                role="user",
                content=(
                    "The previous output was invalid for these reasons:\n"
                    f"{last_error}\nReturn a corrected JSON object only."
                ),
            )
        )
    raise AgentBuilderError(
        "invalid_generation", last_error or "Invalid workflow generation"
    )


async def generate_agent_workflow(
    session: AsyncSession,
    registry: ProviderRegistry,
    *,
    workspace_id: UUID,
    user_id: UUID,
    prompt: str,
    provider_id: str,
    model: str,
    current_definition: dict | None = None,
    raw_agent_id: str | None = None,
) -> AgentBuilderResult:
    result = await run_builder_turn(
        session,
        registry,
        workspace_id=workspace_id,
        user_id=user_id,
        kind="generate",
        prompt=prompt,
        provider_id=provider_id,
        model=model,
        current_definition=current_definition,
        raw_agent_id=raw_agent_id,
    )
    if result.definition is None:
        raise AgentBuilderError("invalid_generation", "Model returned no definition")
    return result


async def _validate_session_targets(
    session: AsyncSession,
    workspace_id: UUID,
    agent_id: UUID | None,
    workflow_id: UUID | None,
) -> None:
    if agent_id is not None:
        agent = await session.get(CustomAgent, agent_id)
        if agent is None or agent.workspace_id != workspace_id or agent.archived_at is not None:
            raise AgentBuilderError("agent_not_found", "Agent not found")
    if workflow_id is not None:
        workflow = await session.get(Workflow, workflow_id)
        if (
            workflow is None
            or workflow.workspace_id != workspace_id
            or workflow.deleted_at is not None
        ):
            raise AgentBuilderError("workflow_not_found", "Workflow not found")


async def create_builder_session(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    agent_id: UUID | None,
    workflow_id: UUID | None,
    provider_id: str,
    model: str,
    draft_definition: dict | None,
) -> AgentBuilderSession:
    await _validate_session_targets(session, workspace_id, agent_id, workflow_id)
    row = AgentBuilderSession(
        workspace_id=workspace_id,
        user_id=user_id,
        agent_id=agent_id,
        workflow_id=workflow_id,
        provider_id=provider_id,
        model=model,
        messages=[],
        draft_definition=draft_definition or {},
    )
    session.add(row)
    await session.flush()
    return row


async def get_builder_session(
    session: AsyncSession, session_id: UUID, workspace_id: UUID, user_id: UUID
) -> AgentBuilderSession:
    row = await session.get(AgentBuilderSession, session_id)
    if (
        row is None
        or row.workspace_id != workspace_id
        or row.user_id != user_id
    ):
        raise AgentBuilderError("session_not_found", "Builder session not found")
    return row


async def list_builder_sessions(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    *,
    agent_id: UUID | None = None,
) -> list[AgentBuilderSession]:
    conditions = [
        AgentBuilderSession.workspace_id == workspace_id,
        AgentBuilderSession.user_id == user_id,
    ]
    if agent_id is not None:
        conditions.append(AgentBuilderSession.agent_id == agent_id)
    rows = (
        await session.execute(
            select(AgentBuilderSession)
            .where(*conditions)
            .order_by(AgentBuilderSession.updated_at.desc())
            .limit(20)
        )
    ).scalars().all()
    return list(rows)


def append_builder_message(
    row: AgentBuilderSession, message: dict[str, Any]
) -> None:
    messages = list(row.messages or [])
    messages.append(message)
    row.messages = messages[-60:]


async def apply_builder_definition(
    session: AsyncSession, row: AgentBuilderSession, definition: dict
) -> dict[str, Any]:
    try:
        validated = validate_definition(definition)
    except WorkflowValidationError as exc:
        raise AgentBuilderError("invalid_definition", str(exc)) from None
    applied = validated.model_dump(by_alias=True)
    row.draft_definition = applied
    append_builder_message(
        row,
        {
            "role": "assistant",
            "kind": "apply",
            "content": "Applied to canvas",
            "definition": applied,
            "created_at": datetime.now(UTC).isoformat(),
        },
    )
    await session.flush()
    return applied


async def build_run_context(
    session: AsyncSession, run_id: UUID, workspace_id: UUID
) -> dict[str, Any]:
    run = await session.get(WorkflowRun, run_id)
    if run is None or run.workspace_id != workspace_id:
        raise AgentBuilderError("run_not_found", "Workflow run not found")
    nodes = (
        await session.execute(
            select(WorkflowNodeRun)
            .where(WorkflowNodeRun.run_id == run.id)
            .order_by(WorkflowNodeRun.created_at, WorkflowNodeRun.id)
        )
    ).scalars().all()
    return {
        "run_id": str(run.id),
        "workflow_id": str(run.workflow_id),
        "status": run.status,
        "error_code": run.error_code,
        "nodes": [
            {
                "node_id": node.node_id,
                "node_type": node.node_type,
                "status": node.status,
                "error_code": node.error_code,
                "input_summary": node.input_summary,
                "output_summary": node.output_summary,
            }
            for node in nodes
        ],
    }