from typing import Any

KNOWLEDGE_PROCESS_CATALOG: list[dict[str, Any]] = [
    {
        "type": "start",
        "label": "文档输入",
        "description": "接收本次运行的文档，作为处理流程起点。",
        "icon": "FileInput",
        "config_fields": [],
    },
    {
        "type": "parse_document",
        "label": "文档解析",
        "description": "按文件类型提取文本与页码。",
        "icon": "FileText",
        "config_fields": [
            {
                "name": "keep_blank_pages",
                "label": "保留空白页",
                "kind": "select",
                "options": ["false", "true"],
            },
        ],
    },
    {
        "type": "clean_text",
        "label": "文本清洗",
        "description": "规范化空白、移除 URL 与控制字符。",
        "icon": "Eraser",
        "config_fields": [
            {
                "name": "collapse_whitespace",
                "label": "压缩空白",
                "kind": "select",
                "options": ["true", "false"],
            },
            {
                "name": "strip_urls",
                "label": "移除 URL",
                "kind": "select",
                "options": ["false", "true"],
            },
            {
                "name": "strip_control",
                "label": "移除控制字符",
                "kind": "select",
                "options": ["true", "false"],
            },
        ],
    },
    {
        "type": "chunk_text",
        "label": "文本切片",
        "description": "固定、Markdown 或递归切片，支持标题上下文与最小长度。",
        "icon": "Scissors",
        "config_fields": [
            {
                "name": "strategy",
                "label": "切片策略",
                "kind": "select",
                "required": True,
                "options": ["fixed", "markdown", "recursive"],
            },
            {"name": "chunk_size", "label": "Chunk Size", "kind": "number"},
            {"name": "chunk_overlap", "label": "Chunk Overlap", "kind": "number"},
            {"name": "min_chars", "label": "最小切片长度", "kind": "number"},
            {
                "name": "keep_heading",
                "label": "保留标题上下文",
                "kind": "select",
                "options": ["true", "false"],
            },
        ],
    },
    {
        "type": "embed_chunks",
        "label": "向量化",
        "description": "使用知识库配置的 Embedding 模型生成向量。",
        "icon": "Boxes",
        "config_fields": [
            {"name": "batch_size", "label": "批大小", "kind": "number"},
        ],
    },
    {
        "type": "index_knowledge",
        "label": "暂存索引",
        "description": "把切片与向量写入运行暂存区，确认后再应用到知识库。",
        "icon": "Database",
        "config_fields": [
            {
                "name": "require_embeddings",
                "label": "要求全部向量化",
                "kind": "select",
                "options": ["true", "false"],
            },
        ],
    },
    {
        "type": "output",
        "label": "输出",
        "description": "汇总本次处理结果。",
        "icon": "Flag",
        "config_fields": [],
    },
]

KNOWLEDGE_NODE_BY_TYPE = {item["type"]: item for item in KNOWLEDGE_PROCESS_CATALOG}


def build_knowledge_process_catalog() -> dict[str, Any]:
    return {
        "kind": "knowledge_process",
        "nodes": KNOWLEDGE_PROCESS_CATALOG,
        "limits": {"max_nodes": 30, "linear": True},
        "variables": {"document": "本次处理的文档", "chunks": "切片结果"},
    }


def knowledge_builder_manifest() -> str:
    lines = ["Knowledge processing nodes (linear pipeline):"]
    for item in KNOWLEDGE_PROCESS_CATALOG:
        fields = ", ".join(
            f"{field['name']}{'*' if field.get('required') else ''}"
            for field in item["config_fields"]
        )
        lines.append(f"- {item['type']}: {item['description']} fields: {fields or '(none)'}")
    lines.append(
        "Rules: exactly one start and one output; every other node has exactly "
        "one incoming and one outgoing edge; no branches, conditions or cycles; "
        "index_knowledge requires embed_chunks upstream when require_embeddings=true."
    )
    return "\n".join(lines)


KNOWLEDGE_PROCESS_TEMPLATES: dict[str, dict[str, Any]] = {
    "general": {
        "name": "普通文档处理",
        "nodes": [
            ("start", "start", {}),
            ("parse", "parse_document", {}),
            ("clean", "clean_text", {}),
            (
                "chunk",
                "chunk_text",
                {"strategy": "fixed", "chunk_size": 1000, "chunk_overlap": 150},
            ),
            ("embed", "embed_chunks", {}),
            ("index", "index_knowledge", {}),
            ("out", "output", {}),
        ],
    },
    "technical": {
        "name": "技术文档处理",
        "nodes": [
            ("start", "start", {}),
            ("parse", "parse_document", {}),
            ("clean", "clean_text", {}),
            (
                "chunk",
                "chunk_text",
                {
                    "strategy": "markdown",
                    "chunk_size": 800,
                    "chunk_overlap": 120,
                    "keep_heading": True,
                },
            ),
            ("embed", "embed_chunks", {}),
            ("index", "index_knowledge", {}),
            ("out", "output", {}),
        ],
    },
    "markdown": {
        "name": "Markdown 文档处理",
        "nodes": [
            ("start", "start", {}),
            ("parse", "parse_document", {}),
            ("clean", "clean_text", {"strip_urls": False}),
            (
                "chunk",
                "chunk_text",
                {"strategy": "markdown", "chunk_size": 900, "chunk_overlap": 100},
            ),
            ("embed", "embed_chunks", {}),
            ("index", "index_knowledge", {}),
            ("out", "output", {}),
        ],
    },
}


def build_template(name: str) -> dict[str, Any] | None:
    template = KNOWLEDGE_PROCESS_TEMPLATES.get(name)
    if template is None:
        return None
    nodes = []
    edges = []
    previous = None
    for index, (node_id, node_type, config) in enumerate(template["nodes"]):
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "config": config,
                "ui": {"x": 80 + index * 190, "y": 120},
            }
        )
        if previous is not None:
            edges.append({"from": previous, "to": node_id})
        previous = node_id
    return {
        "name": template["name"],
        "description": "",
        "definition": {"nodes": nodes, "edges": edges},
    }