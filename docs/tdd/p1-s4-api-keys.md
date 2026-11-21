# TDD Evidence — P1-S4: API keys and scopes

- **Date:** 2026-11-21
- **Scope:** P1-S4（API Key 创建/列表/吊销、`X-API-Key` 认证、scope 控制、`last_used_at`）
- **Source:** [`docs/plan/p1-plan.md`](../plan/p1-plan.md) S4、[`ADR-0007`](../adr/0007-api-keys.md)、[`ADR-0004`](../adr/0004-auth-sessions.md)
- **Test runner:** pytest（Python 3.13.15）；默认 SQLite
- **Commits:** RED/GREEN 见提交历史

## User Journeys

1. 作为用户，我能创建 API Key 并用它程序化访问对话/知识库读取接口。
2. 作为用户，我只能在创建时看到一次完整 Key，之后只能看到前缀与元数据。
3. 作为用户，我可以限制 Key 只有 `kb:read` 或 `chat:write`。
4. 作为用户，我吊销 Key 后它立即失效。
5. 作为用户，我的 Key 与其他用户完全隔离。
6. 作为维护者，Key 明文不落库、不落日志；Key 管理必须用 JWT。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| RED | `.venv/Scripts/python.exe -m pytest tests/test_api_keys.py` | 收集失败：`ImportError: cannot import name 'ApiKey' from 'app.models'` |
| GREEN | `.venv/Scripts/python.exe -m pytest` | `185 passed, 3 skipped` |
| Coverage | `... --cov=app --cov-report=term-missing` | `TOTAL 1814 88 95%` |
| Lint / Format | `ruff check` / `ruff format --check` | 通过 |

**GREEN 前实现范围**：`ApiKey` 模型、Key 生成/哈希、`authenticate_api_key`、`AuthContext` / `require_scope`、`/api-keys` 路由、会话/知识库/文档的 scope 依赖、迁移 0004。

## 真实环境验证

### 1. 迁移 0004（WSL Postgres）

```
alembic upgrade b0eadf822c29 -> 588eba4a32fe
api_keys 列：id, user_id, name, prefix, key_hash, scopes, created_at, last_used_at, revoked_at
```

### 2. 容器端到端

```
POST /api-keys                     → 201，响应含完整 key（仅此一次）
GET /api-keys (JWT)                → 列表不含 key/key_hash
GET /knowledge-bases (X-API-Key)   → 200
GET /conversations/{id} (X-API-Key)→ 200
GET /api-keys (X-API-Key)          → 401（Key 管理必须 JWT）
POST /conversations (kb:read Key)  → 403
DELETE /api-keys/{id} (JWT)        → 204
GET /knowledge-bases (旧 Key)      → 401
last_used_at                       → 已更新
数据库 key_hash 长度                → 64（无明文）
```

## Test Specification（`tests/test_api_keys.py`，7）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | Key 管理端点只接受 JWT，Key 调用 → 401 | `test_api_key_management_requires_jwt` | PASS |
| 2 | 创建返回一次性明文；列表不含 key/hash；DB 存 SHA-256 | `test_create_key_returns_plaintext_once_and_stores_hash` | PASS |
| 3 | `chat:write` Key 可发送消息并写 usage，`last_used_at` 更新 | `test_key_with_chat_scope_can_send_messages` | PASS |
| 4 | `kb:read` 可列知识库但创建会话/发消息 403；`chat:write` 不能列知识库 | `test_key_scopes_are_enforced` | PASS |
| 5 | 吊销后立即 401；重复吊销 204 | `test_revoked_key_is_rejected` | PASS |
| 6 | Key 列表/吊销按用户隔离 | `test_keys_are_isolated_by_user` | PASS |
| 7 | 无效 Key → 401 | `test_invalid_api_key_is_rejected` | PASS |

### 迁移（`tests/test_migrations.py` 更新）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 8 | 迁移创建 `api_keys` 及全部字段 | `test_alembic_upgrade_head_creates_schema` | PASS |

## Coverage

```
TOTAL                             1814     88    95%
```

未覆盖：`vector.py` 方言分支、worker cron 包装等既有边角；新增认证/路由均被覆盖。

## Known Gaps

- **无过期时间/自动轮换**：Key 永久有效直到吊销。
- **无 per-key 限流/配额**：P2 与配额一起做。
- **scope 较粗**：不支持按知识库细粒度授权。
- **Key 管理仅 JWT**：浏览器之外的自动化无法轮换 Key（刻意安全取舍）。
- **prefix 可枚举**：仅暴露存在性，无法伪造哈希。
- **无使用审计明细**：只有 `last_used_at`，没有每次调用日志。