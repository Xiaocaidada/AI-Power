# TDD Evidence — P0 S1: Auth + 用户隔离

- **Date:** 2026-11-21
- **Scope:** S1（auth + 用户隔离）
- **Source:** [`PRODUCT-BRIEF.md`](../../PRODUCT-BRIEF.md)、[`docs/product/CAPABILITY.md`](../product/CAPABILITY.md)（P0）
- **Test runner:** pytest（Python 3.13.15），SQLite + aiosqlite（本机无 Docker）

## User Journeys

1. 作为访客，我想用邮箱和密码注册，以便获得账号。
2. 作为已注册用户，我想登录并拿到 token，以便调用 API。
3. 作为已登录用户，我想查看自己的资料，以便确认身份。
4. 作为用户，我想让我的知识库对其他用户不可见，以便数据隔离。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| RED | `.venv/Scripts/python.exe -m pytest` | `21 failed in 0.19s` |
| GREEN | 同上 | `21 passed in 2.66s` |
| GREEN（补充覆盖用例后） | 同上 | `29 passed in 3.63s` |
| Coverage | `... -m pytest --cov=app --cov-report=term-missing` | `TOTAL 239 0 100%` |
| Lint | `... -m ruff check .` | `All checks passed!` |
| Format | `... -m ruff format .` | 14 files reformatted，随后 check 通过 |

**RED 证据（节选）**

- `tests/test_auth.py::test_register_returns_201_and_public_user` → `assert 404 == 201`
- `tests/test_auth.py::test_login_returns_bearer_token` → `assert 404 == 200`
- `tests/test_isolation.py::test_get_other_users_knowledge_base_returns_404` → `AssertionError: login failed: 404`
- `tests/test_security.py::*` → `ModuleNotFoundError: No module named 'app.security'`

RED 的失败原因是缺失实现（路由与 security 模块），不是测试配置或依赖错误；测试收集成功后才逐条失败。首次运行曾因 `app.security` 在模块顶层导入导致收集中断，改为惰性导入后得到完整的 21 条失败。

**GREEN 前的实现范围**：`User` / `KnowledgeBase` 模型、argon2id 哈希、HS256 JWT、`HTTPBearer` 依赖、`/auth/register|login|me`、知识库 CRUD 与软删除、用户隔离过滤。

## Test Specification

