# TDD Evidence — P3-S4: 成本面板

- **Date:** 2026-11-21
- **Scope:** 价格快照、成本计算、`GET /usage/cost`、用量页成本卡片与趋势
- **Source:** [`docs/plan/p3-plan.md`](../plan/p3-plan.md) P3-S4（D5 写入时快照价格）

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 新增成本测试 | `pytest tests/test_costs.py` | **5 passed** |
| 后端全量 | `pytest -q` | **265 passed, 3 skipped** |
| Lint/Format | `ruff check` / `ruff format --check` | 通过 |
| 前端单测 | `npm test` | 18 passed |
| 类型/构建 | `npm run typecheck` / `npm run build` | 通过 |

## 交付

- **快照字段**：`usage_events` 增加 `input_price`、`output_price`、`cost`、`unpriced`（迁移 `b8c9d0e1f2a3`；历史行默认 `cost=0, unpriced=true`）。
- **写入时机**：助手消息 finalize 时按 `(provider_id, model)` 查 `model_catalog`，把当时价格与成本写入事件；查不到模型记 0 且 `unpriced=true`；NULL token 按 0 计但不算 unpriced。
- **成本公式**：`prompt_tokens/1e6*input_price + completion_tokens/1e6*output_price`，保留 6 位小数。
- **API**：`GET /usage/cost?from&to&group_by=day|provider|model`，返回 `total_cost`、`unpriced_requests` 与分桶成本；SQL `GROUP BY` + `SUM(cost)`，workspace 隔离。
- **前端**：用量页新增成本 KPI、未定价提示、成本趋势图（Recharts）与表格成本列；复用现有时间范围与分组选择。

## Test Specification（新增 5）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 成本按快照价格计算，day/model 分桶一致 | `test_cost_uses_price_snapshot` | PASS |
| 2 | catalog 改价后历史成本不变，新请求用新价 | `test_price_changes_do_not_rewrite_history` | PASS |
| 3 | 未定价模型计 0 且计入 `unpriced_requests` | `test_unpriced_model_counts_zero_and_is_flagged` | PASS |
| 4 | 成本按 workspace 隔离 | `test_cost_is_workspace_scoped` | PASS |
| 5 | NULL usage 成本为 0 且不算未定价 | `test_null_usage_is_zero_cost_not_unpriced` | PASS |

## Known Gaps

- **历史数据未回填**：迁移把所有旧事件标记为 `unpriced=true`、成本 0；若需回填须按当时价格另写脚本。
- **单一货币**：按 USD 展示，catalog 价格含义由种子数据决定。
- **浮点存储**：`Float` 而非 `Numeric`；6 位小数对演示足够，不适用于真实结算。
- **未按 Key/用户/Agent 工具拆分成本**；仅消息维度。
- **成本图未处理多币种/税率/折扣**。
- **前端无成本相关单测**。