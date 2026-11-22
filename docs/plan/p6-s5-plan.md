# P6-S5 Agent 与插件 — 实施规划

- **Date:** 2026-11-23
- **Status:** 已完成
- **上级规划:** [`p6-plan.md`](./p6-plan.md)
- **API:** [`agents-plugins.md`](../api/agents-plugins.md)

## 1. 切片

1. **S5a Agent 平台**：预设 Agent 广场、自定义 Agent CRUD、默认模型/KB、工具与插件、私有/共享。
2. **S5b Agent 会话**：使用指定 Agent 创建会话、执行过程复用现有 SSE/trace/usage、历史记录。
3. **S5c 插件后端**：管理员定义 HTTP 工具、workspace 配置、会话启用、敏感确认、调用记录。
4. **S5d 插件前端**：插件广场/配置、管理员定义管理、新会话选择与敏感确认。

## 2. 决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | 自定义 Agent 为 workspace 级，`private`/`shared` | 与项目/会话的 workspace 共享模型一致 |
| 2 | 创建者或 workspace owner 可编辑/归档 | 防止成员修改共享 Agent |
| 3 | 内置 Agent 只读 | 保持 supervisor/retrieval/math 行为稳定 |
| 4 | 自定义 Agent 作为根 Agent，不再嵌套委派 | 简单、可预测；需要编排时用内置 supervisor |
| 5 | Agent 可用工具限制为 `kb_search`/`current_time`/`calculator` | 不允许用户注入任意工具 |
| 6 | 配置默认 KB 时自动加入 `kb_search` 工具 | 避免“配了 KB 但 Agent 不会检索” |
| 7 | 插件定义仅管理员创建 | 外部 HTTP 工具是平台级安全面 |
| 8 | Workspace 仅 owner 可配置插件凭据 | 防止成员替换凭据 |
| 9 | 插件按会话启用；敏感插件需显式确认 | 最小授权，敏感外部操作可审计 |
| 10 | 插件仅支持 GET/POST、禁重定向、超时/响应上限 | 降低 SSRF 与资源消耗 |
| 11 | `PLUGIN_ALLOWED_HOSTS` 可选白名单；始终做 DNS/私网校验 | 平台可控的出站边界 |
| 12 | 插件只进入 Agent 模式 | 普通对话没有工具循环 |

## 3. 数据模型

- `custom_agents`
  - workspace/owner、名称、描述、角色指令
  - 默认 provider/model/KB、`tools`、`plugin_ids`
  - `visibility`（private/shared）、`enabled`、`archived_at`
- `conversations.custom_agent_id`
- `plugin_definitions`（管理员）
  - slug、名称、描述、分类、文档
  - endpoint、method、auth_type、parameters JSON Schema
  - sensitive、enabled、timeout
- `plugin_configs`（workspace）
  - enabled、加密凭据/提示、status
- `conversation_plugins`
  - conversation/plugin、`confirmed_at`
- `plugin_calls`
  - workspace/conversation/plugin、status、请求/响应摘要、耗时、错误码

迁移：`e3f4a5b6c7d8_p6_agents_plugins.py`。

## 4. 接口

- `/agents`：列表（内置 + 可访问自定义）、创建
- `/agents/{id}`：详情、更新、归档
- `/conversations?custom_agent_id=`
- `/plugins`：workspace 市场、配置
- `/plugins/calls`：调用记录
- `/admin/plugins`：定义 CRUD
- `GET/PUT /conversations/{id}/plugins`
- `POST/DELETE /conversations/{id}/plugins/{plugin_id}/confirm`

## 5. 安全

- Agent/插件跨 workspace `404`；私有 Agent 对非 owner `404`。
- 插件 URL：http(s)、非 dev 强制 HTTPS、DNS 解析、私网/回环/链路本地/保留地址拒绝、可选主机白名单。
- 禁止重定向；超时取插件定义与全局上限的较小值；响应截断。
- 凭据 Fernet 加密、只返回掩码提示；不写日志/调用摘要。
- 敏感插件未确认时工具返回 `plugin_confirmation_required`，不发起请求。
- 插件调用写入 `plugin_calls`，仅保留截断摘要。

## 6. 边界

- 不做用户上传可执行插件代码。
- 不做 OAuth/多步鉴权；v1 只有 none/bearer。
- 不做插件健康检查/自动重试。
- 附件/多模态仍按 P6-B 单独评估。
- 插件工具仅在 Agent 模式可用。