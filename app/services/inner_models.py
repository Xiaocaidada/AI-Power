"""Built-in model catalog read from ``inner_models/*.json``.

The catalog only supplies marketplace display metadata. Provider credentials
(API key + base URL) are always supplied by the user at activation time; no key
is bundled with these files.
"""

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)
NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")
NEW_MODEL_WINDOW_SECONDS = 180 * 24 * 60 * 60

PROVIDER_CATALOG: dict[str, dict[str, str]] = {
    "zhipu": {
        "name": "智谱 AI",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "docs_url": "https://open.bigmodel.cn/dev/api",
    },
    "aliyun": {
        "name": "阿里云百炼",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "docs_url": "https://help.aliyun.com/zh/model-studio/",
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "docs_url": "https://platform.openai.com/docs/models",
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "docs_url": "https://api-docs.deepseek.com/",
    },
}

# Model kinds that cannot answer chat turns are not offered for BYOK chat.
NON_CHAT_TYPES = frozenset(
    {
        "audio",
        "realtime",
        "image",
        "image_generation",
        "moderation",
        "embedding",
        "reranker",
        "vision_ocr",
    }
)

_NAME_SUFFIXES = {
    "air": "Air",
    "flash": "Flash",
    "flashx": "FlashX",
    "turbo": "Turbo",
    "legal": "Legal",
    "pro": "Pro",
    "max": "Max",
    "mini": "Mini",
    "plus": "Plus",
    "preview": "Preview",
    "latest": "Latest",
    "coder": "Coder",
    "coding": "Coding",
    "instruct": "Instruct",
    "reasoning": "Reasoning",
    "search": "Search",
    "api": "API",
    "chat": "Chat",
    "flash_realtime": "Flash Realtime",
}

_NAME_FAMILIES = {
    "gpt": "GPT",
    "qwen": "Qwen",
    "deepseek": "DeepSeek",
    "glm": "GLM",
    "kimi": "Kimi",
    "claude": "Claude",
    "gemini": "Gemini",
    "ling": "Ling",
    "tongyi": "Tongyi",
    "omni": "Omni",
    "xing": "Xing",
    "grok": "Grok",
    "llama": "Llama",
    "mixtral": "Mixtral",
    "command": "Command",
    "o": "O",
}


@dataclass(frozen=True, slots=True)
class InnerModel:
    id: uuid.UUID
    slug: str
    name: str
    provider_id: str
    provider_name: str
    model_id: str
    description: str
    category: str
    capabilities: list[str]
    input_types: list[str]
    output_types: list[str]
    context_window: int
    max_output: int | None
    thinking_supported: bool
    thinking_required: bool
    thinking_levels: list[str]
    provider_base_url: str
    docs_url: str
    featured: bool
    is_new: bool
    sort_order: int


_cache: dict[tuple[str, tuple[str, ...], float], list[InnerModel]] = {}


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _first_int(item: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = _as_int(item.get(key))
        if value is not None and value > 0:
            return value
    return None


def _level_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    levels: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            continue
        level = raw.strip().lower()
        if level and re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,39}", level) and level not in levels:
            levels.append(level)
    return levels[:10]


def _thinking_info(item: dict[str, Any]) -> tuple[bool, bool, list[str]]:
    thinking = item.get("thinking")
    if isinstance(thinking, dict):
        levels = _level_list(thinking.get("levels"))
        return bool(thinking.get("supported")), bool(thinking.get("required")), levels
    effort = item.get("effort")
    if isinstance(effort, dict):
        levels = _level_list(effort.get("supported_levels"))
        return bool(levels), False, levels
    mode = item.get("thinking_mode")
    if isinstance(mode, bool):
        return mode, False, []
    if isinstance(mode, str):
        text = mode.strip()
        if text == "" or text in {"不支持", "否", "none", "None"}:
            return False, False, []
        return True, "默认" in text or "仅" in text, []
    return False, False, []


