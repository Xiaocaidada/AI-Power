# TDD Evidence — P2-S6: 收口与欠账

- **Date:** 2026-11-21
- **Scope:** 分页（会话/文档/trace）、SQL 用量聚合、Playwright 冒烟入 CI、ADR-0009/0010/0011
- **Source:** [`docs/plan/p2-plan.md`](../plan/p2-plan.md) S6

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 后端全量 | `pytest --cov=app` | **228 passed, 3 skipped，覆盖率 94%** |
| 分页单测 | `pytest tests/test_pagination.py` | `3 passed` |
| 前端单测 | `npm test` | 18 passed |
| 类型/构建 | `tsc --noEmit` / `vite build` | 通过 |
| E2E | `npm run test:e2e` | **1 passed（8.6s）** |
| Lint | ruff check/format | 通过 |

## 交付

- **分页**：`GET /conversations`、`GET /knowledge-bases/{id}/documents`、`GET /traces` 支持 `limit`（1–200，默认 50）与 `before`（UUID 游标），按 id 倒序。`TraceOut` 增加 `id` 供游标使用。
- **SQL 聚合**：`GET /usage/summary` 改为数据库 `GROUP BY`（day/provider/model），不再全量拉取事件到 Python。
- **Playwright**：`web/e2e/smoke.spec.ts` 用路由 mock 完成“登录 → 新对话”冒烟；`playwright.config.ts` 使用 `vite preview`；CI 前端 job 安装 Chromium 并运行 E2E。
- **ADR**：0009（租户）、0010（路由/配额）、0011（trace）。

## Test Specification（新增 3）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 会话 `limit` + `before` 游标正确 | `test_conversation_pagination` | PASS |
| 2 | trace 列表分页且不重复 | `test_trace_list_pagination` | PASS |
| 3 | 文档列表分页 | `test_document_pagination` | PASS |

现有 `test_usage.py` 的 day/provider/model 分组用例验证 SQL 聚合结果与旧实现一致。

## Known Gaps

- **前端未接分页**：仍请求默认 50 条，无“加载更多”。
- **用量无分页**：聚合结果按时间/分组返回，未限制桶数量。
- **Playwright 只有 1 条 mock 冒烟**：不覆盖真实 API、SSE、对比表与 trace 抽屉。
- **CI E2E 依赖 `vite preview`**：首次构建增加 CI 时间。
- **未做 API Key 轮换提示**、暗色主题、workspace 删除/退出。
- **ADR-0009/0010/0011 为事后整理**，决策细节以各 TDD 证据为准。