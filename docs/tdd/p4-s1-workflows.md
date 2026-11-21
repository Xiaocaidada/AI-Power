# TDD Evidence — P4-S1: 工作流模型与执行引擎

- **Date:** 2026-11-21
- **Scope:** 工作流/版本/run/node run 持久化、DAG 校验、顺序执行引擎、SSE、REST API
- **Source:** [`docs/plan/p4-plan.md`](../plan/p4-plan.md) P4-S1（D2 版本化定义、D3 引擎、D4 节点白名单）

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 新增工作流测试 | `pytest tests/test_workflows.py` | **12 passed** |
| 后端全量 | `pytest -q` | **284 passed, 3 skipped** |
| Lint/Format | `ruff check` / `ruff format --check` | 通过 |
| 迁移 | `tests/test_migrations.py` | 通过（新增 4 张表） |

## 交付

- **数据模型**：`workflows`、`workflow_versions`（不可变定义）、`workflow_runs`、`workflow_node_runs`；迁移 `d0e1f2a3b4c5`。
- **定义与校验**（`app/services/workflow/schema.py`）：
  - `nodes[{id,type,config}]` + `edges[{from,to}]`；节点 id 唯一、类型白名单（`llm`、`kb_search`）。
  - 校验：配置 Pydantic、引用存在、无自环/重复边、入口唯一、单入单出（S1 线性）、全部可达、无环、节点数 ≤ `WORKFLOW_MAX_NODES`。
  - 非法定义统一 422 `invalid_workflow` + 错误列表。
- **执行引擎**（`app/services/workflow/runner.py`）：
  - 按拓扑顺序执行；`{{input}}` / `{{node_id}}` 模板渲染，未知变量 → `invalid_template`。
  - `llm` 节点复用 provider 流式输出并累计 usage/cost；`kb_search` 节点复用工具（workspace + kb 隔离）。
  - 节点超时 `WORKFLOW_NODE_TIMEOUT_SECONDS`，ProviderError 重试至 `WORKFLOW_NODE_ATTEMPTS`。
  - run/node 状态、尝试次数、耗时、输入/输出摘要（≤500 字符）入库。
  - SSE：`workflow_start` / `node_start` / `node_end` / `workflow_end`；失败节点停后续节点。
- **API**（`/workflows`，workspace 隔离）：
  - `GET/POST /workflows`、`GET /workflows/{id}`、`POST /workflows/{id}/versions`、`DELETE`（软删除）。
  - `POST /workflows/{id}/runs`（SSE）、`GET /workflows/runs/{run_id}`、`GET /workflows/{id}/runs?limit&before`。
  - 运行前校验 kb 归属并执行 workspace 配额检查。

## Test Specification（新增 12）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1–7 | 空图、重复 id、未知类型、环、多入口、悬空边、缺配置均被拒绝 | `test_invalid_workflow_definitions_are_rejected`（7 参数） | PASS |
| 8 | 两节点线性执行、SSE 顺序、usage 累计、run/node 持久化 | `test_workflow_runs_linear_nodes_and_persists_state` | PASS |
| 9 | ProviderError 重试后成功，attempts=2 | `test_workflow_retries_provider_failure_before_failing` | PASS |
| 10 | 节点失败标记 run failed 并保留错误码 | `test_workflow_node_failure_marks_run_failed` | PASS |
| 11 | `kb_search` 节点返回知识库内容；无 kb 返回 `no_knowledge_base` | `test_workflow_kb_search_node` | PASS |
| 12 | 跨 workspace 读写/运行一律 404 | `test_workflows_are_workspace_scoped` | PASS |

## Known Gaps

- **仅支持线性 DAG**：S1 强制单入单出，`condition`/`parallel`/`agent` 节点在 S2。
- **同步 SSE 执行**：run 绑定请求连接，长工作流占用连接；后续可转后台队列。
- **成本只记在 run**：未写 `usage_events`（无 message_id），用量页看不到工作流消耗。
- **无节点级配额**：只在 run 开始时检查一次。
- **取消为 best-effort**：断连时标记 run cancelled，节点记录可能来不及更新。
- **无前端**：S2 提供 `/workflows` 编辑与 run 时间线。
- **无工作流级 trace/审计**；run/node 表即 S1 的可观测载体。