def _model_type(item: dict[str, Any]) -> str:
    for key in ("type", "model_type"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return "text"


def _display_name(model_id: str, item: dict[str, Any]) -> str:
    declared = item.get("name")
    if isinstance(declared, str) and declared.strip():
        return declared.strip()[:120]
    raw = model_id.split("/")[-1]
    released: str | None = None
    match = re.search(r"-(\d{4}-\d{2}-\d{2})$", raw)
    if match is not None:
        released = match.group(1)
        raw = raw[: match.start()]
    tokens: list[str] = []
    for part in (segment for segment in re.split(r"[-_]+", raw) if segment):
        lower = part.lower()
        family = _NAME_FAMILIES.get(lower)
        if family is not None:
            tokens.append(family)
            continue
        attached = re.fullmatch(r"([a-z]+)(\d.*)", lower)
        if attached is not None and attached.group(1) in _NAME_FAMILIES:
            tokens.append(_NAME_FAMILIES[attached.group(1)] + attached.group(2))
            continue
        version = re.fullmatch(r"v?(\d+(?:\.\d+)*[a-z]*)", lower)
        if version is not None:
            tokens.append(("V" if lower.startswith("v") else "") + version.group(1))
            continue
        if lower in _NAME_SUFFIXES:
            tokens.append(_NAME_SUFFIXES[lower])
            continue
        tokens.append(part[:1].upper() + part[1:])
    if not tokens:
        return model_id[:120]
    rendered = tokens[0]
    families = set(_NAME_FAMILIES.values())
    for token in tokens[1:]:
        if token not in families and re.fullmatch(r"V?\d+(?:\.\d+)*[a-z]*", token):
            rendered = f"{rendered}-{token}" if rendered in families else f"{rendered} {token}"
        else:
            rendered = f"{rendered} {token}"
    if released is not None:
        rendered = f"{rendered} ({released})"
    return rendered[:120]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:120] or "model"


def _modalities(item: dict[str, Any]) -> tuple[list[str], list[str]]:
    inputs = [
        str(value).lower() for value in item.get("input_modalities") or [] if isinstance(value, str)
    ]
    outputs = [
        str(value).lower()
        for value in item.get("output_modalities") or []
        if isinstance(value, str)
    ]
    model_type = _model_type(item)
    if not inputs:
        inputs = ["text", "image"] if model_type in {"multimodal", "vision"} else ["text"]
    if not outputs:
        outputs = ["text"]
    return sorted(set(inputs)), sorted(set(outputs))


def _category(model_type: str, thinking_supported: bool) -> str:
    if model_type in {"multimodal", "vision"}:
        return "multimodal"
    if model_type == "code":
        return "coding"
    if model_type == "embedding":
        return "embedding"
    if model_type == "reranker":
        return "reranker"
    if thinking_supported or model_type == "reasoning":
        return "reasoning"
    return "general"


def _description(
    provider_name: str,
    name: str,
    context_window: int,
    max_output: int | None,
    capabilities: list[str],
) -> str:
    facts: list[str] = []
    if context_window > 0:
        facts.append(f"{context_window // 1000}K 上下文")
    if max_output:
        facts.append(f"最大输出 {max_output // 1000}K")
    if "tools" in capabilities:
        facts.append("工具调用")
    if "vision" in capabilities:
        facts.append("多模态")
    if "reasoning" in capabilities:
        facts.append("可配置思考")
    tail = "，".join(facts) if facts else "OpenAI 兼容接口"
    return f"{provider_name} 提供的 {name}，{tail}。"


def _parse_entry(
    item: dict[str, Any],
    *,
    provider_id: str,
    provider_name: str,
    base_url: str,
    docs_url: str,
) -> InnerModel | None:
    model_id = str(item.get("id") or "").strip()
    if model_id == "":
        return None
    model_type = _model_type(item)
    if model_type in NON_CHAT_TYPES:
        return None
    context_window = _first_int(item, "context_window", "max_context", "context_length") or 0
    max_output = _first_int(item, "max_output_tokens", "max_output", "max_completion_tokens")
    thinking_supported, thinking_required, thinking_levels = _thinking_info(item)
    input_types, output_types = _modalities(item)
    capabilities = ["chat", "stream"]
    if item.get("tool_calling") is True:
        capabilities.append("tools")
    if "image" in input_types:
        capabilities.append("vision")
    if thinking_supported:
        capabilities.append("reasoning")
    name = _display_name(model_id, item)
    category = _category(model_type, thinking_supported)
    created = _as_int(item.get("created")) or 0
    is_new = created > int(datetime.now(UTC).timestamp()) - NEW_MODEL_WINDOW_SECONDS
    return InnerModel(
        id=uuid.uuid5(NAMESPACE, f"ai-power:market:{provider_id}:{model_id}"),
        slug=_slugify(f"{provider_id}-{model_id}"),
        name=name,
        provider_id=provider_id,
        provider_name=provider_name,
        model_id=model_id,
        description=_description(provider_name, name, context_window, max_output, capabilities),
        category=category,
        capabilities=capabilities,
        input_types=input_types,
        output_types=output_types,
        context_window=context_window,
        max_output=max_output,
        thinking_supported=thinking_supported,
        thinking_required=thinking_required,
        thinking_levels=thinking_levels,
        provider_base_url=base_url,
        docs_url=docs_url,
        featured=False,
        is_new=is_new,
        sort_order=100,
    )


