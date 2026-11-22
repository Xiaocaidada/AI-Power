# ADR-0021: Python SDK 与 Webhook 开放平台

- **Status:** Accepted
- **Date:** 2026-11-22
- **Context:** P3/P5 已有 OpenAPI 与 curl 示例，但外部接入仍需手写 SSE/分页/错误处理；同时平台事件只能被前端轮询，无法可靠推送给外部系统。P5-S3 需要把平台从“有 API”推进到“可被集成”。

## Decision

### Python SDK

- 位置：`sdk/python`，包名 `ai_power_sdk`，可 `pip install -e sdk/python`；**不发布 PyPI**。
- 同步 `AIPowerClient` + 异步 `AsyncAIPowerClient`，共享相同的请求/SSE 语义。
- 认证：邮箱密码登录/刷新、`access_token`、`refresh_token`、`api_key`；401 自动刷新一次。
- 能力：models、conversations + chat SSE、knowledge bases/documents（上传/等待就绪）、retrieval search、workflow run SSE、collaboration run SSE、usage summary。
- SSE：解析 `event:`/`data:`，返回 `SSEEvent(event, data)`，`event.json()` 解析 JSON。
- 错误：`AIPowerError(status_code, code, message, request_id, body)`；GET 对 429/5xx 最多重试 2 次并遵守 `Retry-After`；流式请求不重试。
- 依赖仅 `httpx`；测试用 `httpx.MockTransport`，不依赖真实模型。

### Webhook

- 数据模型：`webhooks`（workspace、URL、加密 secret、逗号分隔 events、active/软删除）+ `webhook_deliveries`（事件、payload、status、attempts、response、next_attempt_at）。
- 事件：`message.completed`、`document.ready`、`document.failed`、`workflow.completed`、`collaboration.completed`、`budget.exceeded`。
- 入队：业务代码调用 `enqueue_event(workspace_id, event, payload)`，只写投递行，不做网络请求；业务失败不影响主流程。
- 投递：Arq worker 每分钟扫描到期投递，`httpx` POST，超时 10s、不跟随重定向。
- 签名：`X-AI-Power-Signature: t=<unix>,v1=<HMAC_SHA256(secret, f"{t}.{body}")>`；另带 `X-AI-Power-Event` 与 `X-AI-Power-Delivery`。
- 重试：最多 5 次，1m / 5m / 30m / 2h / 6h；超过上限 mark `dead`；管理端可重放。
- Secret：`whsec_<48 hex>`，创建时返回一次；用 `WEBHOOK_SECRET_KEY` 派生 Fernet 密钥加密存储；非 dev 未配置则启动失败。
- SSRF：仅 http/https、拒绝 URL 凭据；解析主机并拒绝 loopback/私网/link-local/reserved/multicast；`WEBHOOK_ALLOW_PRIVATE_HOSTS=true` 仅用于局域网演示。
- 权限：Webhook 管理仅 workspace owner 的 JWT；API Key 不管理 Webhook。
- 新增 API Key scope `workflow:run`：允许 Key 触发工作流，`chat:write` 不再隐式允许 workflow run。

## Consequences

- 外部集成方可以 `pip install -e sdk/python` 后直接流式调用；SDK 不在 PyPI，版本随仓库。
- Webhook 投递与主请求解耦，但依赖 worker；worker 停机时投递保持 pending。
- 只保证“至少一次”，不保证顺序；集成方用 `X-AI-Power-Delivery` 去重。
- Secret 不能再次读取；丢失需删除重建。
- 时间戳校验由集成方完成；服务端未强制拒绝旧时间戳（重放防护在客户端）。
- SSRF 防护有 DNS rebinding 残余风险；投递前二次解析降低风险但不能完全消除。
- SDK 在 P5-S3 对齐同步 SSE；P5-S5 已更新为 202 + 事件回放（`start_*` / `*_run_events` / `cancel_*`），见 [ADR-0023](0023-async-runs.md)。

## Alternatives

- **只提供 OpenAPI/curl**：无法展示 SDK 工程能力，外部接入成本高。
- **发布 PyPI**：账号/版本/发布流程超出个人项目范围。
- **Webhook 直接在业务请求里发送**：阻塞主流程、无重试、失败不可见。
- **Redis pub/sub 或独立 MQ**：多一个组件；DB 投递队列足够演示。
- **明文存 secret**：数据库泄露即签名密钥泄露；Fernet 加密成本低。
- **允许 API Key 管理 Webhook**：Key 泄露即可改回调地址，风险高；保持 JWT-only。

## Follow-ups

- P5-S5：workflow/collaboration 改为后台 run + 事件日志后更新 SDK 与 Webhook 事件语义。
- 可增加事件签名时间戳窗口校验、投递并发上限、死信告警。
- 可为 SDK 增加评测/Webhook 管理方法。
- 可增加 `workflow.failed`、`eval.completed` 等更细粒度事件。