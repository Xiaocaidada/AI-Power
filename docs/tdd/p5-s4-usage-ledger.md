# P5-S4 统一用量账本 — TDD 证据

- **Date:** 2026-11-22
- **Scope:** `usage_events` 覆盖聊天/工作流/协作；按来源与 API Key 对账；预算、`/metrics`、用量页同口径。
- **ADR:** [`ADR-0022`](../adr/0022-unified-usage-ledger.md)

## 1. RED

先写 `tests/test_usage_ledger.py`，在实现前运行：

```text
.venv/Scripts/python.exe -m pytest tests/test_usage_ledger.py -q
8 failed, 3 passed
TypeError: 'workflow_node_run_id' is an invalid keyword argument for UsageEvent
```

失败覆盖：

- `source` / `api_key_id` / node / step 列不存在；
- `group_by=source` 与 `/usage/by-key` 不存在；
- 工作流/协作不写账本；
- 聊天事件没有 API Key 归属。

## 2. GREEN

实现后：

```text
.venv/Scripts/python.exe -m pytest tests/test_usage_ledger.py tests/test_migrations.py -q
12 passed
```

新增用例（`tests/test_usage_ledger.py`，10 条）：

| 用例 | 覆盖 |
|---|---|
| `test_usage_groups_by_source_and_filters_by_api_key` | 三类来源汇总、`api_key_id` 过滤、来源成本 |
| `test_usage_by_key_attributes_requests_and_is_workspace_scoped` | 按 Key 对账、JWT 未归属桶、跨 workspace 隔离 |
| `test_chat_usage_event_records_api_key` | 聊天 `source=chat` + `api_key_id` |
| `test_chat_finalize_is_idempotent` | 重复 finalize 不重复写 |
| `test_workflow_writes_one_ledger_event_per_llm_node` | 每节点一条、node id 唯一、run 成本 = 账本成本、`/metrics` `source="workflow"` |
| `test_workflow_usage_event_records_api_key` | `workflow:run` Key 归属 |
| `test_workflow_cost_enters_workspace_budget` | 工作流成本触发 `budget.exceeded` |
| `test_collaboration_writes_one_ledger_event_per_step` | planner + 2 workers + critic 四条、step id 唯一、run 成本一致 |
| `test_usage_events_keep_null_message_for_runs` | 非聊天来源 `message_id=NULL` |
| `test_chat_conversation_still_links_usage_event` | 聊天仍保留 message/conversation 关联 |

迁移用例（`tests/test_migrations.py`）新增：

- `usage_events` 新列与 `message_id` 可空；
- 复合索引存在；
- 历史消息回填 `source='chat'`。

回归：

```text
.venv/Scripts/python.exe -m pytest -q
361 collected, 357 passed, 4 skipped
```

```text
.venv/Scripts/python.exe -m ruff check app tests alembic
All checks passed!
```

前端：

```text
cd web && npm test -- --run
22 passed
cd web && npm run build
built in 3.70s
```

## 3. 行为说明

- 迁移：`d6e7f8a9b0c1_p5_usage_ledger.py`，`message_id` 可空，新增 `source` / `api_key_id` / `workflow_node_run_id` / `collaboration_step_id` 与索引；历史行 `source='chat'`。
- 写入：统一走 `app/services/usage_ledger.py`；以 message / node run / step 做幂等，价格快照在写入时读取。
- 聊天：`_finalize` 透传 `AuthContext.api_key_id`。
- 工作流：每个 LLM/agent 节点成功后写一条；终态后检查 workspace 预算。
- 协作：每个 planner/worker/critic 步骤写一条；worker 失败但有 usage 时也写；终态后检查预算。
- 指标：`ai_power_tokens_total` / `ai_power_cost_usd_total` 增加 `source` 标签。
- API：`group_by=source`、`source` / `api_key_id` 过滤、`GET /usage/by-key`。
- 前端：用量页“按来源”分组与“按 API Key 对账”表。

## 4. 真实部署验证（2026-11-22）

```text
docker compose exec api alembic upgrade head
c5d6e7f8a9b0 -> d6e7f8a9b0c1 (head)
docker compose up -d --build api worker web
/readyz -> {"status":"ok","checks":{"database":"ok","redis":"ok"}}
worker -> 7 functions
```

通过真实 API（`http://192.168.29.100:8002`）注册临时用户，创建带 `chat:write` + `workflow:run` 的 Key，执行一次聊天与一个单节点工作流：

```json
{
  "sources": {"chat": 1, "workflow": 1},
  "key_requests": 2,
  "unattributed_requests": 0
}
```

- `group_by=source` 同时出现 `chat` 与 `workflow`；
- `/usage/by-key` 将两次调用归到同一 Key，未归属桶为 0；
- 本地 `local-qwen` 未配置价格，因此真实运行成本为 0；价格非零时的金额一致性由 `test_workflow_writes_one_ledger_event_per_llm_node` / `test_collaboration_writes_one_ledger_event_per_step` 用 `fake` 目录价覆盖。

## 5. 已知边界

- provider 在返回 usage 前中途失败时无法计量该次调用。
- 评测运行（answer + judge）仍使用 `eval_runs` / `eval_run_items` 的成本字段，未进入统一账本。
- `/usage/by-key` 对已删除 Key（未来若支持硬删除）会退化为未归属桶；当前只有吊销，名称仍可读。
- 工作流节点重试时，失败尝试若在返回 usage 前中断，其 token 无法计量；成功节点按唯一 `workflow_node_run_id` 只记一条。