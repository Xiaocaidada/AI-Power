# ADR-0006: P1 用量事件与引用持久化

- **Status:** Accepted
- **Date:** 2026-11-21
- **Deciders:** 项目作者
- **Related:** [`ADR-0003`](./0003-retrieval.md)、[`ADR-0005`](./0005-ingestion-queue.md)、[`docs/plan/p1-plan.md`](../plan/p1-plan.md) S3、[`docs/tdd/p1-s3-usage.md`](../tdd/p1-s3-usage.md)

## Context

P1 需要：

- 控制台展示 token 用量（按时间/provider/model）。
- 会话历史能回放当时的引用，而不是重新检索。
- 用量记录一旦写入不可被业务修改（能力契约 I7）。
- 未来 API Key（P1-S4）也需要按调用方统计用量。

现状：`messages` 已有 `prompt_tokens/completion_tokens`，但没有独立事件、没有聚合 API，引用只存在于 SSE 流中。

## Decision

### 1. 只追加的 `usage_events`

- 表：`id, user_id, conversation_id?, message_id UNIQUE, provider_id?, model?, prompt_tokens?, completion_tokens?, created_at`。
- 每个最终确定（completed / cancelled / failed）的助手消息写一条事件；`message_id` 唯一保证幂等。
- **usage 缺失也写事件**（token 为 NULL），用于请求计数；聚合时按 0 处理 token。
- 写入发生在 `_finalize` 的独立会话中，与消息状态更新同一事务。
- 业务代码只插入、不更新、不删除（I7）；统计通过查询完成。

### 2. 历史回填

- 迁移 `0003` 在创建表后，把 `messages` 中 `role='assistant'` 且 token 非空的记录复制为 `usage_events`。
- 迁移只执行一次；回填在 Postgres 上用真实消息验证（10/5 tokens）。

### 3. 聚合 API

`GET /usage/summary?from&to&group_by=day|provider|model`

- 仅返回当前用户数据（`user_id` 过滤）。
- 默认范围：最近 30 天；`from > to` → 400；非法 `group_by` → 422。
- 桶字段：`requests`、`prompt_tokens`、`completion_tokens`、`total_tokens`。
- **在 Python 中聚合**：先按用户/时间过滤，再分组。P1 事件量小，避免 SQLite/Postgres 日期函数差异；数据量上来后改 SQL 聚合。
- `day` 使用 UTC 日期键；`provider/model` 缺失时归入 `unknown`。

### 4. `message_citations` 持久化

- 表：`id, message_id, citation_index, document_id, chunk_id, page_no, snippet, created_at`。
- `(message_id, citation_index)` 唯一；与助手消息一起在 finalize 写入。
- 写入的正是 SSE 中发送的同一组 `Citation` 对象（来自 `fit_context` 后的真实 chunk），满足 I3。
- `document_id/chunk_id` 使用**普通 UUID 列，不设外键**：文档删除会级联删除 chunk，但历史引用仍需保留原始 ID 与 snippet。
- `GET /conversations/{id}` 返回每条消息的 `citations`，按 `citation_index` 排序。

### 5. 范围

- 不做：用量导出、预算告警、按 API Key 的维度（P1-S4 再把 `api_key_id` 加到事件或另建维度）。
- `token_count`（chunk）仍为 NULL，与用量事件无关。

## Consequences

### Positive

- 用量不可变、可审计；请求计数包含失败/取消，不会被 token 缺失吞掉。
- 历史会话可回放引用，前端无需重新检索。
- 聚合 API 与 UI 解耦，后续 API Key 用量可复用事件表。
- 回填让历史消息立刻出现在控制台。

### Negative / Risks

- **Python 聚合**：内存与延迟随事件量线性增长；10 万级事件后需改 SQL 聚合/预聚合表。
- **每个助手消息一条事件**：重试同一消息（当前不存在）会因唯一约束冲突，需要显式处理。
- **引用快照**：chunk 删除后 ID 仍保留但无法跳回原文；snippet 是唯一可回放内容。
- **事件写入失败**：`_finalize` 捕获异常并记录日志，消息仍会更新；极端情况下会丢失用量（数据库故障时消息也可能丢失）。
- **时区**：day 桶固定 UTC，前端需按用户时区展示时自行换算。

### Alternatives Considered

| 方案 | 未采用原因 |
|---|---|
| 直接聚合 `messages` | 失败/取消且无 token 的消息无法计数；未来 API Key 调用没有 message |
| `messages.citations` JSON 列 | 难查询/难保证唯一；历史引用与消息耦合 |
| 引用外键到 chunks | chunk 硬删后引用被置空，历史不可读 |
| SQL `date_trunc` 聚合 | SQLite 测试与 Postgres 行为差异，P1 收益低 |
| 引入 Prometheus 指标 | P1 非目标，控制台需要的是按用户查询 |

## Follow-ups

1. 事件量增大后改为 SQL 聚合或按日预聚合。
2. P1-S4：API Key 调用写入同一事件表（增加 `api_key_id` 维度或独立事件）。
3. 控制台图表（S5c）消费 `/usage/summary`。
4. 为 `_finalize` 增加指标/告警，观察事件写入失败。