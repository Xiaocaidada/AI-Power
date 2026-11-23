# P10-S4 项目/Agent 记忆界面与权限矩阵

## 目标

把 P10 的记忆能力从“个人记忆注入”扩展到项目与 Agent 的显式授权：

- 项目可控制是否启用项目记忆、是否允许项目会话读取全局记忆、是否允许 Agent 写入项目记忆。
- Agent 可控制读取 `global/project/agent` 三类记忆、是否允许写入、写入作用域与写入方式。
- 工作流记忆节点支持项目/Agent 作用域、按标题 upsert、候选状态保存。
- Agent 获得 `memory_search` / `memory_save` 工具，并在工具执行时再次校验权限。
- 项目详情页与 Agent Studio 提供配置界面。

## 数据模型

新增两个 JSON 列（迁移 `a0b1c2d3e4f5`）：

- `projects.memory_permissions`
  - `enabled`: `bool | null`
  - `allow_global`: `bool`（默认 `true`）
  - `allow_agent_writes`: `bool`（默认 `false`）
- `custom_agents.memory_permissions`
  - `read_global` / `read_project` / `read_agent`: `bool`（默认 `true`）
  - `write`: `bool`（默认 `false`）
  - `write_scope`: `global | project | agent`（默认 `agent`）
  - `write_mode`: `candidate | create | upsert`（默认 `candidate`）

`custom_agents.memory_enabled` 仍是读取总开关；关闭时写入权限也会被归一化为 `false`。

## 权限执行点

1. `app/services/memory_permissions.py`
   - 归一化项目/Agent 权限，生成 `MemoryAccess`。
   - 空权限读集合直接跳过记忆检索。
2. `app/services/memories.py::select_memories`
   - 新增 `allowed_scopes`，在 SQL 层限制 `scope_type`。
3. `app/routers/conversations.py`
   - 项目 `enabled=false` 时关闭项目会话记忆。
   - 项目 `allow_global=false` 时剔除 `global`。
   - 自定义 Agent 按其 `read_*` 权限裁剪作用域。
   - 对话注入快照与使用记录保持 P10-S3 语义。
4. `app/tools/memory.py`
   - `memory_search` 使用 `ToolContext.memory_access`，记录 `usage_events`。
   - `memory_save` 校验写入总开关、作用域、项目 `allow_agent_writes`，支持候选/直接新增/upsert。
5. `app/services/workflow/runner.py`
   - `memory_read` 支持 `all/global/project/agent`，校验项目/Agent 属于当前工作区。
   - `memory_write` 支持项目/Agent 作用域、`status=candidate`、按标题 upsert。
   - `agent` 节点可携带 `project_id` 作为记忆工具的项目上下文。

## 界面

- 项目详情页：
  - “项目记忆”列表，支持新增/编辑/删除。
  - “记忆权限”面板：项目记忆开关（继承/开/关）、允许全局记忆、允许 Agent 写入。
- Agent Studio 配置页：
  - 记忆权限矩阵：读取全局/项目/Agent 记忆、允许写入、写入作用域、写入方式。
- 工作流节点面板：
  - 记忆读写节点新增作用域、项目、Agent 选择器；写入节点支持候选状态与按标题更新。

## 测试证据

`tests/test_p10_s4.py`：

1. 项目 `allow_global_memory=false` 时对话只注入项目记忆，不注入全局记忆。
2. Agent 权限 API 往返、`build_agent_spec` 自动加入记忆工具、`select_memories` 按读取作用域过滤。
3. `memory_save` 在 Agent 写入开关关闭时拒绝；项目禁止 Agent 写入时拒绝；候选写入落库为 `candidate`。
4. 工作流 `memory_write` 项目作用域 + `upsert` 两次运行更新同一条记忆且版本递增，`memory_read` 可读回。
5. 跨工作区项目记忆写入返回 404。

全量验证：

- `ruff check .` 通过。
- `pytest -n auto` 全量通过。
- `npm run typecheck`、`npm test`（33 个）、`npm run build` 通过。

## 边界处理

| 边界 | 状态 | 说明 |
|---|---|---|
| 项目级“是否启用记忆” | 已解决 | 项目权限 JSON + 对话注入 |
| 项目禁止读取全局记忆 | 已解决 | `allowed_scopes` 剔除 global |
| Agent 读取作用域 | 已解决 | 三类 `read_*` 权限 |
| Agent 写入权限/作用域/方式 | 已解决 | 工具层与项目层双重校验 |
| 工作流项目记忆 | 已解决 | 节点显式项目/Agent 选择 |
| 工作流候选记忆 | 已解决 | `status=candidate` |
| 记忆关系图 | 后续 P10-S5 | 已标注 |
| 冲突/重复质量分析 | 后续 P10-S6 | 已标注 |
| 模型级细粒度读取白名单 | 现有能力 | 沿用 `allow_cross_model`，不新增模型级矩阵 |