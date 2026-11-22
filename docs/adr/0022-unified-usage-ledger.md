# ADR-0022: 统一用量账本

- **Status:** Accepted
- **Date:** 2026-11-22
- **Context:** P1 的 `usage_events` 只记录聊天消息，`message_id` 非空；工作流与协作把成本留在各自 run 表，导致用量页、预算与 `/metrics` 三套口径。

## Decision

- **账本在调用点写入**：每次产生 token 的 LLM 调用写一条 `usage_events`，而不是每个 run 汇总一条。聊天、工作流节点、协作步骤共用同一张表。
- **来源与归属**：
  - `source`：`chat | workflow | collaboration`，默认 `chat`，历史行迁移时回填。
  - `message_id` 改为可空；新增 `api_key_id`、`workflow_node_run_id`、`collaboration_step_id`。
  - `workflow_node_run_id` 与 `collaboration_step_id` 唯一（可空），保证重复 finalize / 重试不会重复计费。
- **写入边界**：
  - 聊天：`_finalize` 一次调用写一条，携带调用方 `AuthContext.api_key_id`。
  - 工作流：每个 `llm` / `agent` 节点成功调用后写一条，价格快照在调用时读取；节点失败的已计费 token 最多只能记录到节点成功的那一次（provider 流式中途失败通常不会返回 usage）。
  - 协作：每个 planner / worker / critic 步骤写一条；worker 失败但已产生 usage 时也写。
  - 每次写入快照 `input_price` / `output_price`，后续目录改价不回写历史。
- **查询**：
  - `GET /usage/summary` 与 `GET /usage/cost` 新增 `group_by=source`，并支持 `source`、`api_key_id` 过滤。
  - 新增 `GET /usage/by-key`，按 API Key 汇总请求/token/成本；JWT 调用归入 `api_key_id=null` 的“未归属”桶。
  - 所有查询强制 `workspace_id` 过滤，跨 workspace 不可见。
- **预算与指标**：
  - 预算继续按 workspace 当日 `usage_events.cost` 汇总，因此天然覆盖三类来源；工作流/协作在终态提交后触发一次预算检查。
  - `ai_power_tokens_total` / `ai_power_cost_usd_total` 增加低基数 `source` 标签。
- **前端**：用量页新增“按来源”分组与“按 API Key 对账”表。

## Consequences

- 同一 run 的成本在 run 详情、用量页、预算与 `/metrics` 使用同一批账本行，金额一致。
- 工作流节点按节点成功调用写入；provider 在返回 usage 前失败时无法精确计量，属于已知边界。
- 评测平台（answer + judge）仍把成本留在 `eval_runs` / `eval_run_items`，尚未进入统一账本；这是 S4 范围外的后续项。
- 账本保持只追加，不允许业务代码更新/删除；对账通过查询完成。
- 增加 `source` / `api_key_id` 复合索引，按来源与 Key 的查询不会全表扫描。

## Alternatives

- **每个 run 汇总一条**：丢失 provider/model 维度，无法按节点归因。
- **新表 union**：预算、指标、用量页需要同时查多表，口径更复杂。
- **只加 source 不加 Key**：无法回答“哪个 Key 花了多少钱”，不满足开放平台对账需求。