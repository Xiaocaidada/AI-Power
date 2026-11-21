# ADR-0014: 成本按写入时价格快照

- **Status:** Accepted
- **Date:** 2026-11-21
- **Context:** `model_catalog` 已有价格，但用量事件只存 token。若按“查询时现价”计算，调价会让历史成本漂移，无法对账。

## Decision

- 助手消息 finalize 时，按 `(provider_id, model)` 查 `model_catalog`，把 `input_price` / `output_price` 写入该条 `usage_events`。
- `cost = prompt_tokens/1e6*input_price + completion_tokens/1e6*output_price`，保留 6 位小数。
- 查不到模型 → `cost=0`、`unpriced=true`；NULL usage → token 按 0、`unpriced=false`（模型本身有价）。
- `GET /usage/cost` 与 `/admin/usage` 直接 `SUM(cost)`，不再 join 价格。
- 迁移把历史事件标记为 `unpriced=true`、成本 0；如需回填需单独脚本。

## Consequences

- 历史成本稳定，调价只影响新请求。
- 使用 `Float` 而非 `Numeric`：6 位小数只适合演示，不用于真实结算。
- 单一 USD 口径；无税率、折扣、多币种。
- 只按消息维度拆分，未按 Key/用户/工具细化。

## Alternatives

- **查询时 join 现价**：历史漂移，不可对账。
- **`Numeric` + 货币表**：更正确但超出 P3 演示范围。
- **异步成本重算**：增加队列与一致性复杂度，当前不需要。