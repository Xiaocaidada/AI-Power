# P10-S3 记忆检索与注入

## 统一选择

`app/services/memories.py` 新增：

- `select_memories(...) -> MemorySelection`
- `MemorySelection.block`：注入文本
- `MemorySelection.items`：`SelectedMemory(memory, score, injected_chars)`
- `MemorySelection.refs()`：消息快照结构

选择条件：

- 状态 `active`、`enabled=true`、未过期。
- 作用域：global + 当前 Agent（若传入）+ 当前项目（若传入）。
- `excluded_ids` 排除。
- `allow_cross_model=false` 时，提取记忆若带来源 `provider_id/model` 且与当前模型不同则跳过；
  无来源信息的手动记忆仍允许。
- 排序：向量相似度（可用时）+ 重要性 + 使用次数 + 置顶/收藏 + 时效；
  无向量时按词法匹配 + 基础分。
- `max_chars` 包含头部与每条记忆，按预算截断。

`memory_context` 保留为 `select_memories().block` 的兼容包装，工作流节点继续可用。

## 对话注入

- 仅当记忆中心 `enabled=true` 且满足以下条件：
  - 会话 `memory_enabled` 未显式为 false；
  - 自定义 Agent 的 `memory_enabled` 未关闭。
- 注入位置：
  - 普通对话：合并到 system prompt（RAG 或无 RAG 均适用）。
  - Agent 对话：追加到自定义 Agent 或内置 supervisor 的 system prompt。
- 使用限制来自 `memory_settings.max_inject_items/max_inject_chars`。
- 每次注入写 `memory_usage_events`：
  `context_type=chat|agent`、`context_id=assistant_message_id`、provider/model、
  相关性、注入字符。
- 助手消息 `memory_refs` 保存本次注入的记忆快照（id/title/category/scope/relevance/chars）。
- 对话 PATCH 支持：
  - `memory_enabled`（true/false/null 跟随全局）
  - `excluded_memory_ids`（最多 50）
- 聊天设置对话框新增记忆开关与排除记忆多选；消息“运行详情”展示本次使用记忆。

## 工作流

- `memory_read`：使用统一选择；写 `context_type=workflow` 使用记录；记忆中心关闭时返回
  `(memory disabled)`。
- `memory_write`：记忆中心关闭时返回 `memory_disabled`。
- 工作流无 `project_id`，项目作用域注入留待 P10-S4（已标注）。

## 权限

- `allow_cross_model` 控制跨模型读取提取记忆。
- `allow_agent_extract` 关闭时，Agent 会话不提取（默认关闭）。
- `allow_project_extract` 关闭时，项目会话不提取。
- Agent 写入记忆的细粒度授权仍属于 P10-S4 计划。

## 验证

- `tests/test_p10_s3.py`：
  - 普通对话注入记忆、写使用记录、消息快照。
  - `memory_enabled=false` 不注入。
  - 排除列表生效。
  - 项目/全局作用域过滤、跨模型过滤。
  - 字符预算。
- `tests/test_p8_s5c.py` 记忆节点测试已按“默认关闭”语义先开启记忆中心。
- 全量 `ruff`/`pytest`、前端 typecheck/build、E2E 通过。

## 后续计划

- 工作流项目作用域注入：P10-S4。
- Agent 记忆写工具与细粒度写权限：P10-S4。
- 夜间 consolidation、语义冲突：P10-S6。