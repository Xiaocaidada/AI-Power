# P12-S1 统一模式与能力框架

日期：2026-11-24
状态：已完成（框架切片）

## 目标

在不改变现有聊天执行路径的前提下，建立网页对话的统一模式、能力声明与前后端门控：

- 会话保存默认模式，消息保存本次模式与思考等级。
- 模型声明可用的思考等级；不支持的等级仍展示，但不可选，后端二次校验。
- 为 P12-S2 网页搜索、P12-S3 学习模式、P12-S6 深度研究预留稳定的数据与 API 契约。

## 实现

### 数据

- `conversations.default_mode`：`chat|web_search|deep_research|study|agent`，默认 `chat`。
- `messages.mode`：本条消息使用的模式，默认 `chat`。
- `messages.mode_meta`：白名单 JSON，当前包含 `thinking_level`、`search_provider_id`、
  `research_task_id`、`study_session_id`、`agent_task_id`、`web_search_enabled`。
- `provider_models.reasoning_levels`、`model_catalog.reasoning_levels`：显式思考等级声明。
- 迁移：`d5e6f7a8b9c0_p12_s1_chat_modes.py`。

### 服务与 API

- `app/services/chat_modes.py`：
  - 模式目录与实现状态：`chat`、`agent` 可执行；`web_search`、`deep_research`、`study`
    仅持久化，发送返回 `422 mode_not_available`。
  - `thinking_level` 默认 `standard`；显式声明优先，其次 `reasoning` 能力标签推导
    `standard|deep`，无声明时仅 `standard`。
  - `validate_turn_mode` 校验模式、Agent 一致性、tools 能力与思考等级。
  - `resolve_model_capabilities` 解析个人 Provider 模型或平台模型目录。
- `GET /chat/modes`：模式目录与全部思考等级。
- `GET /chat/capabilities`：指定 Provider/模型的思考等级可用性。
- `POST /conversations`、`PATCH /conversations/{id}` 支持 `mode` / `default_mode`。
- `POST /conversations/{id}/messages` 支持 `mode` 与 `mode_meta`；SSE `meta` 增量返回
  `mode`、`mode_meta`。
- `/models`、`/provider-configs/models` 返回 `reasoning_levels`。

### 前端

- 新建会话与既有会话共用 `ModeSelector`；已规划但未实现的模式显示“即将支持”。
- 高级设置与会话输入区展示全部思考等级；不支持的等级置灰不可选。
- 选择未实现模式时，会话仍会创建并保存模式，但不会自动发送；发送按钮禁用并展示提示。
- 消息运行详情展示模式与思考等级。

## 测试

- 后端：`tests/test_p12_s1_chat_modes.py` 覆盖模式目录、默认/显式模式、未实现模式 422、
  非法模式、Agent 一致性、消息元数据、SSE meta、思考等级 422、跨工作区 404、
  个人模型声明的思考等级与能力回退。
- 前端：`web/src/lib/chatModes.test.ts` 覆盖能力推导与等级钳制。
- 全量验证：`ruff check`、`pytest -n auto`、`npm run typecheck`、`npm test -- --run`、
  `npm run build`。

## 边界

已解决：

- 旧会话默认 `chat`；旧消息默认 `chat` 与 `standard`。
- 模式与消息元数据持久化，前端可切换，后端类型化校验。
- 能力展示与不可选状态由后端声明驱动，后端再次校验，无静默降级。
- Agent 会话与 Agent 模式保持一致性；普通 Agent 会话切换模式时拒绝有插件的冲突状态。

后续切片：

- `web_search` 执行与来源引用：P12-S2。
- `study` 执行、测验与掌握度：P12-S3。
- `deep_research` 长任务与报告：P12-S5/S6。
- 思考等级映射到 Provider 真实参数：P12-S8；S1 只记录、展示与校验，不改变模型调用参数。
- `auto` 路由在 S1 只能使用 `standard`，因为具体模型在路由后才确定；P12-S8 将按实际路由模型
  重新校验。
- 平台模型的显式逐级声明当前通过 `model_catalog.reasoning_levels` 或 `reasoning` 标签生效，
  暂无管理员编辑界面；P12-S8 随思考模式配置补充。

明确不做（真实外部集成）：

- 网页搜索、图片生成、语音、OAuth 应用：S1 不触发任何外部服务，不伪造成功。

需要用户决策：

- 无。