| # | What is guaranteed | Test | Type | Result |
|---|---|---|---|---|
| 1 | 注册返回 201，邮箱小写归一，且不返回密码字段 | `tests/test_auth.py::test_register_returns_201_and_public_user` | integration | PASS |
| 2 | 重复邮箱（大小写不敏感）返回 409 | `test_register_duplicate_email_is_case_insensitive` | integration | PASS |
| 3 | 非法邮箱返回 422 | `test_register_rejects_invalid_email` | integration | PASS |
| 4 | 少于 8 位密码返回 422 | `test_register_rejects_short_password` | integration | PASS |
| 5 | 登录返回 bearer token、`expires_in=86400`、`sub` 为合法 UUID | `test_login_returns_bearer_token` | integration | PASS |
| 6 | 错误密码返回 401 | `test_login_with_wrong_password_is_rejected` | integration | PASS |
| 7 | 不存在的邮箱与错误密码返回相同 401 文案（不泄露账号是否存在） | `test_login_does_not_reveal_whether_email_exists` | integration | PASS |
| 8 | `/auth/me` 返回当前用户 | `test_me_returns_current_user` | integration | PASS |
| 9 | 无 token 访问 `/auth/me` 返回 401 | `test_me_without_token_is_rejected` | integration | PASS |
| 10 | 畸形 token 返回 401 | `test_me_with_malformed_token_is_rejected` | integration | PASS |
| 11 | 过期 token 返回 401 | `test_me_with_expired_token_is_rejected` | integration | PASS |
| 12 | 合法 token 指向不存在用户时返回 401 | `test_me_with_token_for_unknown_user_is_rejected` | integration | PASS |
| 13 | 用户只能看到自己的知识库 | `tests/test_isolation.py::test_user_sees_only_own_knowledge_bases` | integration | PASS |
| 14 | 读取他人知识库返回 404 | `test_get_other_users_knowledge_base_returns_404` | integration | PASS |
| 15 | 删除他人知识库返回 404，且原数据保留 | `test_delete_other_users_knowledge_base_returns_404_and_keeps_it` | integration | PASS |
| 16 | 知识库端点未认证返回 401 | `test_knowledge_base_endpoints_require_auth` | integration | PASS |
| 17 | 纯空白名称返回 422 | `test_knowledge_base_name_must_not_be_blank` | integration | PASS |
| 18 | 所有者删除自己的知识库返回 204，后续读取 404（软删除） | `test_owner_can_delete_own_knowledge_base` | integration | PASS |
| 19 | 密码哈希加盐且可验证 | `tests/test_security.py::test_password_hash_is_salted_and_verifiable` | unit | PASS |
| 20 | access token 往返得到同一 user id | `test_access_token_round_trip` | unit | PASS |
| 21 | 过期 token 被拒绝 | `test_expired_access_token_is_rejected` | unit | PASS |
| 22 | 畸形 token 被拒绝 | `test_malformed_access_token_is_rejected` | unit | PASS |
| 23 | 非法哈希串不会让验证抛异常 | `test_verify_password_rejects_invalid_hash` | unit | PASS |
| 24 | 非 access 类型 token 被拒绝 | `test_decode_rejects_token_without_access_type` | unit | PASS |
| 25 | 缺少 `sub` 的 token 被拒绝 | `test_decode_rejects_token_without_subject` | unit | PASS |
| 26 | `sub` 不是 UUID 的 token 被拒绝 | `test_decode_rejects_non_uuid_subject` | unit | PASS |
| 27 | 非 dev 环境拒绝 `dev-` 前缀的 JWT secret | `tests/test_config.py::test_dev_secret_is_rejected_outside_dev` | unit | PASS |
| 28 | `init_db()` 能建表 | `tests/test_app.py::test_init_db_creates_tables` | integration | PASS |
| 29 | 应用 lifespan 会执行 `init_db()` | `test_app_lifespan_runs_init_db` | integration | PASS |

## Coverage

```
TOTAL                              239      0   100%
```

关键修正：SQLAlchemy async 通过 greenlet 执行同步 ORM 代码，coverage 默认只追踪切换前的行。加入 `[tool.coverage.run] concurrency = ["greenlet", "thread"]` 后，`auth.py` / `knowledge_bases.py` / `deps.py` 从误报的 68%/74%/86% 变为 100%。

## Known Gaps

- **测试数据库是 SQLite**：本机未安装 Docker，Postgres 特有的 UUID 存储、唯一约束与 pgvector 行为尚未验证。S3 引入 pgvector 时应增加在 Postgres 上运行的集成测试。
- **无 Alembic**：当前用 `Base.metadata.create_all()`；生产迁移方案待引入。
- **登录限流未实现**：能力契约中的 10 次/分钟/IP 推迟到 P1（Redis）。
- **无 refresh token**：access token 24h，过期需重新登录。
- **无 CORS 配置**：前端接入 S2 时补。
- **无 E2E/UI 测试**：S2 起再覆盖前端关键流程。
- **密码策略仅最小长度 8**：未做复杂度/常见密码检查。
- **JWT secret 长度**：默认值与测试值均 ≥32 字节，但未在 Settings 中强制最小长度（仅禁止非 dev 使用 `dev-` 前缀）。

## Merge Evidence

本仓库当前**不是 git 仓库**，因此未创建 TDD checkpoint commits。RED/GREEN/refactor 的证据以本报告和上述命令输出为准；若后续 `git init`，请把本文件保留在 PR 或 squash commit 的正文中。