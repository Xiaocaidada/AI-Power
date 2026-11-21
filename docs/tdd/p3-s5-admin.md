# TDD Evidence — P3-S5: 管理后台与审计

- **Date:** 2026-11-21
- **Scope:** 平台管理员、用户/Workspace/全局用量、模型启停、审计日志与 90 天清理、前端 `/admin`
- **Source:** [`docs/plan/p3-plan.md`](../plan/p3-plan.md) P3-S5（D6 管理员 + 审计）

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 新增管理端测试 | `pytest tests/test_admin.py` | **6 passed** |
| 后端全量 | `pytest -q` | **271 passed, 3 skipped** |
| Lint/Format | `ruff check` / `ruff format --check` | 通过 |
| 前端单测 | `npm test` | 18 passed |
| 类型/构建 | `npm run typecheck` / `npm run build` | 通过 |

## 交付

- **管理员判定**：`require_admin` 依赖基于 `users.role == "admin"`；非管理员一律 404，匿名 401。授权脚本：`python scripts/grant_admin.py <email>`（无默认管理员）。
- **API**（均 `/admin`，JWT）：
  - `GET /admin/users?limit&before`
  - `GET /admin/workspaces?limit&before`（含 `member_count`）
  - `GET /admin/workspaces/{id}/members`
  - `GET /admin/usage?from&to&group_by`（全局 requests/tokens/cost/unpriced）
  - `GET /admin/models`（含已停用）、`PATCH /admin/models/{id}` 启停
  - `GET /admin/audit-logs?limit&before`
- **审计**：`audit_logs` 表（actor/action/target/detail/created_at）；模型启停写 `model.toggle`；worker 每日 03:30 删除超过 `AUDIT_LOG_RETENTION_DAYS`（默认 90 天）的记录。
- **模型目录语义**：一旦存在已登记 provider 的目录行，目录即为权威来源；全部停用时返回空列表，不再回退到实时模型列表（保证“停用即消失”）。
- **前端**：仅管理员可见的 `/admin` 导航；Tabs 展示总览（全局用量/成本）、用户、Workspace 与成员、模型启停、审计日志；`apiRequest` 支持 PATCH，CORS 允许 PATCH。

## Test Specification（新增 6）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 非管理员访问 `/admin/*` 返回 404，匿名 401 | `test_admin_endpoints_hide_from_non_admins` | PASS |
| 2 | 用户/Workspace 列表与成员查询、limit 生效 | `test_admin_lists_users_workspaces_and_members` | PASS |
| 3 | 停用模型后广场消失，`/admin/models` 仍可见，审计落库 | `test_admin_toggles_model_and_writes_audit_log` | PASS |
| 4 | 全局用量跨 workspace 聚合 requests/tokens/cost | `test_admin_usage_aggregates_all_workspaces` | PASS |
| 5 | 审计日志按 id 倒序分页 | `test_admin_can_paginate_audit_logs` | PASS |
| 6 | 90 天前审计记录被清理 | `test_cleanup_audit_logs_removes_expired` | PASS |

## Known Gaps

- **管理员角色只能通过脚本授予**：无 API/UI 管理角色，无邀请流程。
- **审计仅覆盖模型启停**：登录、成员变更、配额调整等尚未审计。
- **无 Workspace 删除/计划修改**；无用户禁用功能。
- **列表仅 `limit`/`before`**：没有搜索/筛选。
- **前端 `/admin` 无 Vitest 覆盖**，以 typecheck/build 为准。
- **无二次认证/IP 白名单**；仍按局域网部署假设。
- **`require_admin` 依赖 JWT**：API Key 无法访问管理端（符合预期）。