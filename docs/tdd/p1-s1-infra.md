# TDD Evidence — P1-S1: Auth sessions, migrations, health, container

- **Date:** 2026-11-21
- **Scope:** P1-S1（refresh token、登录限流、`/readyz`、Alembic 初始迁移、Dockerfile/compose/CI）
- **Source:** [`docs/plan/p1-plan.md`](../plan/p1-plan.md) §4 S1、[`ADR-0004`](../adr/0004-auth-sessions.md)、[`CAPABILITY.md`](../product/CAPABILITY.md) §3.2/§3.6
- **Test runner:** pytest（Python 3.13.15）；默认 SQLite；fake Redis 通过依赖覆盖注入
- **Commits:** RED/GREEN 见提交历史（本文件随后续文档提交）

## User Journeys

1. 作为用户，我希望 access token 过期后不用重新登录，而是用 refresh token 换新。
2. 作为用户，我希望退出登录后 refresh token 立即失效。
3. 作为运维者，我希望暴力登录尝试被限流，并能通过 `/readyz` 判断依赖是否可用。
4. 作为维护者，我希望数据库 schema 通过迁移版本化，而不是启动时 `create_all`。
5. 作为部署者，我希望一条 `docker compose up -d` 就能启动 API 并自动迁移。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| RED | `.venv/Scripts/python.exe -m pytest tests/test_auth_refresh.py tests/test_rate_limit.py tests/test_health.py tests/test_migrations.py` | 收集阶段失败：`ImportError: cannot import name 'RefreshToken'`、`ModuleNotFoundError: No module named 'alembic'`（另有 `app.clients` / `rate_limit` 缺失） |
| GREEN | `.venv/Scripts/python.exe -m pytest` | `156 passed, 3 skipped` |
| Coverage | `... --cov=app --cov-report=term-missing` | `TOTAL 1375 54 96%` |
| Lint | `... -m ruff check .` | `All checks passed!` |
| Format | `... -m ruff format --check .` | `73 files already formatted` |

**RED 证据（节选）**

- `tests/test_auth_refresh.py` → `ImportError: cannot import name 'RefreshToken' from 'app.models'`
- `tests/test_migrations.py` → `ModuleNotFoundError: No module named 'alembic'`
- `tests/conftest.py::fake_redis` → `ModuleNotFoundError: app.clients`
- `tests/test_rate_limit.py` → `app.services.rate_limit` 不存在

**GREEN 前实现范围**：`RefreshToken` 模型、refresh token 哈希/轮换/吊销、`/auth/refresh`、`/auth/logout`、Redis 客户端与登录限流、`/healthz`、`/readyz`、Alembic 初始迁移、Dockerfile、compose `api`、CI。

## 真实环境验证

### 1. Alembic 在 WSL Postgres 上升级/回滚

```
alembic upgrade head    → 10 张表（含 refresh_tokens、alembic_version）
pg_indexes             → ix_chunk_embeddings_embedding_hnsw USING hnsw (embedding vector_l2_ops)
alembic downgrade base → 仅剩 alembic_version（1 张表）
alembic upgrade head   → 恢复 10 张表
```

### 2. 容器构建

```
docker build -t ai-power:ci .
```

结果见文末「容器验证」。

### 3. compose 配置

```
docker compose config -q   → OK
```

## Test Specification

### Refresh tokens（`tests/test_auth_refresh.py`，7）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 登录返回 access + refresh，TTL 分别为 30 分钟 / 7 天 | `test_login_returns_access_and_refresh_tokens` | PASS |
| 2 | 数据库只存 SHA-256 哈希，不存明文 | `test_refresh_token_is_stored_hashed_and_not_in_plaintext` | PASS |
| 3 | refresh 轮换：新 token 生效，旧 token 二次使用 401，旧记录标记 revoked/replaced_by | `test_refresh_rotates_token_and_rejects_reuse` | PASS |
| 4 | 未知 refresh token → 401 | `test_refresh_rejects_unknown_token` | PASS |
| 5 | 过期 refresh token → 401 | `test_refresh_rejects_expired_token` | PASS |
| 6 | logout 吊销且幂等，吊销后 refresh 失败 | `test_logout_revokes_refresh_token_and_is_idempotent` | PASS |
| 7 | 空 refresh token → 422 | `test_refresh_requires_a_well_formed_token` | PASS |

