# ADR-0004: P1 会话认证与登录限流

- **Status:** Accepted
- **Date:** 2026-11-21
- **Deciders:** 项目作者
- **Related:** [`CAPABILITY.md`](../product/CAPABILITY.md) §3.2/§3.6、[`docs/plan/p1-plan.md`](../plan/p1-plan.md) S1、[`docs/tdd/p1-s1-infra.md`](../tdd/p1-s1-infra.md)

## Context

P1 要在局域网/VM 上长期运行，并把 access token 从 24 小时缩短。用户明确要求 refresh token。
同时，登录接口暴露在网络上，需要基础限流；Redis 已是 compose 依赖（后续 Arq 也会用）。

约束：

- 现有 JWT 只有 access token（HS256，`sub` + `exp`）。
- 部署目标是本地 VM + 局域网 IP/端口，暂不公网、暂不 HTTPS。
- P1 前端尚未开始，token 传输方式需要与前端约定。
- 不引入新的状态服务；refresh token 状态放 Postgres。

## Decision

### 1. 双 token：access 30 分钟 + refresh 7 天

- `ACCESS_TOKEN_TTL_MINUTES=30`（默认）。
- `REFRESH_TOKEN_TTL_DAYS=7`（默认）。
- 登录返回 `access_token / expires_in / refresh_token / refresh_expires_in`。
- access token 新增 `jti`，保证同一秒内签发的 token 也不相同。

### 2. refresh token 存储与轮换

- 生成：`secrets.token_urlsafe(48)`，返回明文一次；数据库只存 **SHA-256 哈希**（高熵随机串，无需 argon2）。
- `refresh_tokens` 表：`id, user_id, token_hash UNIQUE, expires_at, revoked_at, replaced_by_id, created_at`。
- `POST /auth/refresh`：
  1. 按哈希查记录；
  2. 拒绝不存在、已吊销、已过期；
  3. 生成新 refresh token；
  4. **条件更新**旧记录 `WHERE revoked_at IS NULL`，设置 `revoked_at` 与 `replaced_by_id`；
  5. 返回新的 access + refresh。
- 旧 token 二次使用会命中 `revoked_at IS NOT NULL` → 401。
- `POST /auth/logout`：按哈希吊销，幂等 204。
- 并发安全：条件更新 `rowcount != 1` 时回滚并 401，避免两个请求同时轮换成功。

### 3. 登录限流：Redis 固定窗口

- 键：`auth:login:<client_ip>`；`INCR` + 首次 `EXPIRE 60`。
- 超过 `LOGIN_RATE_LIMIT_PER_MINUTE`（默认 10）→ 429 + `Retry-After`。
- **Redis 不可用时 fail-open**：记录 warning，允许登录。理由是本地演示优先可登录；`/readyz` 会把 Redis 标记为 error，避免静默。
- IP 取 `request.client.host`，不信任 `X-Forwarded-For`（当前无反向代理；接入 nginx 时再配置可信代理）。

### 4. 健康检查

- `GET /healthz`：进程存活。
- `GET /readyz`：执行 `SELECT 1` 与 Redis `PING`；任一失败返回 503，并给出分项状态。

## Consequences

### Positive

- access token 泄漏窗口从 24 小时降到 30 分钟；refresh token 可吊销、可轮换。
- 登录暴力尝试有基础限流；Redis 故障可观测（readyz）。
- 不引入新表以外的组件；refresh 状态在 Postgres，便于审计。
- 迁移工具落地，后续 P1 表结构变更可版本化。

### Negative / Risks

- **无 token family 吊销**：检测到 refresh 重用时只拒绝该 token，不会吊销同一会话链（P2 可加）。
- **前端存储未定**：当前 refresh token 在 JSON body 返回；S5 需决定 `HttpOnly` cookie 或内存存储。HTTP 局域网下 cookie 的 `Secure` 不可用。
- **限流 fail-open**：Redis 故障时登录不受限；这是可用性与安全性的取舍。
- **IP 维度**：NAT 后多用户共享 IP；无代理配置时无法区分真实客户端。
- **无设备/会话列表**：用户不能查看或踢掉其他会话（P2）。

### Alternatives Considered

| 方案 | 未采用原因 |
|---|---|
| 只用 24h access token | 用户明确要求 refresh token；泄漏窗口过大 |
| 无状态 refresh JWT | 无法可靠吊销/轮换，需额外黑名单 |
| 存 refresh 明文 | 数据库泄漏即会话泄漏 |
| argon2 存 refresh | 高熵随机串无需慢哈希，且每次刷新都要验证，成本不必要 |
| Redis 存 refresh | 重启丢会话；Postgres 更适合审计 |
| Redis 故障时 fail-closed | 本地演示会因 Redis 抖动完全无法登录 |
| 信任 `X-Forwarded-For` | 无代理时客户端可伪造 |

## Follow-ups

1. S5 前端确定 refresh token 存储方式（优先 HttpOnly cookie；HTTP 局域网下需权衡）。
2. P2：token family / 重用检测后吊销整链；会话列表与设备管理。
3. P2：接入反向代理后配置可信代理与真实 IP。
4. 观察限流误伤（NAT），必要时改为 `IP + email` 双维度。