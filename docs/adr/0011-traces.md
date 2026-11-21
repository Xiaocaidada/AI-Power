# ADR-0011: Trace 存储与保留

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** [`docs/plan/p2-plan.md`](../plan/p2-plan.md) S4、[`docs/tdd/p2-s4-traces.md`](../tdd/p2-s4-traces.md)

## Context

P1 只有访问日志与用量事件，无法回答“这次回答慢在检索还是生成”。需要轻量、可查询、可演示的 trace，同时避免引入 Prometheus 运维复杂度。

## Decision

- `traces` 表按 `request_id` 记录一次聊天请求：
  `workspace_id, user_id, conversation_id, message_id, provider_id, model, retrieval_ms, ttft_ms, total_ms, status, error_code, attempts`。
- `messages.request_id` 保存中间件生成的请求 ID，使历史消息可跳到 trace。
- 阶段计时：检索在 `retrieve_chunks` 前后；首 token 在第一个 `delta`；总耗时在终止分支。
- 状态：`streaming → completed | failed | cancelled`。
- `GET /traces/{request_id}` 按 workspace 过滤；新增 `GET /traces?limit&before` 列表。
- 保留 7 天，worker 每日 03:15 清理。
- 不存 prompt/回答正文，不接 Prometheus。

## Consequences

**Positive**

- 能定位慢在检索还是生成，失败有 error_code。
- 表结构简单，随 workspace 隔离；保留策略明确。
- 与现有请求 ID 日志可直接对照。

**Negative**

- 只有聊天链路有 trace；入库/上传没有。
- 无可用 provider 的 503 在创建消息前发生，不落 trace。
- 流式 `duration_ms`（访问日志）与 trace 的 `total_ms` 语义不同，需分别理解。
- 无 metrics/告警；容量按 7 天估算。

## Follow-ups

1. 为入库与上传补 trace。
2. 增加列表页与筛选（status/provider/耗时）。
3. 需要时再引入 Prometheus 指标。