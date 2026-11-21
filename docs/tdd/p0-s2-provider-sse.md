# TDD Evidence — P0 S2: Provider abstraction + SSE chat

- **Date:** 2026-11-21
- **Scope:** S2（provider 抽象 + SSE 流式对话）
- **Source:** [`PRODUCT-BRIEF.md`](../../PRODUCT-BRIEF.md)、[`docs/product/CAPABILITY.md`](../product/CAPABILITY.md)（P0）
- **Test runner:** pytest（Python 3.13.15），SQLite + aiosqlite
- **Commits:** RED `18fdfba`，GREEN `ff3ef97`（分支 `feat/p0-s2-provider-sse`）

## User Journeys

1. 作为用户，我想看到可用的 provider 与模型，以便选择。
2. 作为用户，我想用指定 provider/model 创建会话。
3. 作为用户，我想发送消息并看到回复逐字流式返回。
4. 作为用户，我想让我的会话与其他用户隔离。
5. 作为用户，我想在模型失败时看到明确的错误事件，并知道该条回复失败。
6. 作为用户，我想在 provider 返回 usage 时记录 token；未返回时显示为空而不是假数据。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| RED | `.venv/Scripts/python.exe -m pytest` | `7 failed, 29 passed, 15 errors in 4.99s` |
| GREEN（最小实现） | 同上 | `51 passed in 9.33s` |
| GREEN（补错误分支后） | 同上 | `68 passed in 12.74s` |
| Coverage | `... -m pytest --cov=app --cov-report=term-missing` | `TOTAL 594 0 100%` |
| Lint | `... -m ruff check .` | `All checks passed!` |
| Format | `... -m ruff format .` | `31 files already formatted` |

**RED 证据（节选）**

- `tests/test_openai_compat.py::*` → `ModuleNotFoundError: No module named 'app.providers'`
- `tests/test_conversations.py::*` → registry fixture 导入失败（`app.providers` 缺失）
- 既有 29 条 S1 测试仍全部通过，失败集中在新增能力上。

**GREEN 前实现范围**：`LLMProvider` / `ChatMessage` / `ChatChunk` / `Usage`、`OpenAICompatProvider`、`ProviderRegistry`、`GET /providers`、`Conversation` / `Message` 模型、会话 CRUD、SSE 消息端点与落库。

## 真实模型冒烟

同一实现直接连本地 Qwen（`http://192.168.29.100:8083/v1`）：

```
models: ['/home/wq/models/qwen2.5-7b-instruct/qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf']
text: ok
usage: [Usage(prompt_tokens=33, completion_tokens=2)]
finish: ['stop']
```

第一次冒烟时流式响应**没有** usage；加 `stream_options.include_usage=true` 后返回。该改动走了一个小 TDD 循环：

- 先让 `test_stream_sends_bearer_token_and_stream_flag` 断言 `payload["stream_options"] == {"include_usage": True}` → RED（`KeyError`）。
- 再在 `OpenAICompatProvider` 的请求体加入该字段 → GREEN。

## Test Specification

### Provider 单元（`tests/test_openai_compat.py`，15）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | SSE 增量文本、finish_reason、usage 正确解析 | `test_stream_parses_deltas_usage_and_finish` | PASS |
| 2 | 请求带 Bearer、`stream=true`、`stream_options.include_usage` 与正确 messages | `test_stream_sends_bearer_token_and_stream_flag` | PASS |
| 3 | 无 api_key 时不发送 Authorization | `test_stream_omits_authorization_without_api_key` | PASS |
| 4 | HTTP 5xx → `provider_http_error` | `test_stream_raises_provider_error_on_http_failure` | PASS |
| 5 | 连接失败 → `provider_unreachable`（流式） | `test_stream_raises_provider_error_when_unreachable` | PASS |
| 6 | 非法 SSE 行被忽略，不影响后续内容 | `test_stream_ignores_malformed_sse_lines` | PASS |
| 7 | `/v1/models` 解析 id 与 provider | `test_list_models_parses_ids_and_provider` | PASS |
| 8 | 模型列表 HTTP 失败 → `provider_http_error` | `test_list_models_raises_provider_error_on_http_failure` | PASS |
| 9 | 模型列表非 JSON → `provider_bad_response` | `test_list_models_raises_provider_error_on_invalid_json` | PASS |
| 10 | 模型列表缺 `data` → `provider_bad_response` | `test_list_models_rejects_missing_data` | PASS |
| 11 | 模型列表顶层非对象 → `provider_bad_response` | `test_list_models_rejects_non_object_payload` | PASS |
| 12 | 非整数 token 字段按 null 处理 | `test_non_integer_usage_is_reported_as_null` | PASS |
| 13 | 无内容的 SSE 事件被忽略 | `test_stream_ignores_events_without_content` | PASS |
| 14 | 未注入 client 时自行创建并应用 timeout | `test_provider_creates_its_own_client_when_none_injected` | PASS |
| 15 | 模型列表连接失败 → `provider_unreachable` | `test_list_models_raises_provider_error_when_unreachable` | PASS |

