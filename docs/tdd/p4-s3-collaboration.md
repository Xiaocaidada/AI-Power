# TDD Evidence — P4-S3: planner → worker → critic 协作

- **Date:** 2026-11-21
- **Scope:** 多 Agent 协作模式、计划/复核协议、并行 worker、全局步数预算、run/step 持久化、`/collaborations` 前端
- **Source:** [`docs/plan/p4-plan.md`](../plan/p4-plan.md) P4-S3（D5 协作模式）

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 新增协作测试 | `pytest tests/test_collaboration.py` | **4 passed** |
| 后端全量 | `pytest -q` | **296 passed, 3 skipped** |
| Lint/Format | `ruff check` / `ruff format --check` | 通过 |
| 前端单测 | `npm test` | 22 passed |
| 类型/构建 | `npm run typecheck` / `npm run build` | 通过 |
| E2E | `npm run test:e2e` | 1 passed（9.0s） |

## 交付

- **数据模型**：`collaboration_runs`（plan/rounds/final_output/tokens/cost）、`collaboration_steps`（planner/worker/critic 角色、输入输出摘要、耗时、错误码）；迁移 `e1f2a3b4c5d6`。
- **协作流程**（`app/services/collaboration.py`）：
  - planner 只接受 JSON 计划：2–`COLLABORATION_MAX_TASKS` 个子任务，`agent ∈ retrieval|math|general`，id 唯一。
  - worker 通过 `AgentRunner` 并行执行（`COLLABORATION_PARALLEL_LIMIT`，默认 3）；`general` 映射 supervisor，`retrieval`/`math` 使用专用子 Agent。
  - critic 返回 `accept`（必须含 `final_answer`）或 `revise`（必须含 `feedback`）；revise 时 worker 带着上一版输出与反馈重做，最多 `COLLABORATION_MAX_ROUNDS`（默认 2）轮。
  - 全局步数预算 `COLLABORATION_MAX_STEPS`；每次 LLM/Agent 步都消耗预算并检查配额；worker 超时 `COLLABORATION_TASK_TIMEOUT_SECONDS`。
  - 所有角色 token 与成本汇总到 run 与 step；SSE：`collaboration_start/planner_start/planner_end/worker_start/worker_end/critic_start/critic_end/collaboration_end`。
- **API**（workspace 隔离）：`POST /collaborations/runs`（SSE）、`GET /collaborations/runs/{id}`、`GET /collaborations/runs`。
- **前端** `/collaborations`：任务输入、模型/知识库选择、计划列表、planner/worker/critic 时间线（状态、耗时、输出摘要）、最终结果与错误。

## Test Specification（新增 4）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | planner 产出 2 任务、worker 并行、critic accept，run/step 持久化 | `test_collaboration_plans_workers_and_accepts` | PASS |
| 2 | critic revise 后 worker 重做，最多 2 轮并接受 | `test_collaboration_revises_once` | PASS |
| 3 | 非 JSON 计划 → `invalid_plan`，run failed | `test_collaboration_invalid_plan_fails` | PASS |
| 4 | 跨 workspace 读取/列表 404/空 | `test_collaboration_runs_are_workspace_scoped` | PASS |

## Known Gaps

- **依赖模型遵循 JSON 协议**：planner/critic 输出不合法即失败；测试使用脚本化 provider。
- **revise 会重跑全部 worker**：没有按任务精准重试；成本可能翻倍。
- **critic 无数值评分**：仅 accept/revise + 文本反馈。
- **协作成本只记 run/step**：未写 `usage_events`；用量页看不到。
- **同步 SSE 执行**：长协作占用请求连接；断连取消为 best-effort。
- **前端无运行历史列表 UI**：API 已提供分页列表。
- **worker 的 Agent 步数未按任务单独限制**：受全局预算与 `agent_max_steps` 双重约束，但没有逐任务上限。