### Login rate limit（`tests/test_rate_limit.py`，3）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 8 | 第 11 次登录返回 429 + `Retry-After` + typed code | `test_login_is_rate_limited_per_client` | PASS |
| 9 | 限流按客户端 IP 隔离 | `test_rate_limit_is_keyed_by_client_ip` | PASS |
| 10 | Redis 不可用时 fail-open（登录仍成功）且记录 warning | `test_login_fails_open_when_redis_is_unavailable` | PASS |

### Health（`tests/test_health.py`，4）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 11 | `/healthz` 返回 `{"status":"ok"}` | `test_healthz_returns_ok` | PASS |
| 12 | `/readyz` 检查 DB + Redis 均正常时 200 | `test_readyz_reports_database_and_redis` | PASS |
| 13 | Redis 故障时 503 且分项标记 error | `test_readyz_returns_503_when_redis_is_down` | PASS |
| 14 | DB 故障时 503 且分项标记 error | `test_readyz_returns_503_when_database_is_down` | PASS |

### Migrations（`tests/test_migrations.py`，1）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 15 | `alembic upgrade head` 在空库创建全部表与 refresh 字段，且可重复执行 | `test_alembic_upgrade_head_creates_schema` | PASS |

### 既有测试更新

- `tests/test_auth.py::test_login_returns_bearer_token`：`expires_in` 由 1440 分钟改为 30 分钟，并断言 refresh 字段。
- `tests/conftest.py`：新增 FakeRedis（autouse 依赖覆盖），避免测试连接真实 Redis。

## Coverage

```
TOTAL                             1375     54    96%
```

新增/修改模块均被覆盖；未覆盖的 6 行集中在 `app/vector.py` 的方言分支与既有边角。

## Known Gaps

- **refresh 重用不吊销整链**：只拒绝旧 token，不吊销同会话 family（P2）。
- **refresh 交付方式未定**：当前 JSON body；S5 前端需决定 HttpOnly cookie 或内存存储。
- **限流 fail-open**：Redis 故障时登录不受限；`/readyz` 会暴露该故障。
- **IP 维度**：不信任 `X-Forwarded-For`，NAT 后多人共享 IP。
- **无会话/设备列表**：不能查看或踢掉其他会话。
- **CI 未实际在 GitHub 运行**：workflow 与本地命令一致，首次 push 后验证。
- **compose 仅 API**：worker 在 S2 加入。

## 容器验证

```
docker build -t ai-power:ci .                          → exit 0
docker compose up -d api                               → 容器启动，自动执行 alembic upgrade head
GET http://192.168.29.100:8002/healthz                 → 200 {"status":"ok"}
GET http://192.168.29.100:8002/readyz                  → 200 {"status":"ok","checks":{"database":"ok","redis":"ok"}}
```

auth 冒烟（容器 + 真实 Postgres/Redis）：

```
register                 → 201
login                    → 200（access + refresh）
refresh                  → 200，refresh token 已轮换
旧 refresh 再次使用       → 401
logout                   → 204
logout 后 refresh        → 401
expires_in               → 1800（30 分钟）
refresh_expires_in       → 604800（7 天）
```

**环境发现**：VM 的 `8000` 与 `8001` 均被 vLLM 占用（`ss -tlnp` 显示 `vllm` 进程），
API 容器映射到宿主机 **`8002`**（容器内仍为 8000）。已在 compose 与文档中固定。

**配置陷阱**：`.env` 末尾缺少换行时追加键会粘到上一行（曾导致 `EMBEDDING_DIM=1024REFRESH_TOKEN_TTL_DAYS=7`，
容器启动时 Pydantic 校验失败）。追加配置时必须保证前置换行；已修复本地 `.env`。