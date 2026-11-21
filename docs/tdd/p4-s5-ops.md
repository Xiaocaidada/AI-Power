# TDD Evidence — P4-S5: 运营增强与可选 HTTPS

- **Date:** 2026-11-22
- **Scope:** 管理员修改 workspace plan、run 失败率、workflow 发布审计、可选 Caddy HTTPS
- **Source:** [`docs/plan/p4-plan.md`](../plan/p4-plan.md) P4-S5（D8 可选 HTTPS、D9 运营）

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 新增运营测试 | `pytest tests/test_admin.py` | **9 passed（新增 3）** |
| 后端全量 | `pytest -q` | **303 passed, 3 skipped** |
| Lint/Format | `ruff check` / `ruff format --check` | 通过 |
| 前端单测 | `npm test` | 22 passed |
| 类型/构建 | `npm run typecheck` / `npm run build` | 通过 |
| E2E | `npm run test:e2e` | 1 passed（23.7s） |

## 交付

- **Plan 管理**：`PATCH /admin/workspaces/{id}/plan`（`free|pro`），立即影响 `plan_limits`（免费/Pro 的请求、token、Key、每日成本阈值）；写 `audit_logs`（`workspace.plan_change`，含 from/to）。
- **Run 失败率**：`GET /admin/runs/summary` 返回 workflow/collaboration 的 total/failed/failure_rate；前端总览显示两张失败率卡片。
- **审计扩展**：workflow 首次创建与每次新版本写 `workflow.publish`（target=workflow，detail 含 version/name），可在 `/admin/audit-logs` 查看。
- **前端管理端**：Workspace 表格内直接切换 plan；总览显示 run 失败率。
- **可选 HTTPS**：`deploy/Caddyfile` + compose `caddy` 服务（`profiles: ["https"]`，需 `CADDY_DOMAIN`）反代 `web:8080`；默认不启动。`deploy/prometheus.yml` 仍为可选观测 profile。

## Test Specification（新增 3）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 改 plan 后配额立即生效并写审计；非法 plan 422 | `test_admin_changes_workspace_plan_and_audits` | PASS |
| 2 | 全局 workflow/collaboration 失败率统计 | `test_admin_run_failure_summary` | PASS |
| 3 | workflow 创建/新版本写 publish 审计 | `test_workflow_publish_writes_audit_log` | PASS |

## Known Gaps

- **无 plan 历史/生效时间**：只有当前 plan 与审计记录，无计划变更时间线。
- **失败率仅按状态计数**：无按 provider/模型/时间窗口细分。
- **审计覆盖仍有限**：仅 model toggle、plan change、workflow publish；用户/成员/Key 变更未审计。
- **HTTPS 未在 CI 验证**：需要真实域名与证书；Caddy profile 默认关闭。
- **无组织层级/RBAC/SSO**（明确不在 P4）。
- **管理端无用户禁用/workspace 删除**。