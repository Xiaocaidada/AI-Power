# TDD Evidence — P5-S3: Python SDK 与 Webhook

- **Date:** 2026-11-22
- **Scope:** `sdk/python` 同步/异步客户端、SSE 解析、错误/重试；Webhook 订阅、HMAC 签名、重试/重放、SSRF、投递日志、`/settings/webhooks`、`workflow:run` scope
- **Source:** [`docs/plan/p5-plan.md`](../plan/p5-plan.md) P5-S3、[`ADR-0021`](../adr/0021-sdk-webhooks.md)

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| Webhook 测试 | `pytest tests/test_webhooks.py -q` | **8 passed** |
| SDK 测试 | `pytest tests/test_sdk.py -q` | **6 passed** |
| Workflow scope 测试 | `pytest tests/test_workflows.py::test_workflow_run_requires_workflow_scope_for_api_keys -q` | **1 passed** |
| 定向回归 | `pytest tests/test_webhooks.py tests/test_sdk.py tests/test_workflows.py tests/test_api_keys.py tests/test_migrations.py tests/test_conversations.py tests/test_collaboration.py -q` | **68 passed** |
| 后端全量 | `pytest -q` | **348 passed, 3 skipped**（351 collected） |
| Lint/Format | `ruff check .` / `ruff format --check .` | 通过 |
| SDK 安装 | `uv pip install -e sdk/python` | 安装成功 |
| 前端单测 | `npm test` | **22 passed** |
| 类型/构建 | `npm run typecheck` / `npm run build` | 通过 |
| E2E | `npm run test:e2e` | **2 passed** |

## Test Specification

| # | What is guaranteed | Test |
|---|---|---|
| 1 | 创建 Webhook 返回一次 secret，列表不返回 secret，DB 中加密 | `test_create_webhook_returns_secret_once_and_encrypts_at_rest` |
| 2 | 事件入队后投递带正确 HMAC 签名与事件头 | `test_webhook_event_creates_delivery_with_valid_signature` |
| 3 | 非 2xx 进入 failed 并记录 attempts，可重放为 pending | `test_failed_delivery_is_retried_and_can_be_replayed` |
| 4 | 仅 owner 可管理 Webhook（member 403） | `test_webhook_management_requires_owner` |
| 5 | 未知事件 422 | `test_webhook_rejects_unknown_events` |
| 6 | 消息 finalize 会为订阅写入投递 | `test_message_finalize_enqueues_webhook_delivery` |
| 7 | SSRF 拒绝私网/非法 URL，允许显式放行私网 | `test_ssrf_guard_rejects_private_addresses` |
| 8 | 签名稳定且绑定 body | `test_signature_is_stable_and_body_bound` |
| 9 | 同步登录/模型/SSE 流、错误映射、API Key、429 重试 | `test_sync_*` / `test_get_retries_429_with_retry_after` |
| 10 | 异步登录与 SSE 流 | `test_async_login_and_stream` |
| 11 | SSE 注释与多行 data 解析 | `test_sse_parser_supports_comments_and_multiline_data` |
| 12 | API Key 只有 `workflow:run` 才能触发 workflow | `test_workflow_run_requires_workflow_scope_for_api_keys` |

## Real SDK smoke

```text
AIPowerClient("http://192.168.29.100:8002")
login -> models=2
knowledge_bases=["检索评测集", "P5 检索演示 0bc2"]
retrieval_search("退款多久到账") -> mode=hybrid+rerank
top_hit="退款与报销政策\n\n退款一般在 3 个工作日内原路退回…"
```

SDK 已通过 `uv pip install -e sdk/python` 安装到本地 venv。

## Real Webhook checks

- `POST /webhooks` 创建 `https://example.com/ai-power-demo`，订阅 5 类事件，返回一次性 `whsec_…` secret；`GET /webhooks` 不返回 secret。
- `/settings/webhooks` 页面已验证：列表、事件标签、启用/暂停、投递记录入口、删除确认、创建弹窗与 secret 一次性展示。
- 投递签名/重试使用 `httpx.MockTransport` 验证（避免向真实第三方发送测试事件）。
- SSRF 校验对 `https://example.com` 公网 IPv4 通过；localhost/私网默认拒绝。

## Known Gaps

- **SDK 未发布 PyPI**：`pip install -e sdk/python`，版本随仓库。
- **SDK workflow 对齐同步 SSE**：P5-S5 改为 202 + 事件回放后需更新。
- **Webhook 只保证至少一次**：不保证顺序；集成方需用 `X-AI-Power-Delivery` 去重。
- **Secret 不可恢复**：丢失只能删除重建。
- **服务端未强制校验时间戳窗口**：示例建议集成方校验（防重放）。
- **SSRF 有 DNS rebinding 残余风险**：投递前会再次解析，但不能完全消除。
- **投递依赖 worker**：worker 停机时保持 pending；每 1 分钟扫描一次。
- **无真实第三方投递验证**：测试使用 fake HTTP client，避免外部副作用。
- **无 Webhook/Eval 管理 SDK 方法**：当前 SDK 聚焦运行时接口。
- **前端无 URL 编辑/事件编辑**：可改 active，URL/events 变更需重建（PATCH 已支持，UI 未暴露）。