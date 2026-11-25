# Provider 模型动态能力配置（上下文 / 工具 / 思考）

日期：2026-11-25
状态：已实现，待部署

## 策略

模型能力不是平台能可靠自动探测的：OpenAI-compatible `/v1/models` 通常只返回模型 id，不返回上下文长度、工具调用或思考等级。改为由用户为自己的 Provider 模型配置：

- 上下文窗口 `context_window`（tokens，0 表示未知）
- 最大输出 `max_output`（tokens，可选）
- 标签类型 `capabilities`（chat / stream / tools / vision / file / structured / reasoning / long_context / embedding / rerank）
- 思考配置 `thinking_config`：用户自定义等级列表，每项为 `{id, label}`

系统按配置运行，不再依赖名称推断。思考等级不再是固定的 fast / standard / deep：`id` 会作为 `reasoning_effort` 原样发送给模型服务（内置 `fast`→`low`、`standard`→不发送、`deep`→`high` 保持兼容），`label` 只用于界面显示。旧数据只写 `reasoning_levels` 时，后端自动回填为空标签的 `thinking_config`。

## 数据与 API

- `provider_models` 新增 `context_window`、`max_output` 列（迁移 `d1e2f3a4b5c7`）和 `thinking_config` 列（迁移 `e4f5a6b7c8d9`）。
- `ProviderModelCreate` / `ProviderModelUpdate` / `ProviderModelOut` / `PersonalModelOut` 增加对应字段。
- `PATCH /provider-configs/{id}/models/{model_id}` 支持更新上下文、输出、能力、标签和思考配置。
- `thinking_config` 最多 10 项；等级值限定为小写字母、数字与 `._-`；`reasoning_levels` 由 `thinking_config` 派生以兼容旧读取方。
- 显式更新能力后 `source="manual"`，同步不会覆盖用户配置。

## 前端

`/settings/providers` 的模型行新增“模型能力配置”：

- 上下文窗口（tokens）
- 最大输出（tokens）
- 标签类型：全部能力标签多选
- 思考配置：可添加/删除等级行，每行填写等级值与显示名称

保存后刷新 Provider 模型与个人模型查询，聊天/Agent 立即按新配置工作；对话页的思考选择器只展示该模型配置的等级，并显示自定义名称。

## 运行时

新增 `app/services/context_budget.py`：

- `context_window=0`：保持旧的固定策略，历史取最近 12 条，RAG 使用全局 `RETRIEVAL_MAX_CONTEXT_CHARS`。
- `context_window>0`：
  - 输入预算 = `context_window - max_output/生成 max_tokens - 安全余量`
  - 历史消息按约 2 字符/token 估算，从最新消息向前保留，最多 60 条。
  - RAG 上下文上限取全局上限与剩余输入预算的较小值。
- 工具调用能力继续控制 Agent/Agent 任务/Agent Studio 的可用性。
- `reasoning_levels`（由 `thinking_config` 派生）继续控制思考等级选择与后端 422 校验。
- 自定义等级（如 `minimal` / `medium` / `xhigh`）直接作为 `reasoning_effort` 传递；研究任务与 Agent 任务复用同一映射。
- 模型没有配置等级时，带 `reasoning` 标签的模型仍回退为 standard / deep，其余仅 standard。

## 测试

- `tests/test_context_budget.py`：未知上下文、大窗口、小窗口裁剪、RAG 预算收缩。
- `tests/test_provider_configs.py`：上下文/输出/思考等级创建与更新、GLM 工具能力、`thinking_config` 标签回读。
- `tests/test_p12_s8_thinking.py`：自定义等级作为 `reasoning_effort` 发送、未配置等级返回 422。
- `web/src/lib/chatModes.test.ts`：自定义等级顺序、显示名称与回退。
- 全量后端 `pytest -n auto` 通过。
- 前端 `typecheck`、Vitest、生产构建通过。

## 边界

- 没有真实 tokenizer，使用保守字符估算（约 2 字符/token）；不会精确等于厂商计费 token。
- 最多保留 60 条历史，避免超长会话带来无界请求。
- `max_output` 用于预算预留，不会自动改写用户显式设置的 `max_tokens`。
- RAG 仍受全局 `RETRIEVAL_MAX_CONTEXT_CHARS` 上限约束，不会因为模型窗口大而无限扩大。
- 平台模型目录的 `context_window` 同样参与预算；为 0 时回退固定策略。
- 思考配置目前只映射 OpenAI-compatible 的 `reasoning_effort`；`enable_thinking`、`thinking_budget` 等厂商专有参数尚未支持。
- 自定义等级值必须是模型服务实际接受的 `reasoning_effort` 值，平台不做语义校验（只校验字符格式）。