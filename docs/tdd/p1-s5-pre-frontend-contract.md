# TDD Evidence — P1-S5-pre: 前端契约前置

- **Date:** 2026-11-21
- **Scope:** CORS 中间件、`GET /knowledge-bases/{kb_id}/documents`
- **Source:** [`docs/plan/p1-s5-frontend-ui.md`](../plan/p1-s5-frontend-ui.md) §9
- **Test runner:** pytest（Python 3.13.15）；默认 SQLite
- **Commits:** RED/GREEN 见提交历史

## User Journeys

1. 作为前端，我能从 `http://localhost:5173`（开发）与 `http://192.168.29.100:8080`（局域网）跨域调用 API。
2. 作为用户，我能在知识库详情页看到全部未删除文档及其状态、失败原因。
3. 作为用户，我只能看到自己知识库下的文档；他人的知识库返回 404。
4. 作为持有 `kb:read` Key 的调用方，我能列出文档；只有 `chat:write` 的 Key 被拒绝。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| RED | `.venv/Scripts/python.exe -m pytest tests/test_frontend_contract.py` | `11 failed`（无 CORS 头；列表路由 405） |
| GREEN | `.venv/Scripts/python.exe -m pytest tests/test_frontend_contract.py` | `12 passed` |
| Full suite | `.venv/Scripts/python.exe -m pytest` | `197 passed, 3 skipped` |
| Coverage | `... --cov=app --cov-report=term-missing` | `TOTAL 1826 88 95%` |
| Lint / Format | `ruff check` / `ruff format --check` | 通过 |

**GREEN 前实现范围**：`Settings.cors_origins` + `cors_origin_list`、`CORSMiddleware`、文档列表路由、`.env.example` 增加 `CORS_ORIGINS`。

## 设计要点

### CORS

- origins 来自 `CORS_ORIGINS`（逗号分隔），默认：
  `http://localhost:5173,http://127.0.0.1:5173,http://192.168.29.100:8080`
- `allow_credentials=False`：前端用 `Authorization: Bearer` 与 `X-API-Key`，不需要 cookie。
- 允许方法 `GET/POST/DELETE/OPTIONS`；允许头 `Authorization/Content-Type/X-API-Key`。
- 暴露 `Retry-After`，前端登录限流可读倒计时。
- `max_age=600`，减少预检请求。

### 文档列表

```
GET /knowledge-bases/{kb_id}/documents → 200 list[DocumentOut]
```

- 认证：`kb:read`（JWT 或具备该 scope 的 API Key）。
- 先校验知识库归属（跨用户 404，不泄露存在性）。
- 过滤 `deleted_at IS NULL`；按 `created_at DESC, id DESC` 排序（UUIDv7 时间有序，保证同一秒内也稳定）。
- 响应复用 `DocumentOut`，不暴露 `storage_path` / `content_hash`。

## 真实环境验证（容器 `192.168.29.100:8002`）

```
OPTIONS /auth/login (Origin localhost:5173) → 200
  access-control-allow-origin: http://localhost:5173
  access-control-allow-headers: … Authorization, Content-Type, X-API-Key
GET /healthz (Origin 192.168.29.100:8080)   → ACAO 正确，expose: Retry-After
GET /healthz (Origin evil.example)          → 无 ACAO
创建知识库                                   → 201
GET /knowledge-bases/{id}/documents（空）    → 200 []
上传 note.md                                 → 202 uploaded
轮询文档列表                                  → 200 [("note.md", "ready", 1)]
他人访问同一 KB 文档列表                       → 404
X-API-Key（kb:read）列表                      → 200
删除文档 / 知识库                              → 204 / 204
```

## Test Specification（`tests/test_frontend_contract.py`，12）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 预检允许配置的 Vite origin，并允许 Authorization/X-API-Key | `test_cors_preflight_allows_configured_origin` | PASS |
| 2 | 局域网 web origin 被允许 | `test_cors_allows_lan_web_origin` | PASS |
| 3 | 未知 origin 不返回 ACAO | `test_cors_ignores_unknown_origin` | PASS |
| 4 | 实际响应暴露 `Retry-After` | `test_cors_exposes_retry_after` | PASS |
| 5 | 列表按新建优先，字段不含存储路径/哈希 | `test_list_documents_returns_newest_first` | PASS |
| 6 | 软删文档不出现在列表 | `test_list_documents_excludes_deleted` | PASS |
| 7 | 空知识库返回 `[]` | `test_list_documents_for_empty_kb_returns_empty_list` | PASS |
| 8 | 他人知识库返回 404 | `test_list_documents_on_foreign_kb_returns_404` | PASS |
| 9 | 未认证返回 401 | `test_list_documents_requires_auth` | PASS |
| 10 | `kb:read` Key 可列出文档 | `test_api_key_with_kb_scope_can_list_documents` | PASS |
| 11 | 仅 `chat:write` Key 返回 403 | `test_api_key_without_kb_scope_cannot_list_documents` | PASS |
| 12 | 返回的 id 是合法 UUID | `test_list_documents_returns_uuid_ids` | PASS |

## Known Gaps

- **无分页**：一次返回知识库全部文档；P1 数据量可接受，P2 加 `limit/cursor`。
- **无文档计数**：知识库列表页无法显示文档数，详情页只能进入后统计。
- **CORS 为静态 allowlist**：新增域名需改 env 并重启；不做正则匹配。
- **不校验来源 IP**：局域网场景接受。
- **`/providers` 仍 JWT-only**：API Key 调用方无法列模型（刻意，Key 只服务对话/读取）。