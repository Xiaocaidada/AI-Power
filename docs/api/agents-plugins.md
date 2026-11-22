# Agent 与插件 API

## 1. Agent 广场

### `GET /agents?q=&category=`

返回内置 Agent + 当前用户可见的自定义 Agent（自己的私有 Agent + workspace 共享 Agent）。

```json
[
  {
    "id": "builtin:supervisor",
    "name": "Supervisor",
    "builtin": true,
    "owned": false,
    "tools": ["delegate_to_agent"],
    "plugin_ids": [],
    "visibility": "shared",
    "conversation_count": 0
  }
]
```

内置 ID：`builtin:supervisor`、`builtin:retrieval`、`builtin:math`。

### `GET /agents/{id}`

自定义 Agent 返回 `owned`；私有 Agent 对其他用户 `404`。

### `POST /agents`

```json
{
  "name": "Pirate",
  "description": "Talks like a pirate",
  "instructions": "You are a pirate. Answer briefly.",
  "category": "writing",
  "default_provider_id": "fake",
  "default_model": "fake-model",
  "default_kb_id": null,
  "tools": ["calculator"],
  "plugin_ids": [],
  "visibility": "private"
}
```

- `tools` 仅允许 `kb_search`、`current_time`、`calculator`。
- 默认 Provider/模型需存在且具备 `tools` 能力。
- `default_kb_id` 必须属于当前 workspace。
- `plugin_ids` 必须是当前 workspace 已启用的插件。
- 同名 Agent 返回 `422`。

### `PATCH /agents/{id}` / `DELETE /agents/{id}`

创建者或 workspace owner 可编辑/归档；其他成员 `403`。删除为软归档。

### Agent 会话

`POST /conversations`：

```json
{ "custom_agent_id": "…", "plugin_ids": ["…"], "confirmed_plugin_ids": ["…"] }
```

- 使用 Agent 默认 Provider/模型/KB（请求显式字段优先）。
- `agent=true`；自定义 Agent 的 `instructions` 作为根 Agent 系统提示。
- 配置默认 KB 时自动启用 `kb_search` 工具。
- 省略 `plugin_ids` 时继承 Agent 的插件列表。

历史记录：`GET /conversations?custom_agent_id=…`。

## 2. 插件市场

### `GET /plugins`

返回启用的插件定义 + 当前 workspace 配置状态：

```json
[
  {
    "id": "…",
    "slug": "weather",
    "name": "Weather",
    "sensitive": false,
    "enabled": true,
    "configured": true,
    "config_enabled": true,
    "credential_hint": "••••abcd",
    "status": "configured"
  }
]
```

### `PATCH /plugins/{plugin_id}`

仅 workspace owner：

```json
{ "enabled": true, "credential": "optional-token" }
```

- `credential=null` 表示不修改；空字符串清除。
- 凭据 Fernet 加密，接口只返回掩码提示。

### `GET /plugins/calls?conversation_id=`

最近 100 条插件调用记录（status、请求/响应摘要、耗时、错误码）。

## 3. 会话插件

### `GET /conversations/{id}/plugins`

返回会话已启用插件与 `confirmed_at`。

### `PUT /conversations/{id}/plugins`

```json
{ "plugin_ids": ["…"] }
```

- 只有 Agent 模式会话可启用插件，否则 `422 agent_required`。
- 插件必须在 workspace 已配置且启用。

### `POST /conversations/{id}/plugins/{plugin_id}/confirm`

确认敏感插件；`DELETE` 取消确认。

敏感插件未确认时，Agent 调用会得到工具错误 `plugin_confirmation_required`，不会发起 HTTP 请求。

## 4. 管理员插件定义

`/admin/plugins`（仅 admin，其他用户 404）：

- `GET` 列出全部定义
- `POST` 创建
- `PATCH` 更新
- `DELETE` 删除

```json
{
  "slug": "weather",
  "name": "Weather",
  "description": "Looks up weather",
  "category": "data",
  "endpoint_url": "https://example.com/weather",
  "method": "POST",
  "auth_type": "bearer",
  "parameters": {
    "type": "object",
    "properties": { "query": { "type": "string" } },
    "required": ["query"]
  },
  "sensitive": false,
  "enabled": true,
  "timeout_seconds": 10
}
```

参数 Schema 限制：

- `type=object`，最多 10 个属性。
- 属性类型仅 `string|number|integer|boolean`。
- 属性名需为合法标识符且非 Python 关键字。

## 5. 安全约束

- 插件 URL 仅 `http(s)`；非 dev 强制 HTTPS。
- 创建/更新与每次调用都做 DNS 解析与私网/回环/链路本地/保留地址拒绝。
- 可选 `PLUGIN_ALLOWED_HOSTS` 主机白名单。
- 禁止重定向；超时取 `min(插件定义, PLUGIN_TIMEOUT_SECONDS)`。
- 响应按 `PLUGIN_MAX_RESPONSE_CHARS` 截断。
- 凭据不返回、不写日志、不写调用摘要。
- Agent/插件跨 workspace 一律 `404`。