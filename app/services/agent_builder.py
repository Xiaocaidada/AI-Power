import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    CustomAgent,
    KnowledgeBase,
    ModelCatalog,
    PluginConfig,
    PluginDefinition,
    ProviderConfig,
    ProviderModel,
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
    definition: dict[str, Any]
    summary: str
    missing_resources: list[str]


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
        "allowed_pairs": {(item["provider_id"], item["model"]) for item in models},
        "allowed_kbs": {str(item.id) for item in kbs},
        "allowed_agents": {str(item.id) for item in agents},
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
        for key in ("models", "knowledge_bases", "agents", "plugins")
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
    return list(dict.fromkeys(missing))


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
    try:
        provider = registry.get(provider_id)
    except Exception:
        raise AgentBuilderError(
            "provider_not_found", "Builder provider is not available"
        ) from None
    catalog = await _resource_catalog(session, workspace_id, user_id)
    agent_context = ""
    if raw_agent_id:
        try:
            agent = await session.get(CustomAgent, UUID(raw_agent_id))
        except ValueError:
            agent = None
        if agent is not None and agent.workspace_id == workspace_id:
            agent_context = (
                f"\nCurrent agent:\n{agent.name}\n{agent.description}\n{agent.instructions}"
            )
    system = (
        "You are the AI Power workflow architect. Design an editable agent workflow.\n"
        "Return ONLY one JSON object with keys: summary (string), definition "
        "({nodes: [...], edges: [...]}), missing_resources (string array).\n"
        "Every node is {id, type, config, ui?}. Every edge is {from, to, when?}.\n"
        "Use only the node types and resource IDs listed below. Do not invent IDs.\n"
        "New flows should start with a start node and end with an output node. "
        "Keep the graph acyclic, with exactly one entry node. Keep it under 20 nodes.\n"
        f"{builder_manifest()}\n"
        "Resource catalog:\n"
        f"{json.dumps(_prompt_catalog(catalog), ensure_ascii=False)}"
        f"{agent_context}"
    )
    user_content = f"Requirement:\n{prompt}"
    if current_definition is not None:
        user_content += (
            "\n\nCurrent definition (modify it, preserving valid configuration):\n"
            + json.dumps(current_definition, ensure_ascii=False)
        )
    messages = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=user_content),
    ]
    last_error = ""
    for _attempt in range(3):
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
        elif not isinstance(payload.get("definition"), dict):
            last_error = "Model response is missing definition."
        else:
            try:
                validated = validate_definition(payload["definition"])
            except WorkflowValidationError as exc:
                last_error = str(exc)
            else:
                definition = validated.model_dump(by_alias=True)
                reported = payload.get("missing_resources") or []
                missing = _missing_resources(
                    definition,
                    catalog,
                    reported if isinstance(reported, list) else [],
                )
                summary = str(payload.get("summary", ""))[:2000]
                return AgentBuilderResult(
                    definition=definition,
                    summary=summary,
                    missing_resources=missing,
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
    raise AgentBuilderError("invalid_generation", last_error or "Invalid workflow generation")