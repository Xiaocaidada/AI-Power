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
        "type": "filter_text",
        "label": "文本过滤",
        "description": "按长度/正则/重复行过滤文本，可移除跨页页眉页脚。",
        "icon": "Filter",
        "config_fields": [
            {"name": "min_line_chars", "label": "最短行长度", "kind": "number"},
            {
                "name": "drop_patterns",
                "label": "丢弃行正则（每行一个）",
                "kind": "textarea",
                "hint": "例如：^第 \\d+ 页$",
            },
            {
                "name": "dedupe_lines",
                "label": "页面内去重行",
                "kind": "select",
                "options": ["true", "false"],
            },
            {
                "name": "normalize_width",
                "label": "全角转半角",
                "kind": "select",
                "options": ["true", "false"],
            },
            {
                "name": "drop_boilerplate",
                "label": "移除跨页重复行",
                "kind": "select",
                "options": ["false", "true"],
            },
        ],
    },
    {
        "type": "chunk_text",
        "label": "文本切片",
        "description": "固定、Markdown、递归、自定义、父子或语义切片。",
        "icon": "Scissors",
        "config_fields": [
            {
                "name": "strategy",
                "label": "切片策略",
                "kind": "select",
                "required": True,
                "options": [
                    "fixed",
                    "markdown",
                    "recursive",
                    "custom",
                    "parent_child",
                    "semantic",
                ],
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
            {
                "name": "separators",
                "label": "自定义分隔符",
                "kind": "text",
                "hint": "custom 策略使用，| 分隔，支持 \\n",
            },
            {"name": "parent_size", "label": "父块大小", "kind": "number"},
            {"name": "child_size", "label": "子块大小", "kind": "number"},
            {
                "name": "semantic_threshold",
                "label": "语义断点阈值",
                "kind": "number",
                "hint": "0–1，越低越少断点",
            },
        ],
    },
    {
        "type": "enrich_metadata",
        "label": "元数据增强",
        "description": "把标题、文件夹、标签、来源与文档名写入每个切片元数据。",
        "icon": "Tags",
        "config_fields": [
            {
                "name": "include_filename",
                "label": "包含文件名",
                "kind": "select",
                "options": ["true", "false"],
            },
            {
                "name": "include_folder",
                "label": "包含文件夹",
                "kind": "select",
                "options": ["true", "false"],
            },
            {
                "name": "include_tags",
                "label": "包含标签",
                "kind": "select",
                "options": ["true", "false"],
            },
            {
                "name": "include_source",
                "label": "包含来源 URL",
                "kind": "select",
                "options": ["true", "false"],
            },
            {
                "name": "prepend_title",
                "label": "标题写入正文",
                "kind": "select",
                "options": ["false", "true"],
            },
        ],
    },
    {
        "type": "extract_keywords",
        "label": "关键词提取",
        "description": "按词频提取切片关键词，可写入正文前缀以增强检索。",
        "icon": "Tags",
        "config_fields": [
            {"name": "count", "label": "关键词数量", "kind": "number"},
            {
                "name": "prepend",
                "label": "关键词写入正文",
                "kind": "select",
                "options": ["false", "true"],
            },
        ],
    },
    {
        "type": "summarize_chunks",
        "label": "切片摘要",
        "description": "为每个切片生成抽取式摘要并写入元数据。",
        "icon": "FileText",
        "config_fields": [
            {"name": "max_chars", "label": "摘要最大长度", "kind": "number"},
            {
                "name": "mode",
                "label": "摘要方式",
                "kind": "select",
                "options": ["extractive", "first_sentence"],
            },
            {
                "name": "prepend",
                "label": "摘要写入正文",
                "kind": "select",
                "options": ["false", "true"],
            },
        ],
    },
    {
        "type": "dedupe_chunks",
        "label": "切片去重",
        "description": "移除完全重复与高相似度切片，并重新编号。",
        "icon": "Copy",
        "config_fields": [
            {"name": "threshold", "label": "相似度阈值", "kind": "number"},
            {"name": "min_chars", "label": "参与去重的最短长度", "kind": "number"},
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
    "enhanced": {
        "name": "增强文档处理",
        "nodes": [
            ("start", "start", {}),
            ("parse", "parse_document", {}),
            ("clean", "clean_text", {}),
            ("filter", "filter_text", {"drop_boilerplate": True}),
            (
                "chunk",
                "chunk_text",
                {"strategy": "recursive", "chunk_size": 800, "chunk_overlap": 100},
            ),
            ("meta", "enrich_metadata", {"prepend_title": True}),
            ("keywords", "extract_keywords", {"count": 8}),
            ("summary", "summarize_chunks", {"max_chars": 200}),
            ("dedupe", "dedupe_chunks", {}),
            ("embed", "embed_chunks", {}),
            ("index", "index_knowledge", {}),
            ("out", "output", {}),
        ],
    },
    "parent_child": {
        "name": "父子切片处理",
        "nodes": [
            ("start", "start", {}),
            ("parse", "parse_document", {}),
            ("clean", "clean_text", {}),
            (
                "chunk",
                "chunk_text",
                {
                    "strategy": "parent_child",
                    "parent_size": 2000,
                    "child_size": 400,
                },
            ),
            ("meta", "enrich_metadata", {}),
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