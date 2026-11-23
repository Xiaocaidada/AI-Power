from typing import Any

KNOWLEDGE_RETRIEVAL_CATALOG: list[dict[str, Any]] = [
    {
        "type": "start",
        "label": "查询输入",
        "description": "接收用户问题与知识库范围。",
        "icon": "Search",
        "config_fields": [],
    },
    {
        "type": "rewrite_query",
        "label": "查询改写",
        "description": "用 LLM 改写/扩展检索问题。",
        "icon": "Sparkles",
        "config_fields": [
            {"name": "provider_id", "label": "模型提供商", "kind": "provider", "required": True},
            {"name": "model", "label": "模型", "kind": "model", "required": True},
            {"name": "system_prompt", "label": "System Prompt", "kind": "textarea"},
            {
                "name": "prompt",
                "label": "改写 Prompt",
                "kind": "textarea",
                "required": True,
                "hint": "可用 {{query}} / {{input}}",
            },
        ],
    },
    {
        "type": "vector_search",
        "label": "向量检索",
        "description": "按 KB 的 Embedding 配置做向量召回。",
        "icon": "Boxes",
        "config_fields": [
            {"name": "top_k", "label": "Top-K", "kind": "number"},
        ],
    },
    {
        "type": "lexical_search",
        "label": "全文检索",
        "description": "pg_trgm 关键词召回。",
        "icon": "FileText",
        "config_fields": [
            {"name": "top_k", "label": "Top-K", "kind": "number"},
        ],
    },
    {
        "type": "hybrid_search",
        "label": "混合检索",
        "description": "向量 + 全文，RRF 融合。",
        "icon": "GitMerge",
        "config_fields": [
            {"name": "top_k", "label": "Top-K", "kind": "number"},
            {"name": "candidate_k", "label": "候选数", "kind": "number"},
        ],
    },
    {
        "type": "rerank",
        "label": "重排序",
        "description": "使用 KB 配置的 Reranker 重排候选。",
        "icon": "ListOrdered",
        "config_fields": [
            {"name": "top_k", "label": "Top-K", "kind": "number"},
        ],
    },
    {
        "type": "top_k",
        "label": "Top-K 截断",
        "description": "只保留前 K 条结果。",
        "icon": "Filter",
        "config_fields": [
            {"name": "top_k", "label": "Top-K", "kind": "number"},
        ],
    },
    {
        "type": "context",
        "label": "上下文组装",
        "description": "在字符预算内组装上下文。",
        "icon": "Layers",
        "config_fields": [
            {"name": "max_chars", "label": "最大字符", "kind": "number"},
        ],
    },
    {
        "type": "output",
        "label": "输出",
        "description": "返回片段、上下文与引用。",
        "icon": "Flag",
        "config_fields": [],
    },
]

RETRIEVAL_TEMPLATES: dict[str, dict[str, Any]] = {
    "hybrid": {
        "name": "混合检索 + 重排",
        "nodes": [
            ("start", "start", {}),
            ("hybrid", "hybrid_search", {"top_k": 20, "candidate_k": 30}),
            ("rerank", "rerank", {"top_k": 6}),
            ("context", "context", {"max_chars": 6000}),
            ("out", "output", {}),
        ],
    },
    "vector": {
        "name": "向量检索",
        "nodes": [
            ("start", "start", {}),
            ("vector", "vector_search", {"top_k": 8}),
            ("rerank", "rerank", {"top_k": 5}),
            ("out", "output", {}),
        ],
    },
}


def build_knowledge_retrieval_catalog() -> dict[str, Any]:
    templates = []
    for template in RETRIEVAL_TEMPLATES.values():
        nodes = []
        edges = []
        previous = None
        for index, (node_id, node_type, config) in enumerate(template["nodes"]):
            nodes.append(
                {
                    "id": node_id,
                    "type": node_type,
                    "config": config,
                    "ui": {"x": 80 + index * 180, "y": 120},
                }
            )
            if previous is not None:
                edges.append({"from": previous, "to": node_id})
            previous = node_id
        templates.append(
            {
                "name": template["name"],
                "description": "",
                "definition": {"nodes": nodes, "edges": edges},
            }
        )
    return {
        "kind": "knowledge_retrieval",
        "nodes": KNOWLEDGE_RETRIEVAL_CATALOG,
        "limits": {"max_nodes": 20, "linear": True},
        "variables": {"query": "用户问题", "kb_ids": "目标知识库"},
        "templates": templates,
    }
