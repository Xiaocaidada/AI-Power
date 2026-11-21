# TDD Evidence — P4-S2: 节点类型与运行可视化

- **Date:** 2026-11-21
- **Scope:** condition/parallel/join/tool/agent 节点、分支跳过与合并、并发上限、`/workflows` 前端
- **Source:** [`docs/plan/p4-plan.md`](../plan/p4-plan.md) P4-S2（D3 执行语义、D4 节点白名单、D6 前端）

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 工作流测试 | `pytest tests/test_workflows.py` | **20 passed** |
| 后端全量 | `pytest -q` | **292 passed, 3 skipped** |
| Lint/Format | `ruff check` / `ruff format --check` | 通过 |
| 前端单测 | `npm test` | 22 passed |
| 类型/构建 | `npm run typecheck` / `npm run build` | 通过 |
| E2E | `npm run test:e2e` | 1 passed（8.3s） |

## 交付

- **节点类型**：`llm`、`kb_search`、`tool`、`agent`、`condition`、`parallel`、`join`（配置均有 Pydantic 校验）。
- **定义校验**：
  - condition 恰好一条 `when=true` 和一条 `when=false` 边；非 condition 节点不允许 `when`。
  - parallel 至少两条出边；join 至少两条入边；其余节点最多一条出边。
  - 单入口、全部可达、无环、节点数上限（原有）。
- **执行器**（`app/services/workflow/runner.py`）：
  - 事件驱动调度：节点在所有入边被决定后执行；条件分支只走一侧，另一侧标记 `skipped` 并向后传播。
  - `parallel` 的出边并发执行，`asyncio.Semaphore(WORKFLOW_PARALLEL_LIMIT)` 限制并发（默认 3）。
  - `join` 等待所有活跃入边完成后按边顺序拼接输出；被跳过的分支不阻塞。
  - `tool` 复用工具注册表；`agent` 复用 P3 `AgentRunner`（supervisor + 子 Agent）；LLM/Agent 计入 run token 与成本。
  - 每个 `llm` 节点执行前检查配额；Agent 内部逐步检查。
  - SSE：`node_end` 增加 `skipped` 状态、`attempts`、`output` 摘要；`workflow_end` 返回最终输出。
- **前端** `/workflows`：工作流列表、创建（JSON 定义编辑 + 示例）、运行输入/知识库选择、SSE 节点时间线（状态/耗时/尝试次数/输出摘要）、运行结果与错误展示。
- **导航/路由/中英文案**：`nav.workflows`、`/workflows`。

## Test Specification（新增 8）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | condition 只执行匹配分支，另一分支 skipped，最终输出正确 | `test_condition_skips_the_other_branch` | PASS |
| 2 | parallel 两分支并发（峰值 ≥2）并 join 拼接 | `test_parallel_branches_run_concurrently_and_join` | PASS |
| 3 | tool 节点调用 calculator 返回 4 | `test_tool_node_runs_calculator` | PASS |
| 4 | agent 节点运行 supervisor 并返回最终内容 | `test_agent_node_runs_supervisor` | PASS |
| 5–8 | condition 缺分支、parallel 出边不足、join 入边不足、非 condition 使用 when 均被拒绝 | `test_invalid_workflow_definitions_are_rejected`（+4 参数） | PASS |

原有线性执行、重试、失败、kb_search、workspace 隔离用例继续通过。

## Known Gaps

- **编辑器为 JSON 文本**：不是计划中的表单/拖拽画布；无节点可视化连线。
- **无运行历史列表 UI**：API 已提供 `GET /workflows/{id}/runs`，页面暂只显示本次运行。
- **condition 仅字符串比较**：equals/contains/not_empty 等，无数值/复杂表达式。
- **agent 节点固定 supervisor**：不能直接指定 retrieval/math 或自定义 agent。
- **并行输出顺序**：join 按边定义顺序拼接，不保证完成顺序。
- **同步 SSE 执行**：长工作流仍占用请求连接；成本只记 run，未入 `usage_events`。
- **无工作流审计/模板市场**。