# ADR-0015: 平台管理员与审计日志

- **Status:** Accepted
- **Date:** 2026-11-21
- **Context:** P2 的 workspace `owner` 只是租户内角色。需要平台级运营能力（看全局用量、启停模型），但又不想引入复杂 RBAC。

## Decision

- 复用 `users.role`：`admin` = 平台管理员，与 workspace `owner` 正交。
- `/admin/*` 通过 `require_admin` 依赖；非管理员返回 **404**（隐藏接口），匿名 401。
- 管理员只能通过脚本授予：`python scripts/grant_admin.py <email>`，无默认账号/密码。
- 管理端提供：用户列表、workspace 列表与成员、全局用量/成本、模型目录（含停用）与启停、审计日志分页。
- **目录权威性**：只要存在已登记 provider 的 `model_catalog` 行，就以目录为准；全部停用时 `/models` 为空，不再回退到实时列表。
- `audit_logs(actor_user_id, action, target_type, target_id, detail, created_at)`；写操作与业务变更同一事务提交；worker 每日 03:30 删除超过 `AUDIT_LOG_RETENTION_DAYS`（默认 90 天）的记录。

## Consequences

- 权限模型简单，演示与答辩易解释。
- 审计目前仅覆盖 `model.toggle`；登录、成员变更、配额调整未记录。
- 无二次认证/IP 白名单，仍按局域网部署假设。
- 管理员角色修改没有 API/UI，避免误操作，但运维需能执行脚本。

## Alternatives

- **独立 admin 服务/复杂 RBAC**：超出 P3 范围。
- **非管理员返回 403**：会暴露管理端存在；404 更符合项目“跨租户 404”的隐藏约定。
- **仅结构化日志**：不可查询、不可演示审计。