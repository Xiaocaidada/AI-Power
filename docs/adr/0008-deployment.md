# ADR-0008: P1 部署、日志与备份

- **Status:** Accepted
- **Date:** 2026-11-21
- **Deciders:** 项目作者
- **Related:** [`docs/plan/p1-plan.md`](../plan/p1-plan.md) S6、[`docs/tdd/p1-s6-deploy.md`](../tdd/p1-s6-deploy.md)

## Context

P1 需要在本地虚拟机上提供可演示的完整平台：

- 只做局域网访问（`192.168.29.100`），不做公网、不配 HTTPS。
- 前端是 Vite 构建的 SPA，需要静态托管，并需要与 API 同源以便 SSE 与请求简单化。
- VM 的 8000/8001 已被 vLLM 占用，对外端口必须避开。
- 需要能定位单个请求（用户、耗时、状态），并具备最小备份能力。

## Decision

### 1. 拓扑与端口

```
browser → nginx (web:80 → host 8080)
             ├── /           静态 dist（SPA fallback）
             └── /api/*      proxy → api:8000（去掉 /api 前缀）
api ── postgres / redis
worker ── postgres / redis
backup ── postgres
```

| 服务 | 宿主机端口 | 说明 |
|---|---|---|
| web | 8080 | nginx 静态 + 反代 |
| api | 8002 | 直接调试用，容器 8000 |
| postgres | 5432 | pgvector/pg16 |
| redis | 6379 | 队列 + 限流 |

- 前端生产默认 `API_BASE=/api`，经 nginx 同源转发，不依赖 CORS。
- 开发环境 Vite 代理 `/api` 到 `192.168.29.100:8002`。
- `CORS_ORIGINS` 仍保留，覆盖直接访问 API 的场景。

### 2. SSE

- nginx 对 `/api/` 关闭 `proxy_buffering` 与缓存，超时 900s。
- 前端使用 `fetch + ReadableStream`，不经 EventSource。

### 3. 日志

- `LOG_FORMAT=json`（compose 默认）：每行包含 `ts, level, logger, message, request_id`，访问日志额外包含 `method, path, status, duration_ms, user_id`。
- `LOG_FORMAT=text` 为本地开发默认，字段以 `key=value` 附加。
- 请求 ID：接受合法的 `X-Request-ID`（≤64 字符、ASCII 字母数字与 `-_.`），否则生成 32 位 hex，并回写响应头。
- 流式请求的 `duration_ms` 是“到响应头”的时间（近似 TTFT），不是完整流时长。

### 4. 连接池与超时

- 流式响应在返回前释放请求级 DB 会话，避免长连接占用连接池。
- Postgres 池默认 `pool_size=10, max_overflow=20`（可配置），SQLite 使用 `NullPool`。
- 本地模型默认 `PROVIDER_TIMEOUT_SECONDS=180`（compose），避免 20 并发排队时被 60s 读超时误杀。

### 5. 备份

- `backup` 服务每天执行 `pg_dump -Fc` 到 `backups` 卷，保留 7 天，启动即备份一次。
- 恢复使用 `pg_restore --clean`；脚本支持 `RUN_ONCE=1` 手动触发。

### 6. 压测

- `scripts/loadtest.py`：单账号、每请求一个会话、20 并发流式，统计 TTFT 与总耗时 P50/P95。
- 2026-11-21 本机 Qwen（llama.cpp）结果：20/20 成功、0 错误；TTFT P50 24.2s / P95 46.9s；总耗时 P50 29.0s / P95 51.6s。

## Consequences

### Positive

- 单机 compose 可一键重建；前端与 API 同源，SSE 行为稳定。
- 请求级可观测字段齐全，便于按 `request_id` 串联。
- 备份与压测脚本可重复执行。

### Negative / Risks

- **无 HTTPS、无公网**：仅局域网演示；上线需加 Caddy/证书与更严格的安全头。
- **单点**：单 VM、单 API 实例、单本地模型；无高可用。
- **备份在本地卷**：磁盘损坏会同时丢失数据与备份；P2 考虑异地/对象存储。
- **DeepSeek 未参与压测**：当前环境无密钥；脚本支持 `--provider-id`。
- **nginx 无访问日志配置**：依赖 API 访问日志；后续可补。
- **流式 duration 语义**：不是端到端完成时间，TTFT 由压测脚本单独测量。

### Alternatives Considered

| 方案 | 未采用原因 |
|---|---|
| Caddy/Traefik 自动 HTTPS | P1 明确不做公网/HTTPS |
| 前端独立 CDN + CORS 直连 API | SSE 与跨域配置更复杂，演示无收益 |
| 宿主机 nginx 而非容器 | 多一处配置漂移，compose 内更可复现 |
| 备份到宿主机目录 | 卷方式更简单，后续再改挂载 |

## Follow-ups

1. P2：HTTPS/域名、备份异地化、Prometheus/Grafana。
2. 为 nginx 增加访问日志与请求 ID 透传。
3. 有 DeepSeek 密钥后补 20 并发对照压测。
4. 压测脚本加入 CI 夜间任务（需真实模型或 mock provider）。