# ADR-0007: P1 API Key 与作用域

- **Status:** Accepted
- **Date:** 2026-11-21
- **Deciders:** 项目作者
- **Related:** [`ADR-0004`](./0004-auth-sessions.md)、[`docs/plan/p1-plan.md`](../plan/p1-plan.md) S4、[`docs/tdd/p1-s4-api-keys.md`](../tdd/p1-s4-api-keys.md)

## Context

P1 需要让用户用程序调用平台能力，而不是只能依赖浏览器 JWT：

- 不引入开放 API 平台（P3），但要有可演示的 Key 机制。
- Key 一旦泄漏不能导致整账号被接管（尤其是 Key 管理本身）。
- 需要能审计“最近使用时间”，并支持立即吊销。
- 现有认证只有 `Authorization: Bearer <JWT>`。

## Decision

### 1. Key 格式与存储

- 格式：`ap_<8 hex prefix>_<token_urlsafe(32)>`，例如 `ap_7d1f4ecd_...`。
- 数据库只存：
  - `prefix`：前 11 个字符（`ap_` + 8 hex），唯一索引，用于快速查找；
  - `key_hash`：完整 Key 的 SHA-256。
- 明文 Key 只在创建响应中返回一次；列表只返回元数据。
- 校验使用 `hmac.compare_digest`，避免时序侧信道。
- 前缀冲突（概率极低）时重试最多 3 次。

### 2. 认证方式

- 新依赖 `get_auth_context` 同时接受：
  - `Authorization: Bearer <JWT>` → `scopes=None`（拥有全部权限）；
  - `X-API-Key: <key>` → 解析出用户与 scopes。
- 两者同时出现时以 `X-API-Key` 为准。
- `get_current_user` 保持 **JWT-only**，用于账号管理类端点（Key 管理、归档、上传、删除等）。
- `require_scope(scope)` 工厂：JWT 直接通过；API Key 缺少 scope → 403 `insufficient_scope`。

### 3. 作用域与路由映射

最小 scope 集：`chat:write`、`kb:read`；默认 Key 同时拥有两者。

| 端点 | 认证 | 需要的 scope |
|---|---|---|
| `POST /conversations` | JWT 或 Key | `chat:write` |
| `POST /conversations/{id}/messages` | JWT 或 Key | `chat:write` |
| `GET /conversations`、`GET /conversations/{id}` | JWT 或 Key | `kb:read` |
| `DELETE /conversations/{id}` | JWT-only | — |
| `GET /knowledge-bases`、`GET /knowledge-bases/{id}` | JWT 或 Key | `kb:read` |
| `POST/DELETE /knowledge-bases` | JWT-only | — |
| `GET /documents/{id}` | JWT 或 Key | `kb:read` |
| 上传/重试/删除文档 | JWT-only | — |
| `/api-keys/*`、`/auth/me`、`/usage/*` | JWT-only | — |

### 4. 使用时间与吊销

- 每次成功认证后更新 `last_used_at`，但最多每 60 秒写一次，避免每个请求一次写库。
- `DELETE /api-keys/{id}` 设置 `revoked_at`；立即生效（后续请求 401），幂等 204。
- 不做物理删除，保留审计痕迹。
- 列表返回已吊销 Key（带 `revoked_at`），前端可区分。

### 5. 安全边界

- 不在日志、错误信息、响应中输出完整 Key（除创建响应）。
- Key 管理必须 JWT，防止泄漏的 Key 自我复制。
- 无 Key 过期时间、无常驻轮换端点；用户可“创建新 Key → 吊销旧 Key”。

## Consequences

### Positive

- 程序化访问可用，且泄漏影响被 scope 限制。
- Key 明文不落库；prefix 查找 + 哈希比较兼顾性能与安全。
- 路由映射明确，JWT 与 Key 的权限差异可测试。
- `last_used_at` 提供基础审计线索。

### Negative / Risks

- **无过期时间**：Key 永久有效直到吊销；P2 可加 `expires_at`。
- **无自动轮换**：只能手动创建/吊销。
- **scope 较粗**：没有按 KB/资源的细粒度授权。
- **无 per-key 限流/配额**：P2 与配额一起做。
- **prefix 可枚举**：前缀非秘密，但配合哈希无法伪造；仅暴露“存在性”，可接受。
- **X-API-Key 优先于 Bearer**：同时携带时以 Key 为准，前端需避免误用。

### Alternatives Considered

| 方案 | 未采用原因 |
|---|---|
| Key 走 `Authorization: Bearer` | 无法与 JWT 区分，错误提示与中间件复杂 |
| 存 Key 明文 | 数据库泄漏即凭据泄漏 |
| argon2 存 Key | 高熵随机串不需要慢哈希；每次请求验证成本高 |
| Key 内嵌 scope（JWT 式） | 改 scope 需换 Key，无法即时吊销/调整 |
| Key 可管理 Key | 泄漏后可无限续期，风险过大 |
| 每次请求都写 last_used_at | 写放大严重，60 秒节流足够审计 |

## Follow-ups

1. P2：`expires_at`、按 Key 的配额/限流、使用审计日志。
2. 细粒度 scope（按 KB/KB 级 `kb:read:{id}`）在需要时再设计。
3. 前端 S5c 展示 Key 列表（prefix、创建时间、最后使用、吊销）。
4. 观察 prefix 碰撞与 60 秒节流对审计的影响。