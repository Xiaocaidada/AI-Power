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
    {
        "type": "review",
        "label": "人工审核",
        "description": "暂停运行，等待工作区成员批准或驳回后继续。",
        "icon": "UserCheck",
        "config_fields": [
            {
                "name": "prompt",
                "label": "审核说明",
                "kind": "textarea",
                "required": True,
                "hint": "支持 {{input}} 与上游节点 ID 变量",
            },
            {
                "name": "timeout_seconds",
                "label": "超时秒数",
                "kind": "number",
                "hint": "留空使用平台默认值",
            },
        ],
    },
    {
        "type": "loop",
        "label": "循环",
        "description": "按列表或次数重复执行，可选逐次调用模型与提前结束条件。",
        "icon": "Repeat",
        "config_fields": [
            {
                "name": "mode",
                "label": "模式",
                "kind": "select",
                "required": True,
                "options": ["foreach", "repeat"],
            },
            {
                "name": "items",
                "label": "列表（每行一项或 JSON 数组）",
                "kind": "textarea",
                "hint": "foreach 模式必填，支持模板变量",
            },
            {"name": "times", "label": "重复次数", "kind": "number"},
            {"name": "max_iterations", "label": "最大迭代", "kind": "number"},
            {"name": "provider_id", "label": "模型提供商", "kind": "provider"},
            {"name": "model", "label": "模型", "kind": "model"},
            {"name": "system_prompt", "label": "System Prompt", "kind": "textarea"},
            {
                "name": "prompt",
                "label": "单次 Prompt",
                "kind": "textarea",
                "hint": "可用 {{item}} / {{index}} / {{iteration}}",
            },
            {
                "name": "until_operator",
                "label": "提前结束条件",
                "kind": "select",
                "options": [
                    "none",
                    "equals",
                    "not_equals",
                    "contains",
                    "not_contains",
                    "not_empty",
                    "is_empty",
                ],
            },
            {"name": "until_right", "label": "条件右值", "kind": "text"},
            {"name": "separator", "label": "结果分隔符", "kind": "text"},
        ],
    },
    {
        "type": "http",
        "label": "HTTP 请求",
        "description": "调用外部 HTTP API，带 SSRF 防护、超时与响应截断。",
        "icon": "Globe",
        "config_fields": [
            {
                "name": "method",
                "label": "方法",
                "kind": "select",
                "required": True,
                "options": ["GET", "POST"],
            },
            {
                "name": "url",
                "label": "URL",
                "kind": "text",
                "required": True,
                "hint": "支持模板变量；非 dev 环境必须 HTTPS",
            },
            {"name": "headers", "label": "请求头 JSON", "kind": "json"},
            {"name": "body", "label": "请求体", "kind": "textarea"},
            {"name": "timeout_seconds", "label": "超时秒数", "kind": "number"},
        ],
    },
    {
        "type": "mcp",
        "label": "MCP 工具",
        "description": "调用管理员配置的 MCP 服务器工具。",
        "icon": "Plug",
        "config_fields": [
            {"name": "server_id", "label": "MCP 服务器", "kind": "mcp_server", "required": True},
            {"name": "tool", "label": "工具名称", "kind": "text", "required": True},
            {"name": "arguments", "label": "参数 JSON", "kind": "json"},
            {"name": "timeout_seconds", "label": "超时秒数", "kind": "number"},
        ],
    },
    {
        "type": "mcp_resource",
        "label": "MCP 资源",
        "description": "读取 MCP 服务器暴露的资源内容。",
        "icon": "FileText",
        "config_fields": [
            {"name": "server_id", "label": "MCP 服务器", "kind": "mcp_server", "required": True},
            {"name": "uri", "label": "资源 URI", "kind": "text", "required": True},
            {"name": "timeout_seconds", "label": "超时秒数", "kind": "number"},
        ],
    },
    {
        "type": "mcp_prompt",
        "label": "MCP 提示词",
        "description": "获取 MCP 服务器上的提示词模板并展开。",
        "icon": "MessageSquare",
        "config_fields": [
            {"name": "server_id", "label": "MCP 服务器", "kind": "mcp_server", "required": True},
            {"name": "name", "label": "提示词名称", "kind": "text", "required": True},
            {"name": "arguments", "label": "参数 JSON", "kind": "json"},
            {"name": "timeout_seconds", "label": "超时秒数", "kind": "number"},
        ],
    },
    {
        "type": "memory_read",
        "label": "读取记忆",
        "description": "按查询读取用户或工作区的长期记忆。",
        "icon": "Brain",
        "config_fields": [
            {"name": "query", "label": "检索问题", "kind": "text"},
            {"name": "limit", "label": "条数", "kind": "number"},
            {
                "name": "scope",
                "label": "范围",
                "kind": "select",
                "options": ["user", "workspace"],
            },
        ],
    },
    {
        "type": "code",
        "label": "代码 / 表达式",
        "description": "安全沙箱表达式：字符串、JSON 与集合转换，不执行任意 Python。",
        "icon": "Code",
        "config_fields": [
            {
                "name": "code",
                "label": "表达式",
                "kind": "textarea",
                "required": True,
                "hint": "变量：input、outputs、json；支持安全内置函数与字符串方法",
            },
            {"name": "max_output_chars", "label": "最大输出字符", "kind": "number"},
        ],
    },
    {
        "type": "database",
        "label": "数据库查询",
        "description": "在管理员配置的只读 PostgreSQL 连接上执行 SELECT / WITH。",
        "icon": "Database",
        "config_fields": [
            {
                "name": "connection_id",
                "label": "数据库连接",
                "kind": "db_connection",
                "required": True,
            },
            {
                "name": "query",
                "label": "SQL（SELECT / WITH）",
                "kind": "textarea",
                "required": True,
                "hint": "使用 :name 绑定参数；禁止多语句与写操作",
            },
            {"name": "params", "label": "参数 JSON", "kind": "json"},
            {"name": "max_rows", "label": "最大行数", "kind": "number"},
            {"name": "timeout_seconds", "label": "超时秒数", "kind": "number"},
        ],
    },
    {
        "type": "memory_write",
        "label": "写入记忆",
        "description": "把本次运行的关键信息保存为长期记忆。",
        "icon": "Save",
        "config_fields": [
            {"name": "title", "label": "标题", "kind": "text"},
            {"name": "content", "label": "内容", "kind": "textarea", "required": True},
            {
                "name": "scope",
                "label": "范围",
                "kind": "select",
                "options": ["user", "workspace"],
            },
            {
                "name": "kind",
                "label": "类型",
                "kind": "select",
                "options": ["fact", "preference", "summary"],
            },
        ],
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
        "outgoing; exactly one entry node; acyclic graph. The review node blocks "
        "the run for human approval. The loop node repeats inline (foreach/repeat) "
        "with optional per-iteration model call and until condition; it is not a "
        "graph cycle. http/mcp nodes must use resources available to the "
        "workspace; never invent URLs, MCP servers or credentials. The code node "
        "runs a restricted expression (no imports/attributes/loops); the database "
        "node is SELECT/WITH-only against an admin-configured connection."
    )
    return "\n".join(lines)