# TDD Evidence — P2-S4: Trace 可观测

- **Date:** 2026-11-21
- **Scope:** `traces` 表、聊天链路阶段耗时、`GET /traces/{request_id}`、7 天清理
- **Source:** [`docs/plan/p2-plan.md`](../plan/p2-plan.md) S4
- **Test runner:** pytest（Python 3.13）+ 真实 Postgres / 本机 Qwen

## User Journeys

1. 作为用户，我能按 `request_id` 查看一次回答的检索、首 token 与总耗时。
2. 作为用户，失败的回答能查到错误码与状态。
3. 作为用户，`auto` 路由能查到实际 provider 与尝试次数。
4. 作为其他 workspace 用户，我无法查看别人的 trace。
5. 作为维护者，7 天前的 trace 会被自动清理。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 单测 | `pytest tests/test_traces.py` | `5 passed` |
| 全量 | `pytest` | **224 passed, 3 skipped** |
| 覆盖率 | `pytest --cov=app` | **TOTAL 94%** |
| Lint / Format | `ruff check` / `ruff format --check` | 通过 |

## 真实环境验证

```
POST .../messages（X-Request-ID: p2s4-xxxxxxxx，auto 路由）
GET /traces/p2s4-xxxxxxxx
→ 200 {status: completed, provider_id: local-qwen,
       ttft_ms: 6703.1, total_ms: 8122.1, attempts: 1}
另一用户访问同一 request_id → 404
```

## Test Specification（5）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 聊天完成写入 trace，含 provider/model/TTFT/总耗时/attempts | `test_chat_creates_trace_with_stages` | PASS |
| 2 | trace 按 workspace 隔离，跨租户 404 | `test_trace_is_workspace_scoped` | PASS |
| 3 | 流中 provider 失败 → status=failed + error_code | `test_failed_stream_records_error_code` | PASS |
| 4 | `auto` 记录实际 provider 与尝试次数 | `test_auto_trace_records_attempts` | PASS |
| 5 | 7 天前 trace 被清理，新 trace 保留 | `test_cleanup_traces_removes_only_old_rows` | PASS |

## 关键实现

- **表**：`traces(request_id, workspace_id, user_id, conversation_id, message_id, provider_id, model, retrieval_ms, ttft_ms, total_ms, status, error_code, attempts, created_at, updated_at)`；`message_id` 唯一。
- **阶段计时**：检索耗时在 `retrieve_chunks` 前后测；首 token 在第一个 `delta` 时写入；总耗时在终止分支写入。
- **状态**：`streaming → completed | failed | cancelled`；错误码来自 `ProviderError` 或 `internal_error`。
- **关联**：`messages.request_id` 保存中间件生成的请求 ID；`GET /traces/{request_id}` 按当前 workspace 过滤。
- **清理**：`cleanup_traces` 删除 7 天前记录；worker 每日 03:15 执行。
- **auto**：`_open_auto_stream` 返回尝试次数，写入 trace。

## Known Gaps

- **只记录聊天链路**：入库/上传没有 trace。
- **503（无可用 provider）不落 trace**：在创建消息前失败，没有 message_id。
- **无 trace 列表接口**：只能按 `request_id` 查询；S5 抽屉需要时可加。
- **trace 不存正文**：只有耗时与元数据，便于排查但不还原 prompt。
- **前端未展示**：S5。
- **无 Prometheus/metrics**：按决策 D6 不接。
- **时间以服务端单调时钟计算**：跨进程/容器重启不影响单次请求，但无法跨服务拼接。