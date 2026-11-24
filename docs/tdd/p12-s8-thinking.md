# P12-S8 思考模式真实生效

日期：2026-11-24
状态：已完成

## 目标

把已有思考等级从“记录/校验”升级为真实 Provider 参数映射，并保持不支持等级的前后端门控。

## 实现

### 能力声明

- 继续使用 `provider_models.reasoning_levels` 与 `model_catalog.reasoning_levels`。
- 未声明等级的模型：只支持 `standard`。
- 声明 `reasoning` 但未显式等级：支持 `standard, deep`。
- 显式声明：按声明集合，顺序固定 `fast, standard, deep`。
- `GET /chat/capabilities` 与 `/provider-configs/models` 继续返回真实可用等级。

### 参数映射

`app/services/chat_modes.py`：

| 等级 | Provider 参数 |
|---|---|
| `fast` | `reasoning_effort="low"` |
| `standard` | 不发送覆盖参数 |
| `deep` | `reasoning_effort="high"` |

该映射适用于 OpenAI-compatible 推理模型；`standard` 不发送参数，避免改变只提供默认行为的模型。

### 生效路径

- 普通聊天：`_start_chat_turn` 在模式校验后合并 `thinking_provider_opts` 到流式请求参数。
- 网页搜索：沿用同一 `opts`。
- 深度研究：计划生成、步骤摘要、交叉验证、追问、局部重生成均携带映射参数。
- Agent 任务：计划生成与每轮工具决策均携带映射参数。
- 消息继续持久化 `mode_meta.thinking_level`；历史消息可查看当次等级。

### 不支持等级

- 前端：所有等级都展示，不支持的置灰不可选。
- 切换模型导致当前等级不再支持时，自动回到 `standard`，并显示可见提示 `thinkingAdjusted`，不静默发送。
- 后端：`ensure_thinking_supported` 再次校验；仍返回 `422 thinking_level_unsupported`。

## 测试

`tests/test_p12_s8_thinking.py`：

- `fast/standard/deep` 参数映射。
- 不支持等级抛 `thinking_level_unsupported`，不降级。
- 声明 `standard, deep` 的模型在 `deep` 时发送 `reasoning_effort="high"`。
- 同一模型请求 `fast` 返回 422，消息不落库。

前端：`chatModes.test.ts` 覆盖等级选择；`npm run typecheck` / `npm test` / `npm run build` 通过。

## 边界

已解决：

- 不同模型展示不同可用等级。
- 不支持等级不会被静默降级。
- 历史消息保留当次等级。
- 不展示隐藏推理链，只展示整理后的回答与等级标签。

后续/边界：

- 仅使用 OpenAI-compatible `reasoning_effort` 映射；Anthropic `thinking.budget_tokens`、Gemini 等原生参数不在当前 Provider 抽象内。
- `auto` 在路由解析出具体模型前仍只支持 `standard`；解析后按该模型声明执行。
- 不解析或展示模型内部推理内容。