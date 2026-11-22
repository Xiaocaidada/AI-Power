# P6-S5 Agent 与插件 — 实现证据

- **Date:** 2026-11-23
- **Scope:** Agent 广场/自定义 Agent、Agent 会话、插件 v1、敏感确认、调用记录。
- **计划:** [`p6-s5-plan.md`](../plan/p6-s5-plan.md)
- **API:** [`agents-plugins.md`](../api/agents-plugins.md)

## 1. 数据模型

迁移 `e3f4a5b6c7d8_p6_agents_plugins.py`：

- `custom_agents`
  - workspace/owner、名称、描述、指令、分类
  - 默认 provider/model/KB、`tools`、`plugin_ids`
  - `visibility`、`enabled`、`archived_at`
  - 唯一约束 `(workspace_id, name)`
- `conversations.custom_agent_id`
- `plugin_definitions`
  - slug/名称/描述/分类/文档
  - endpoint、method、auth_type、parameters
  - sensitive、enabled、timeout
- `plugin_configs`
  - workspace/plugin、enabled、加密凭据、状态
- `conversation_plugins`
  - conversation/plugin、`confirmed_at`
- `plugin_calls`
  - workspace/conversation/plugin、status、请求/响应摘要、耗时

## 2. 后端

### Agent

- `app/services/custom_agents.py`
  - 内置 Agent 目录（supervisor/retrieval/math）
  - 私有/共享可见性、owner 或 workspace owner 编辑
  - 工具白名单、默认 KB 自动加入 `kb_search`
  - 构造根 `AgentSpec`
- `app/routers/agents.py`
  - `GET/POST /agents`、`GET/PATCH/DELETE /agents/{id}`
  - Provider/模型能力校验、KB 归属、插件配置校验
  - 变更写 `audit_logs`
- 会话集成：
  - `POST /conversations` 支持 `custom_agent_id`，继承 Agent 默认配置。
  - `_start_chat_turn` 构建自定义根 Agent，合并插件工具。
  - 复用 SSE/trace/usage；消息级 provider/model 保持不变。

### 插件

- `app/services/plugins.py`
  - 定义 CRUD、workspace 配置、会话插件、敏感确认。
  - 参数 Schema 限制（最多 10 个原始类型参数）。
  - SSRF：URL 形状、HTTPS（非 dev）、主机白名单、DNS、私网/回环/保留地址。
  - HTTP：GET/POST、禁重定向、超时、响应截断。
  - 凭据 Fernet 加密/解密、掩码提示。
  - 每次调用写 `plugin_calls`（截断摘要，不含凭据）。
- `app/routers/plugins.py`
  - `/plugins` 市场、`PATCH /plugins/{id}`（仅 workspace owner）
  - `/plugins/calls`
  - `/admin/plugins` 定义 CRUD（仅 admin）
- 会话插件：
  - `GET/PUT /conversations/{id}/plugins`
  - `POST/DELETE /conversations/{id}/plugins/{plugin_id}/confirm`
  - 非 Agent 模式启用插件返回 `422 agent_required`
- 工具集成：
  - 只有会话启用 + workspace 配置启用的插件才进入 Agent 工具。
  - 敏感插件未确认时返回 `plugin_confirmation_required`，不发起请求。

## 3. 前端

- `/agents`：Agent 广场、搜索/分类、创建/编辑/归档、立即体验。
- `/agents/:id`：指令、默认配置、插件、执行记录。
- `/plugins`：插件市场、搜索/分类、配置（启用/凭据）、调用记录。
- `/admin/plugins`：管理员定义 CRUD（参数 JSON Schema）。
- 新会话：
  - 选择自定义 Agent；
  - 选择已配置插件；
  - 敏感插件需勾选确认。
- 会话设置：
  - 调整插件集合；
  - 敏感插件单独确认。
- 侧栏新增 Agent / 插件入口；管理员新增插件管理。

## 4. 验证

```text
.venv/Scripts/python.exe -m pytest tests/test_agents_plugins.py -q
7 passed

.venv/Scripts/python.exe -m pytest tests/test_agents_plugins.py tests/test_migrations.py \
  tests/test_conversations.py tests/test_projects.py -q
39 passed

.venv/Scripts/python.exe -m pytest -q
full backend suite passed (exit 0)

.venv/Scripts/python.exe -m ruff check app tests alembic
All checks passed!

cd web && npm run typecheck
passed

cd web && npm test -- --run
24 passed

cd web && npm run build
built in 4.28s

cd web && npm run test:e2e
6 passed（新增 Agent 创建流程）

docker compose up -d --build api worker web
alembic_version = e3f4a5b6c7d8；custom_agents / plugin_* / conversation_plugins 表存在
/readyz → database ok, redis ok

真实 PostgreSQL 冒烟（临时数据已清理）：
custom agent 201 → conversation 201（agent=true，继承 auto/auto，custom_agent_id 正确）
conversation?custom_agent_id= → 1 条
/admin/plugins 私网 URL → 422
/admin/plugins 公网定义 → 201；workspace 配置 200；带插件会话 201；conversation plugins = 1
```

## 5. 已知边界

- 插件仅支持 GET/POST + none/bearer 鉴权，不支持用户上传代码。
- 不做插件健康检查/自动重试/OAuth。
- 敏感确认按会话生效，不按单次调用生效。
- 插件仅 Agent 模式可用。
- SSRF 校验发生在请求前；未做 IP 固定连接，DNS rebinding 仍属残余风险。
- 附件/多模态仍按 P6-B 单独评估。