# 工作流 API 参考

工作流是 workspace 级的 DAG 定义：不可变版本 + 每次运行持久化 node 状态。所有接口需要 JWT；跨 workspace 一律 404。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/workflows` | 列表（含各版本定义） |
| POST | `/workflows` | 创建并发布 v1 |
| GET | `/workflows/{id}` | 详情 |
| POST | `/workflows/{id}/versions` | 发布新版本（不可变） |
| DELETE | `/workflows/{id}` | 软删除 |
| POST | `/workflows/{id}/runs` | 运行（SSE） |
| GET | `/workflows/runs/{run_id}` | run + node 状态 |
| GET | `/workflows/{id}/runs?limit&before` | 运行历史 |

运行请求：

```json
{"input": "用户输入", "version": null, "kb_id": null}
```

`version` 缺省使用最新版本；`kb_id` 供 `kb_search` 节点使用，会校验归属。

## 定义格式

```json
{
  "nodes": [
    {"id": "draft", "type": "llm", "config": {
      "provider_id": "local-qwen", "model": "qwen2.5-7b-instruct",
      "prompt": "Draft an answer for: {{input}}",
      "system_prompt": null
    }},
    {"id": "check", "type": "condition", "config": {
      "left": "{{draft}}", "operator": "not_empty", "right": ""
    }},
    {"id": "final", "type": "llm", "config": {
      "provider_id": "local-qwen", "model": "qwen2.5-7b-instruct",
      "prompt": "Improve: {{draft}}"
    }},
    {"id": "fallback", "type": "llm", "config": {
      "provider_id": "local-qwen", "model": "qwen2.5-7b-instruct",
      "prompt": "Answer directly: {{input}}"
    }}
  ],
  "edges": [
    {"from": "draft", "to": "check"},
    {"from": "check", "to": "final", "when": "true"},
    {"from": "check", "to": "fallback", "when": "false"}
  ]
}
```

### 节点与配置

| type | config | 说明 |
|---|---|---|
| `llm` | `provider_id`, `model`, `prompt`, `system_prompt?` | 调用模型；模板变量可用 |
| `kb_search` | `query` | 检索运行绑定的 `kb_id` |
| `tool` | `tool`, `arguments: {str: str}` | 调用注册工具（如 calculator） |
| `agent` | `provider_id`, `model`, `task` | 运行 supervisor + 子 Agent |
| `condition` | `left`, `operator`, `right` | `equals/not_equals/contains/not_contains/not_empty/is_empty` |
| `parallel` | `{}` | 至少两条出边，并发执行 |
| `join` | `{}` | 至少两条入边，等待活跃分支完成后拼接 |

### 校验规则

- 节点 id 唯一（`[A-Za-z_][A-Za-z0-9_]{0,49}`），最多 `WORKFLOW_MAX_NODES`（默认 20）。
- 恰好一个入口；全部可达；无环；条件节点恰好一条 `when=true` 和一条 `when=false`；非条件节点不能带 `when`；parallel ≥2 出边、join ≥2 入边。
- 其他节点最多一条出边。

### 模板与执行

- 变量：`{{input}}` 与 `{{node_id}}`（已完成节点的输出）。
- 条件分支只执行一侧；另一侧标记 `skipped`，跳过会向后传播，join 不被跳过的分支阻塞。
- 并发由 `WORKFLOW_PARALLEL_LIMIT`（默认 3）限制。
- 节点超时 `WORKFLOW_NODE_TIMEOUT_SECONDS`（默认 120），ProviderError 重试至 `WORKFLOW_NODE_ATTEMPTS`（默认 2）。
- 每个 `llm` 节点前检查 workspace 配额；run 统计 token 与成本（不写 `usage_events`）。

## SSE 事件

```
workflow_start {run_id, workflow_id, version}
node_start {run_id, node_id, node_type}
node_end {run_id, node_id, status, attempts, duration_ms, output?, error_code?}
workflow_end {run_id, status, total_ms, prompt_tokens, completion_tokens, cost, output?, error_code?}
```

`status` 可为 `completed` / `failed` / `skipped`。`error_code` 示例：`invalid_workflow`、`invalid_template`、`node_timeout`、`no_knowledge_base`、`quota_exceeded`、`collaboration_step_limit`。

## Python 示例

见 [`scripts/workflow_example.py`](../../scripts/workflow_example.py)（读取环境变量，不打印凭据）：

```bash
export AI_POWER_BASE_URL=http://192.168.29.100:8080/api
export AI_POWER_EMAIL=demo@example.com
export AI_POWER_PASSWORD='...'
python scripts/workflow_example.py --provider local-qwen --model qwen2.5-7b-instruct
```

脚本会创建（或复用同名）工作流、发起一次运行并打印 `workflow_end` 结果。