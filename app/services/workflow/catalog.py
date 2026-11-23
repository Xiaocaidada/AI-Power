from typing import Any

NODE_CATALOG: list[dict[str, Any]] = [
    {
        "type": "start",
        "label": "开始",
        "description": "工作流入口，接收用户输入。",
        "icon": "Play",
        "config_fields": [],
    },
    {
        "type": "llm",
        "label": "LLM",
        "description": "一次确定性的模型调用。",
        "icon": "Sparkles",
        "config_fields": [
            {"name": "provider_id", "label": "模型提供商", "kind": "provider", "required": True},
            {"name": "model", "label": "模型", "kind": "model", "required": True},
            {"name": "system_prompt", "label": "System Prompt", "kind": "textarea"},
            {
                "name": "prompt",
                "label": "Prompt",
                "kind": "textarea",
                "required": True,
                "hint": "支持 {{input}} 与上游节点 ID 变量",
            },
        ],
    },
    {
        "type": "agent",
        "label": "自主 Agent",
        "description": "自主规划、调用工具并完成子任务。",
        "icon": "Bot",
        "config_fields": [
            {"name": "agent_id", "label": "绑定 Agent", "kind": "agent"},
            {"name": "provider_id", "label": "模型提供商", "kind": "provider"},
            {"name": "model", "label": "模型", "kind": "model"},
            {"name": "task", "label": "任务目标", "kind": "textarea", "required": True},
            {"name": "kb_ids", "label": "知识库", "kind": "kb_multi"},
            {"name": "tools", "label": "额外工具", "kind": "json"},
            {"name": "max_steps", "label": "最大步数", "kind": "number"},
        ],
    },
    {
        "type": "kb_search",
        "label": "知识库检索",
        "description": "检索关联知识库并返回带编号的材料。",
        "icon": "BookOpen",
        "config_fields": [
            {"name": "query", "label": "检索问题", "kind": "text", "required": True},
            {"name": "kb_ids", "label": "知识库", "kind": "kb_multi"},
        ],
    },
    {
        "type": "tool",
        "label": "工具 / 插件",
        "description": "调用内置工具或已配置插件。",
        "icon": "Wrench",
        "config_fields": [
            {"name": "tool", "label": "工具名称", "kind": "text", "required": True},
            {"name": "arguments", "label": "参数 JSON", "kind": "json"},
        ],
    },
    {
        "type": "condition",
        "label": "条件判断",
        "description": "根据表达式选择 true/false 分支。",
        "icon": "GitBranch",
        "config_fields": [
            {"name": "left", "label": "左值", "kind": "text", "required": True},
            {
                "name": "operator",
                "label": "运算符",
                "kind": "select",
                "required": True,
                "options": [
                    "equals",
                    "not_equals",
                    "contains",
                    "not_contains",
                    "not_empty",
                    "is_empty",
                ],
            },
            {"name": "right", "label": "右值", "kind": "text"},
        ],
    },
    {
        "type": "parallel",
        "label": "并行",
        "description": "并行执行多个分支。",
        "icon": "GitFork",
        "config_fields": [],
    },
    {
        "type": "join",
        "label": "合并",
        "description": "等待多个分支并合并输出。",
        "icon": "GitMerge",
        "config_fields": [],
    },
    {
        "type": "output",
        "label": "输出",
        "description": "工作流最终输出。",
        "icon": "Flag",
        "config_fields": [],
    },
]

NODE_BY_TYPE = {item["type"]: item for item in NODE_CATALOG}


def build_node_catalog() -> dict[str, Any]:
    return {
        "nodes": NODE_CATALOG,
        "limits": {"max_nodes": 30, "max_kbs": 10},
        "variables": {
            "input": "用户输入",
            "node_id": "引用上游节点输出",
        },
    }


def builder_manifest() -> str:
    lines = ["Available node types:"]
    for item in NODE_CATALOG:
        fields = ", ".join(
            f"{field['name']}{'*' if field.get('required') else ''}"
            for field in item["config_fields"]
        )
        lines.append(f"- {item['type']}: {item['description']} fields: {fields or '(none)'}")
    lines.append(
        "Rules: nodes[].ui is optional {x,y}; condition nodes need exactly one "
        "true and one false edge; parallel needs >=2 outgoing edges; join needs "
        ">=2 incoming edges; start cannot have incoming; output cannot have "
        "outgoing; exactly one entry node; acyclic graph."
    )
    return "\n".join(lines)