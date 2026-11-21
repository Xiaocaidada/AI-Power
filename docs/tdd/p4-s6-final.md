# TDD Evidence — P4-S6: 开放接口、示例与收口

- **Date:** 2026-11-22
- **Scope:** 工作流 API 文档与示例脚本、并发压测脚本、workflow Playwright、ADR-0016–0018、P4 收口
- **Source:** [`docs/plan/p4-plan.md`](../plan/p4-plan.md) P4-S6

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 后端全量（无后端改动） | `pytest -q` | **303 passed, 3 skipped** |
| Lint/Format | `ruff check` / `ruff format --check` | 通过 |
| 前端单测 | `npm test` | 22 passed |
| 类型/构建 | `npm run typecheck` / `npm run build` | 通过 |
| E2E | `npm run test:e2e` | **2 passed（21.5s）** |

## 交付

- **API 文档**：[`docs/api/workflows.md`](../api/workflows.md) — 接口、节点配置、校验规则、模板/执行语义、SSE 事件、错误码与 Python 示例。
- **示例脚本**：`scripts/workflow_example.py`（环境变量登录、创建/复用工作流、SSE 运行并打印 `workflow_end`，不打印凭据）。
- **压测脚本**：`scripts/loadtest_workflow.py` — 固定并发运行单节点工作流，输出成功数、P50/P95/mean 与 token 总数。
- **Playwright**：`web/e2e/workflow.spec.ts` — mock 登录与 API，运行工作流并断言节点 `draft`、`completed` 与最终输出。
- **ADR**：
  - [`0016-workflow-engine.md`](../adr/0016-workflow-engine.md)
  - [`0017-collaboration.md`](../adr/0017-collaboration.md)
  - [`0018-metrics-budget.md`](../adr/0018-metrics-budget.md)
- **文档更新**：README（工作流/协作/指标/预算/HTTPS 与命令）、CLAUDE（P4 完成、路由、架构、命令）、quickstart（指标与 HTTPS）。

## Test Specification（新增 1 条 E2E）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 工作流页面可运行并展示节点时间线与最终输出 | `workflow run shows node timeline and output` | PASS |

## Known Gaps

- **“SDK”是示例脚本**：不是可发布的 Python 包，无类型/版本。
- **压测脚本未在 CI 或真实环境执行**：结果取决于本机模型算力。
- **Playwright 仍为 mock API**：不覆盖真实 SSE/模型/数据库。
- **编辑器仍为 JSON 文本**：没有拖拽画布。
- **工作流/协作成本未进入 `usage_events`**，预算也不覆盖。
- **无工作流模板市场、无组织/RBAC、无移动端**。