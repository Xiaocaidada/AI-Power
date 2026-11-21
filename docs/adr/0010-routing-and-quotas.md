# ADR-0010: 模型目录、自动路由与配额

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** [`docs/plan/p2-plan.md`](../plan/p2-plan.md) S2/S3、[`docs/tdd/p2-s2-routing.md`](../tdd/p2-s2-routing.md)、[`docs/tdd/p2-s3-quotas.md`](../tdd/p2-s3-quotas.md)

## Context

需要模型广场（元数据/对比）、按优先级的路由与降级，以及 workspace/Key 级配额。此前只有实时 `/providers` 与登录限流。

## Decision

### 模型目录

- `model_catalog(provider_id, model_id)` 唯一，含显示名、上下文、输入/输出价格、标签、`priority`、`enabled`。
- `GET /models` 合并目录与 Redis 熔断状态；目录为空时回退到实时 provider 列表。
- `GET /models/compare?ids=` 最多 5 个。

### 路由与降级

- 会话可创建为 `provider_id=auto, model=auto`。
- 发送时按 `priority` 生成候选，跳过“连续 3 次失败、60s 冷却”的 provider。
- 逐个打开流并读取首个 chunk；首 token 前失败换下一个；全部失败返回 503 `no_provider_available`。
- 首 token 后失败不重试，发 SSE `error`。
- 消息记录实际 provider/model，trace 记录尝试次数。

### 配额

- 静态计划：free 60 req/min、200k token/天、5 Key；pro 600 req/min、5M token/天、50 Key。
- Redis 计数器；发送消息与上传前检查；Key 创建检查数量。
- 429 返回 `quota_exceeded` + `Retry-After` + `X-Quota-*`。
- token 在流结束后按实际 usage 累加；Redis 故障 fail-open。

## Consequences

**Positive**

- 单 provider 故障不再直接失败（首 token 前）。
- 广场与路由共享目录，策略可配置。
- 配额对 workspace 和 Key 均有效。

**Negative**

- 目录价格/上下文需人工维护。
- 熔断是全局 provider 维度，不区分 workspace/模型。
- token 配额事后计费，单条消息可能短暂超额。
- 无计费/成本结算（P3）。

## Follow-ups

1. 管理端维护目录元数据。
2. 按模型/workspace 的路由策略与配额。
3. 预扣 token 配额或流中限额。