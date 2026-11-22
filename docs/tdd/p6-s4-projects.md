# P6-S4 项目与聊天工作区 — 实现证据

- **Date:** 2026-11-23
- **Scope:** S4a 项目基础、S4b 会话工作区、S4c 聊天控制。
- **计划:** [`p6-s4-plan.md`](../plan/p6-s4-plan.md)
- **API:** [`projects.md`](../api/projects.md)

## 1. 数据模型

迁移 `d2e3f4a5b6c7_p6_projects.py`（接在 `c1d2e3f4a5b6` 之后）：

- `projects`
  - `workspace_id`、`owner_user_id`
  - `name`、`description`、`instructions`
  - `default_provider_id`、`default_model`、`default_kb_id`、`default_agent`
  - `archived_at`、`created_at`、`updated_at`
- `conversations` 新增
  - `project_id`（FK projects，SET NULL）
  - `pinned`
  - `generation_settings`（JSON）
  - `updated_at`
- `messages` 新增
  - `reply_to_message_id`（FK messages，SET NULL）
- `message_feedback`
  - `message_id`、`user_id`、`rating`、`reason`
  - 唯一约束 `(message_id, user_id)`

迁移使用 `batch_alter_table` 兼容 SQLite/Postgres；历史会话回填 `updated_at = created_at`。

## 2. 后端

### S4a 项目与继承

- `app/services/projects.py`
  - 项目 CRUD、权限判断、会话计数、软归档。
- `app/routers/projects.py`
  - `/projects` 列表/创建；`/projects/{id}` 详情/更新/归档。
  - 默认 Provider/模型能力校验、KB 归属校验、`audit_logs`。
  - 成员只读：非 owner 编辑/归档返回 403。
- `POST /conversations` 支持 `project_id`：
  - 未显式提供的 provider/model/kb/agent 从项目继承。
  - 项目指令与 Prompt 模板合并后快照到 `system_prompt`。

### S4b 会话工作区

- `GET /conversations` 新增：
  - `q` 标题 + 消息内容模糊搜索（转义 `%`/`_`）。
  - `project_id`（UUID 或 `none`）、`archived`、`pinned` 过滤。
  - 置顶优先排序。
- `PATCH /conversations/{id}`：
  - 标题、置顶、项目、归档/恢复、Provider/模型、生成参数。
- `POST /conversations/batch`：
  - archive/unarchive/move，最多 100 条，原子校验。

### S4c 聊天控制

- 同一流式链路抽象为 `_start_chat_turn`：
  - `send_message` 与 `regenerate_message` 复用 RAG/Agent/Provider/配额/用量逻辑。
- `POST /conversations/{id}/messages/{message_id}/regenerate`：
  - 追加新 assistant 消息，`reply_to_message_id` 指向旧回答。
  - 旧回答不进入新请求上下文。
- 生成参数：
  - JSON 白名单 + clamp；仅合法非空值透传 `stream_chat(..., **opts)`。
  - AgentRunner 同样透传。
- 反馈：
  - `PUT/DELETE /messages/{message_id}/feedback`。
  - 会话详情按当前用户返回 `feedback`。

## 3. 前端

- `/projects`：
  - 项目卡片、创建/编辑/归档、默认模型/KB/Agent。
  - 默认模型支持平台模型与个人 Provider 模型。
- `/projects/:id`：
  - 项目指令、默认配置、项目会话列表。
- `/chat` 新会话：
  - 项目选择、“使用项目默认模型”、继承 KB/Agent 提示。
- 聊天侧栏：
  - 会话搜索、项目过滤、置顶区、普通区。
  - 行内菜单：重命名、置顶/取消、归档、移动到项目。
- `/archive`：
  - 已归档会话列表与恢复。
- 聊天页：
  - 会话设置弹窗：模型/Provider、temperature/max tokens/top P。
  - assistant 消息：重新生成、赞/踩。
  - 附件按钮占位（不触发上传）。
- 生成参数与重新生成复用现有 SSE 解析。

## 4. 验证

```text
.venv/Scripts/python.exe -m pytest tests/test_projects.py -q
9 passed

.venv/Scripts/python.exe -m pytest tests/test_projects.py tests/test_conversations.py \
  tests/test_agents.py tests/test_agent_tools.py tests/test_rag_chat.py \
  tests/test_workflows.py tests/test_migrations.py -q
affected backend tests passed

.venv/Scripts/python.exe -m pytest -q
full backend suite passed (exit 0)

.venv/Scripts/python.exe -m ruff check app tests alembic
All checks passed!

cd web && npm run typecheck
passed

cd web && npm test -- --run
24 passed

cd web && npm run build
built in 4.76s

cd web && npm run test:e2e
5 passed（新增项目创建流程）

docker compose up -d --build api worker web
alembic_version = d2e3f4a5b6c7；projects / message_feedback 表存在
/readyz → database ok, redis ok
真实 PostgreSQL 冒烟（临时用户，已清理）：
register 201 → project 201 → conversation 201（auto/auto，继承 project_id）
PATCH 置顶/改名 200 → q=smoke 命中 → batch archive 200 → archived=true 命中 → restore 200
```

## 5. 已知边界

- 附件只做占位，不接上传/多模态。
- 重新生成追加新回答，不做“多版本切换/覆盖”。
- 会话搜索使用 `ILIKE` + limit；数据量增大后再加 pg_trgm GIN 索引。
- 项目只保存一个默认 KB；多 KB 关联后补。
- 项目共享沿用现有 workspace 会话可见性；未新增“项目内私有会话”。
- 项目列表暂不提供归档项目恢复 UI（API 支持 `archived` 查询与 `PATCH archived=false`）。