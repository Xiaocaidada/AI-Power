# P12-S7 Agent 执行升级

日期：2026-11-24
状态：已完成（可恢复 Agent 任务 MVP）

## 目标

在长任务运行层上提供可确认计划、多步骤工具调用时间线、高风险审批、暂停/继续与失败重试的 Agent 任务。

## 实现

### 任务模型

复用 `chat_tasks`，新增 `kind="agent"`：

- `input`：provider/model、thinking_level、goal、agent_id、plugin_ids、kb_ids、tools、max_steps、language。
- `plan`：`confirmed`、步骤数组、`approvals`。
- `checkpoint`：`exchanges`、`tool_records`、`llm_calls`、`tool_calls`、`tokens`、`plan_cursor`、`pending_approval`、`pending_tool`。
- `result`：`text`、`artifacts`（代码块）、`tool_records`、`message_id`、`token_usage`。

### 工具与风险

- 工具来自内置注册表（`kb_search`/`current_time`/`calculator`/memory/project files）、绑定插件的 `build_plugin_tools_for_ids`、自定义 Agent 的 MCP 工具。
- `ToolSpec` 新增 `risk` 字段；敏感插件在注册时标记 `risk="high"`。
- 高风险工具执行前必须创建审批请求并进入 `waiting_approval`，未审批不执行。

### 流程

1. `POST /agent-tasks`：生成 3–N 步计划，状态 `waiting_approval`。
2. 计划编辑/确认后入队。
3. Worker 循环：
   - 调用模型，使用既有 JSON 协议（`tool` / `final`）；
   - 普通工具立即执行并追加 `agent_tool_call` / `agent_tool_result`；
   - 高风险工具写入 `pending_approval` + `pending_tool`，追加 `approval_required`，退出等待。
4. 审批：
   - `approve`：记录审批结果，任务重新入队，恢复时先执行被挂起的工具；
   - `reject`：不执行工具，把拒绝原因作为观测返回模型继续；
   - 等待期间可直接取消任务。
5. 最终答案写入 `result.text`，代码块提取为 artifacts，追加 `agent_artifact_ready`。
6. 绑定会话时自动追加 `agent` 模式助手消息。

### API

- `POST /agent-tasks`（201）
- `GET /agent-tasks`
- `GET /agent-tasks/{id}`
- `PATCH /agent-tasks/{id}/plan`
- `POST /agent-tasks/{id}/confirm`
- `POST /agent-tasks/{id}/approval`
- `POST /agent-tasks/{id}/save-to-knowledge`
- 控制/事件复用 `/chat-tasks/{id}/pause|resume|cancel|retry|events`

### 限制与恢复

- LLM 步数 `AGENT_TASK_MAX_STEPS`（10）→ `agent_step_limit`。
- 工具调用数 `AGENT_TASK_MAX_TOOL_CALLS`（15）→ `agent_tool_limit`。
- Token 上限 `AGENT_TASK_MAX_TOTAL_TOKENS`（150000）→ `agent_token_limit`。
- `exchanges` 与 `pending_tool` 持久化，失败重试从检查点继续，不重复已完成工具。
- 暂停/取消在循环边界生效，沿用长任务租约与事件回放。

## 测试

`tests/test_p12_s7_agent_tasks.py`：

- 高风险工具先进入 `waiting_approval`，审批前不执行。
- 批准后执行工具、完成最终答案并提取代码 artifact。
- 拒绝后不执行工具，拒绝原因写入 `tool_records`，任务可继续完成。
- 审批/工具事件在时间线中可回放。
- 计划确认、暂停、继续、取消幂等。
- 计划未确认不执行。

## 边界

已解决：

- 未审批的高风险操作绝不执行。
- 审批可批准、拒绝、取消。
- 工具调用与结果可追溯（事件 + checkpoint + result）。
- 失败不丢已完成交换与工具记录。
- 任务成果可保存到知识库。

后续切片/边界：

- 风险分类目前只来自敏感插件定义；MCP 工具默认 `risk="low"`，无法自动判断远端工具是否有副作用。需要为 MCP/插件增加显式风险声明后再纳入审批。
- 纯内部工具（kb_search/current_time/calculator/memory）不打断审批。
- 计划步骤目前是展示/进度语义，工具调用是自适应的，不会严格按计划逐步锁定。
- 任务级成本预算/审批策略（记住本次选择、按工具白名单放行）未实现。

明确不做（真实外部集成）：

- 不执行未配置/未授权的支付、发布、删除、发送操作。
- 不伪造工具结果。