# TDD Evidence — P1-S3: Usage events and citation persistence

- **Date:** 2026-11-21
- **Scope:** P1-S3（只追加用量事件、聚合 API、历史回填、引用持久化）
- **Source:** [`docs/plan/p1-plan.md`](../plan/p1-plan.md) S3、[`ADR-0006`](../adr/0006-usage-metering.md)、[`ADR-0003`](../adr/0003-retrieval.md)
- **Test runner:** pytest（Python 3.13.15）；默认 SQLite
- **Commits:** RED/GREEN 见提交历史

## User Journeys

1. 作为用户，我能在控制台看到按天/provider/model 的请求数与 token 用量。
2. 作为用户，我重新打开历史会话时仍能看到当时的引用。
3. 作为用户，我的用量与其他用户完全隔离。
4. 作为维护者，历史消息的 token 记录会被回填为事件，不会丢数据。
5. 作为维护者，用量事件只增不改，可用于后续审计与 API Key 统计。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| RED | `.venv/Scripts/python.exe -m pytest tests/test_usage.py tests/test_rag_chat.py tests/test_migrations.py` | 收集失败：`ImportError: cannot import name 'UsageEvent' from 'app.models'` |
| GREEN | `.venv/Scripts/python.exe -m pytest` | `178 passed, 3 skipped` |
| Coverage | `... --cov=app --cov-report=term-missing` | `TOTAL 1672 81 95%` |
| Lint / Format | `ruff check` / `ruff format --check` | 通过 |

**GREEN 前实现范围**：`UsageEvent` / `MessageCitation` 模型、`_finalize` 写事件与引用、会话详情返回引用、`GET /usage/summary`、迁移 0003 + 回填。

## 真实环境验证

### 1. Postgres 回填（迁移 0003）

在 `ai_power_test` 的 0002 schema 中插入一条带 token 的历史消息，再 upgrade：

```
messages: prompt_tokens=10, completion_tokens=5
usage_events: prompt_tokens=10, completion_tokens=5  ← 回填成功
```

### 2. 容器端到端（API + worker + local-qwen + bge-m3）

```
上传退款文档            → ready
本地 Qwen RAG 回答      → SSE: meta, citation, delta×17, usage, done
SSE citation 数         → 1
历史会话 citations      → 1（回放成功）
assistant tokens        → prompt 143 / completion 17
/usage/summary          → [{key: local-qwen, requests: 1, total_tokens: 160}]
```

## Test Specification

### Usage API（`tests/test_usage.py`，7）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 未认证 → 401 | `test_usage_summary_requires_auth` | PASS |
| 2 | 按天聚合 requests/prompt/completion/total | `test_usage_summary_groups_by_day` | PASS |
| 3 | 按 provider 与 model 聚合 | `test_usage_summary_groups_by_provider_and_model` | PASS |
| 4 | 不同用户用量隔离 | `test_usage_summary_is_isolated_by_user` | PASS |
| 5 | 非法 group_by → 422；from > to → 400 | `test_usage_summary_rejects_invalid_query` | PASS |
| 6 | 对话完成写入一条带 token 的事件 | `test_chat_writes_usage_event` | PASS |
| 7 | usage 缺失时仍写事件（token 为 NULL）且计入请求数 | `test_chat_records_null_usage_event` | PASS |

### 引用持久化（`tests/test_rag_chat.py` 更新）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 8 | RAG 回答的 citation 与历史详情一致 | `test_rag_conversation_emits_citations_for_retrieved_chunks` | PASS |
| 9 | 普通会话 citations 为空 | `test_plain_conversation_has_no_citations` | PASS |

### Migrations（`tests/test_migrations.py` 更新）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 10 | 迁移创建 `usage_events` / `message_citations` 及字段 | `test_alembic_upgrade_head_creates_schema` | PASS |
| 11 | 0003 从历史 messages 回填 usage_events | `test_usage_backfill_from_existing_messages` | PASS |

## Coverage

```
TOTAL                             1672     81    95%
```

未覆盖：`vector.py` 方言分支、worker cron 包装、部分入库异常分支等既有边角。新增模块均被测试覆盖。

## Known Gaps

- **Python 聚合**：事件量大时需改 SQL/预聚合。
- **按 API Key 的用量未实现**：P1-S4 再扩展事件维度。
- **失败/取消也计为请求**：这是刻意的请求计数口径，控制台需注明。
- **引用无法跳回已删除文档**：chunk 删除后仅保留 ID + snippet 快照。
- **day 桶固定 UTC**：前端需按用户时区换算。
- **无用量导出/告警**：P2/P3。