def _enabled_providers() -> tuple[str, ...]:
    """``*`` loads every file; an empty setting disables the built-in catalog."""
    raw = get_settings().inner_models_providers.strip().lower()
    if raw == "*":
        return ("*",)
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _directory_signature(directory: Path) -> float:
    try:
        return max((path.stat().st_mtime for path in directory.glob("*.json")), default=0.0)
    except OSError:
        return 0.0


def load_inner_models(
    directory: str | None = None, providers: tuple[str, ...] | None = None
) -> list[InnerModel]:
    """Load the built-in catalog, cached until a file or the selection changes."""
    settings = get_settings()
    root = Path(directory or settings.inner_models_dir)
    enabled = providers if providers is not None else _enabled_providers()
    signature = _directory_signature(root)
    key = (str(root), enabled, signature)
    cached = _cache.get(key)
    if cached is not None:
        return list(cached)

    models: list[InnerModel] = []
    seen: set[tuple[str, str]] = set()
    if enabled == ():
        _cache.clear()
        _cache[key] = []
        return []
    if root.is_dir():
        for path in sorted(root.glob("*.json")):
            provider_id = path.stem.removesuffix("_models").lower()
            if "*" not in enabled and provider_id not in enabled:
                continue
            meta = PROVIDER_CATALOG.get(provider_id, {})
            provider_name = meta.get("name", provider_id.title())
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                logger.warning("Skipping unreadable inner model catalog %s: %s", path, exc)
                continue
            entries = payload.get("data") if isinstance(payload, dict) else payload
            if not isinstance(entries, list):
                logger.warning("Skipping inner model catalog %s: expected a list", path)
                continue
            for item in entries:
                if not isinstance(item, dict):
                    continue
                parsed = _parse_entry(
                    item,
                    provider_id=provider_id,
                    provider_name=provider_name,
                    base_url=meta.get("base_url", ""),
                    docs_url=meta.get("docs_url", ""),
                )
                if parsed is None or (parsed.provider_id, parsed.model_id) in seen:
                    continue
                seen.add((parsed.provider_id, parsed.model_id))
                models.append(parsed)

    models.sort(key=lambda model: (model.name.lower(), model.model_id))
    _cache.clear()
    _cache[key] = list(models)
    return models


def find_inner_model(slug: str) -> InnerModel | None:
    return next((model for model in load_inner_models() if model.slug == slug), None)


@dataclass(frozen=True, slots=True)
class ProviderSummary:
    provider_id: str
    name: str
    model_count: int
    base_url: str
    docs_url: str


def provider_catalog() -> list[ProviderSummary]:
    """Summarize providers that currently contribute built-in models."""
    models = load_inner_models()
    grouped: dict[str, list[InnerModel]] = {}
    for model in models:
        grouped.setdefault(model.provider_id, []).append(model)
    ordered: list[ProviderSummary] = []
    seen: set[str] = set()
    for provider_id, meta in PROVIDER_CATALOG.items():
        group = grouped.get(provider_id)
        if not group:
            continue
        seen.add(provider_id)
        ordered.append(
            ProviderSummary(
                provider_id=provider_id,
                name=group[0].provider_name,
                model_count=len(group),
                base_url=meta.get("base_url", ""),
                docs_url=meta.get("docs_url", ""),
            )
        )
    for provider_id, group in grouped.items():
        if provider_id in seen:
            continue
        ordered.append(
            ProviderSummary(
                provider_id=provider_id,
                name=group[0].provider_name,
                model_count=len(group),
                base_url=group[0].provider_base_url,
                docs_url=group[0].docs_url,
            )
        )
    ordered.sort(key=lambda item: (-item.model_count, item.name.lower()))
    return ordered


def filter_inner_models(
    models: list[InnerModel],
    *,
    search: str | None = None,
    category: str | None = None,
    capability: str | None = None,
    provider_id: str | None = None,
    input_type: str | None = None,
    output_type: str | None = None,
) -> list[InnerModel]:
    term = search.strip().lower() if search else ""
    result: list[InnerModel] = []
    for model in models:
        if term and term not in (
            f"{model.name} {model.provider_name} {model.model_id} {model.description}".lower()
        ):
            continue
        if category and model.category != category:
            continue
        if capability and capability not in model.capabilities:
            continue
        if provider_id and model.provider_id != provider_id:
            continue
        if input_type and input_type not in model.input_types:
            continue
        if output_type and output_type not in model.output_types:
            continue
        result.append(model)
    return result