### API / SSE（`tests/test_conversations.py`，21）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 16 | `/providers` 需要认证 | `test_providers_endpoint_requires_auth` | PASS |
| 17 | `/providers` 返回 id/available/models，且不含密钥 | `test_providers_endpoint_returns_metadata_without_secrets` | PASS |
| 18 | 创建会话需要认证 | `test_create_conversation_requires_auth` | PASS |
| 19 | 未知 provider → 404 | `test_create_conversation_rejects_unknown_provider` | PASS |
| 20 | 空白 model → 422 | `test_create_conversation_rejects_blank_model` | PASS |
| 21 | 会话列表按用户隔离 | `test_conversations_are_isolated` | PASS |
| 22 | SSE 事件顺序为 meta→delta→delta→usage→done，且助手消息落库 | `test_send_message_streams_and_persists` | PASS |
| 23 | 向他人会话发消息 → 404 | `test_send_message_requires_ownership` | PASS |
| 24 | 空白消息内容 → 422 | `test_send_message_rejects_blank_content` | PASS |
| 25 | provider 错误 → error 事件，助手消息 `failed` | `test_provider_error_emits_event_and_marks_message_failed` | PASS |
| 26 | 无 usage 时事件与落库均为 null | `test_missing_usage_is_reported_as_null` | PASS |
| 27 | 第二轮请求携带历史（user/assistant/user）与 model | `test_provider_receives_history_and_model` | PASS |
| 28 | 所有者可归档会话，随后 404 且列表为空 | `test_owner_can_archive_conversation` | PASS |
| 29 | 归档他人会话 → 404 | `test_archiving_other_users_conversation_returns_404` | PASS |
| 30 | 用他人知识库建会话 → 404 | `test_create_conversation_with_foreign_knowledge_base_returns_404` | PASS |
| 31 | provider 不可用时 `/providers` 标记 `available=false` | `test_providers_endpoint_marks_unavailable_provider` | PASS |
| 32 | 会话的 provider 已不存在时发消息 → 409 | `test_send_message_with_missing_provider_returns_409` | PASS |
| 33 | 未预期异常 → `internal_error` 事件，消息 `failed` | `test_unexpected_provider_exception_emits_internal_error` | PASS |
| 34 | finalize 遇到不存在的消息安全返回 | `test_finalize_ignores_missing_message` | PASS |
| 35 | finalize 数据库异常被记录且不中断 | `test_finalize_swallows_database_errors` | PASS |
| 36 | 取消流 → 助手消息 `cancelled` 且保留已生成内容 | `test_cancelled_stream_marks_message_cancelled` | PASS |

### Registry（`tests/test_registry.py`，3）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 37 | 配置了 key/base_url 的 provider 被构建 | `test_build_registry_includes_configured_providers` | PASS |
| 38 | 未配置的 provider 被省略 | `test_build_registry_omits_unconfigured_providers` | PASS |
| 39 | `get_registry` 懒加载且缓存 | `test_get_registry_is_lazy_and_cached` | PASS |

## Coverage

```
TOTAL                              594      0   100%
```

## Known Gaps

- **取消路径是合成的**：测试让 provider 主动抛 `CancelledError`，未模拟真实客户端断开（ASGITransport 不易模拟）。
- **DeepSeek 未冒烟**：测试中使用 fake provider；本机未在测试里读取 `.env` 的 key。
- **SQLite only**：Postgres/pgvector 行为仍待 S3 验证。
- **无前端**：SSE 消费端（React）尚未实现。
- **`stream_options` 兼容性**：llama.cpp 实测支持；若某 provider 拒绝该字段，需要降级重试策略（当前未实现）。
- **RAG 上下文/引用**：S3/S4 才接入；当前消息历史只含纯文本对话。

## Merge Evidence

- RED checkpoint：`18fdfba test: add P0 S2 provider and SSE conversation coverage`
- GREEN checkpoint：`ff3ef97 feat: implement provider abstraction and SSE chat`
- 本报告随文档提交保留；若后续 squash，请把 RED/GREEN 摘要与真实冒烟结果写入 squash commit 正文。