# TDD Evidence — P1-S6: 部署、可观测与压测

- **Date:** 2026-11-21
- **Scope:** compose 全栈（web/nginx）、请求 ID 与结构化日志、备份、20 并发压测、README/CI
- **Source:** [`docs/plan/p1-plan.md`](../plan/p1-plan.md) S6、[`ADR-0008`](../adr/0008-deployment.md)
- **Test runner:** pytest 3.13；Vitest 3；构建 `docker compose up -d --build`

## User Journeys

1. 作为演示者，我能用 `docker compose up -d --build` 启动全部服务，并从局域网访问 Web。
2. 作为用户，我通过 Web 的 `/api` 完成登录、对话与知识库操作（同源，无需关心 CORS）。
3. 作为维护者，我能按 `request_id` 找到一次请求的路径、状态、耗时与用户。
4. 作为维护者，我能每天获得数据库备份，并能手动立即备份。
5. 作为维护者，我能用脚本验证 20 并发下的 TTFT 与总耗时。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| RED | `pytest tests/test_observability.py` | `ModuleNotFoundError: app.observability` |
| GREEN | `pytest tests/test_observability.py` | `5 passed` |
| 全量后端 | `pytest` | **202 passed, 3 skipped** |
| 覆盖率 | `pytest --cov=app` | **TOTAL 95%** |
| Lint / Format | `ruff check` / `ruff format --check` | 通过 |
| 前端 | `npm test` / `npm run build` | 18 passed / 构建通过 |

## 真实环境验证

### 1. 全栈启动

```
docker compose up -d --build
api / worker / web / postgres / redis / backup 全部启动
GET http://192.168.29.100:8080/            → 200（登录页）
GET http://192.168.29.100:8080/api/healthz → {"status":"ok"}
GET http://192.168.29.100:8080/api/readyz  → 200
```

浏览器访问 `http://192.168.29.100:8080` 渲染登录页（中文/English、邮箱/密码）。

### 2. 结构化日志

```json
{"ts":"2026-11-21T10:57:55.056+00:00","level":"INFO","logger":"app.access",
 "message":"request","request_id":"6de0eb3ab04b40c8a96184dea22e7648",
 "event":"request","method":"GET","path":"/readyz","status":200,"duration_ms":1.8}
```

认证请求额外包含 `user_id`（测试断言与真实日志均已确认）。

### 3. 备份

```
backup: writing /backups/ai_power_20261121T105739Z.dump
backup: completed
/backups/ai_power_20261121T105739Z.dump 存在
```

保留策略：`-mtime +7` 自动删除；`RUN_ONCE=1` 支持手动执行。

### 4. 20 并发压测（本机 Qwen / llama.cpp）

首次运行暴露连接池缺陷：

```
ok=12 errors=8
sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached
```

修复（流开始前释放请求会话 + 池 10/20 + provider 超时 180s）后：

```
provider=local-qwen model=qwen2.5-7b-instruct-q4_k_m concurrency=20 wall_s=51.6
ok=20 errors=0
ttft_ms p50=24191 p95=46883 max=47775
total_ms p50=28990 p95=51565 max=51569
tokens prompt=680 completion=400
QueuePool 错误：0
```

DeepSeek 当前环境无密钥，未参与对照；脚本支持 `--provider-id deepseek`。

## Test Specification（5）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 合法 `X-Request-ID` 原样回写 | `test_echoes_valid_request_id` | PASS |
| 2 | 缺失时生成 32 位 hex | `test_generates_request_id_when_missing` | PASS |
| 3 | 非法 ID 被替换 | `test_replaces_invalid_request_id` | PASS |
| 4 | 访问日志含 method/path/status/duration/user_id | `test_access_log_includes_user_id_and_duration` | PASS |
| 5 | JSON 格式包含 request_id 与扩展字段 | `test_json_formatter_includes_request_context` | PASS |

## 压测暴露并修复的缺陷

| 现象 | 根因 | 修复 |
|---|---|---|
| 20 并发下大量 500，`QueuePool limit ... reached` | 流式响应在依赖清理前一直持有请求级 DB 会话 | `send_message` 返回流前 `await session.close()`；池大小改为 `DB_POOL_SIZE=10` / `DB_MAX_OVERFLOW=20` |
| 修复后仍有 4–5 个 `provider_unreachable` | 本地模型排队导致单流超过默认 60s 读超时 | compose 设 `PROVIDER_TIMEOUT_SECONDS=180`，复测 0 错误 |
| Alembic 在进程内运行后访问日志消失 | `fileConfig` 默认禁用已有 logger | `disable_existing_loggers=False` |

## Known Gaps

- **无 HTTPS/公网**：局域网演示范围；上线需 Caddy 与证书。
- **单点部署**：单 VM、单 API、单本地模型；无高可用。
- **备份仅本地卷**：未异地化。
- **nginx 未配置独立访问日志**：依赖 API 日志。
- **流式 `duration_ms` 为响应头时间**：非完整生成时长。
- **CI 不跑 compose 冒烟与压测**：仅构建镜像；真实压测需模型服务。
- **DeepSeek 未压测**：无密钥。