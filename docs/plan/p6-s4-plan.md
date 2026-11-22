# P6-S4 项目与聊天工作区 — 实施规划

- **Date:** 2026-11-23
- **Status:** 已完成（2026-11-23）
- **上级规划:** [`p6-plan.md`](./p6-plan.md)
- **前置:** P6-S1 Provider Hub、S2 双模型广场、S3 门户与内容已完成

## 0. 结论摘要

S4 拆成三个可独立验收的切片：

1. **S4a 项目基础**：`projects` 数据模型、CRUD、项目详情页、项目内新会话继承默认配置。
2. **S4b 会话工作区**：搜索、置顶、重命名、归档/恢复、移动项目、批量操作。
3. **S4c 聊天控制**：模型/Provider 切换、生成参数、重新生成、消息反馈、附件入口占位。

不在 S4 做：真实附件上传/多模态、项目级文件中心、多人实时协作、会话全文搜索引擎。

## 1. 现状与约束

- `conversations` 已有 `workspace_id`、`user_id`、`title`、`provider_id`、`model`、`kb_id`、`system_prompt`、`agent`、`archived_at`。
- 会话列表当前按 `workspace_id` 过滤，workspace 成员可见全部会话；`DELETE /conversations/{id}` 实际是软归档。
- `GET /conversations` 只支持 `limit`/`before`，没有搜索、项目、置顶、归档过滤。
- 聊天发送是 SSE，消息级已记录实际 `provider_id`/`model`；`stream_chat(messages, model, **opts)` 可直接透传生成参数。
- 工作流/协作/评测不在 S4 改动范围。

## 2. 设计决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | 项目是 **workspace 级**资源，成员可见可用 | 与现有会话共享模型一致，避免引入第二套权限 |
| 2 | 项目创建者或 workspace owner 可编辑/删除，其他成员只读使用 | 防止成员误改公共默认配置 |
| 3 | 项目只保存 **一个默认 KB**（`default_kb_id`） | 会话当前只支持一个 KB；多 KB 关联等有真实消费方再加 |
| 4 | 项目指令在 **创建会话时快照** 到 `system_prompt` | 项目后续修改不改写历史会话 |
| 5 | 生成参数存 `conversations.generation_settings` JSON | 避免为 temperature/top_p 等逐列迁移；服务端白名单校验 |
| 6 | 重新生成 **追加新的 assistant 消息**，保留旧回答 | 可审计、用量可对账；多版本切换后补 |
| 7 | 消息反馈按 `(message_id, user_id)` 唯一，upsert | 支持改赞/取消，且跨用户隔离 |
| 8 | 置顶会话用独立查询渲染，不改变现有游标分页 | 避免 `pinned + id` 复合游标破坏现有 `before` |
| 9 | 附件只做按钮占位，不接上传 | 附件/多模态按 P6-B 单独评估安全面 |
| 10 | 项目入口放在聊天侧栏，不新增顶级导航 | 延续 S3 的导航减负方向 |

## 3. 数据模型

### 3.1 `projects`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | uuid7 |
| `workspace_id` | UUID FK workspace, index | 租户 |
| `owner_user_id` | UUID FK user, index | 创建者 |
| `name` | String(120) | 项目名 |
| `description` | String(500) | 简介 |
| `instructions` | Text | 项目指令，创建会话时快照 |
| `default_provider_id` | String(50) nullable | 默认 Provider |
| `default_model` | String(200) nullable | 默认模型 |
| `default_kb_id` | UUID FK knowledge_bases nullable | 默认知识库 |
| `default_agent` | Boolean default false | 新会话是否默认 Agent |
| `archived_at` | DateTime nullable | 项目软归档 |
| `created_at` / `updated_at` | DateTime | |

约束与索引：

- `Index("ix_projects_workspace_archived", "workspace_id", "archived_at")`
- 不对项目名做唯一约束（允许重名，前端提示即可）

### 3.2 `conversations` 新增列

| 字段 | 类型 | 说明 |
|------|------|------|
| `project_id` | UUID FK projects nullable, index | 所属项目 |
| `pinned` | Boolean default false, index | 置顶 |
| `generation_settings` | JSON default `{}` | `temperature` / `max_tokens` / `top_p` |
| `updated_at` | DateTime | 最近消息时间，供排序/展示 |

索引：

- `Index("ix_conversations_workspace_project_archived", "workspace_id", "project_id", "archived_at")`
- `Index("ix_conversations_workspace_pinned", "workspace_id", "pinned")`

### 3.3 `message_feedback`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID PK | |
| `message_id` | UUID FK messages CASCADE, index | |
| `user_id` | UUID FK users CASCADE, index | |
| `rating` | String(10) | `up` / `down` |
| `reason` | String(500) default "" | 可选原因 |
| `created_at` / `updated_at` | DateTime | |

- `UniqueConstraint("message_id", "user_id")`

### 3.4 `messages` 新增列

| 字段 | 类型 | 说明 |
|------|------|------|
| `reply_to_message_id` | UUID FK messages nullable | 重新生成时指向被重新回答的 assistant 消息 |

### 3.5 迁移与回填

- 新迁移接在 `c1d2e3f4a5b6` 之后。
- 回填：`pinned=false`、`generation_settings='{}'`、`updated_at=created_at`、`project_id=NULL`、`reply_to_message_id=NULL`。
- 不删除/重写历史会话和消息。

## 4. API 设计

### 4.1 项目

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/projects?archived=false` | 列出 workspace 项目，含会话数 |
| POST | `/projects` | 创建项目 |
| GET | `/projects/{id}` | 项目详情 + 默认配置 + 会话数 |
| PATCH | `/projects/{id}` | 名称、描述、指令、默认配置、归档 |
| DELETE | `/projects/{id}` | 软归档；不级联删除会话 |

- 跨 workspace 一律 404。
- 编辑/删除校验：`owner_user_id == user.id` 或 workspace role == owner；否则 403（资源可见时）或 404（不可见时）。
- 默认 `provider_id`/`model` 必须在 scoped registry 中存在，且具备 `chat`（或 `tools` when `default_agent`）能力；否则 422。
- 默认 `kb_id` 必须在同一 workspace 且未删除，否则 422。

### 4.2 会话扩展

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/conversations?q=&project_id=&archived=&pinned=&limit=&before=` | 搜索与过滤 |
| POST | `/conversations` | 增加可选 `project_id`；缺省字段从项目继承 |
| PATCH | `/conversations/{id}` | `title` / `pinned` / `project_id` / `archived` / `generation_settings` |
| POST | `/conversations/batch` | 批量 archive/unarchive/move，最多 100 条，原子校验 |

- `q`：标题 + 消息内容 `ILIKE`，`%`/`_` 转义；`limit` 1–200。
- `project_id`：UUID 或 `none`（无项目）过滤。
- `archived`：默认 `false`；`true` 只看归档；`all` 全部。
- `pinned=true|false`：可选过滤；侧栏分别查询置顶区和普通区。
- 创建时继承顺序：
  1. 请求显式字段；
  2. 项目默认字段；
  3. 系统默认（`auto` / 无 KB / 非 Agent）。
- 项目指令快照：`system_prompt` = 项目 `instructions` + Prompt 模板渲染结果（模板优先保留在后），写入会话后不再随项目变化。
- `updated_at` 在每次消息完成后更新。

### 4.3 聊天控制

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/conversations/{id}/messages/{message_id}/regenerate` | 对指定 assistant 消息重新生成，SSE 同发送契约 |
| PUT | `/messages/{message_id}/feedback` | upsert 反馈 `{rating, reason}` |
| DELETE | `/messages/{message_id}/feedback` | 取消当前用户反馈 |

- 重新生成：
  - 仅允许对 `role=assistant` 且属于当前 workspace 会话的消息调用。
  - 找到该回答对应的最近一条 user 消息，以其内容重跑完整链路（RAG/Agent/Provider/配额/用量）。
  - 新 assistant 消息写 `reply_to_message_id=原 assistant.id`；旧消息保留。
  - 旧 assistant 消息不进入新请求的上下文，避免自我引用。
- 生成参数：
  - 白名单 `temperature`（0–2）、`max_tokens`（1–32768）、`top_p`（0–1）。
  - 服务端 clamp 到合法范围；未知键忽略。
  - 仅非空参数传给 `stream_chat(..., **settings)`。
- 反馈：
  - 只允许对当前 workspace 内、已完成或已取消的 assistant 消息反馈。
  - 跨用户/跨 workspace 404。

## 5. 服务层

- 新增 `app/services/projects.py`：
  - CRUD、权限判断、默认配置校验、会话计数。
- 扩展 `app/routers/conversations.py`：
  - 列表过滤、搜索、PATCH、批量、重新生成、反馈。
  - 继承逻辑抽成 `_resolve_conversation_defaults(project, payload)`。
  - 生成参数抽成 `_generation_opts(conversation)`。
- 复用现有：
  - `_get_owned_conversation`（workspace 作用域）。
  - SSE 发送、引用、Agent、配额、用量账本。
- 审计：项目默认配置变更写 `audit_logs`（`project.update`），不记录项目指令全文。

## 6. 前端

### 6.1 路由与入口

- 新增 `/projects`、`/projects/:id`，放在控制台 Work 分组下。
- 聊天侧栏增加：
  - “项目”切换/筛选；
  - 会话搜索框；
  - 置顶区 + 最近会话区；
  - 会话右键/更多菜单：重命名、置顶、归档、移动到项目。

### 6.2 页面

- `/projects`：
  - 项目卡片：名称、简介、默认模型、会话数。
  - 新建/编辑/归档。
- `/projects/:id`：
  - 项目概览：指令、默认 Provider/模型/KB/Agent。
  - 会话列表。
  - “在项目中新建会话”。
- 新会话页：
  - 可选项目；选中后预填默认模型/Provider/KB/Agent，并显示项目指令摘要。
- 聊天页：
  - 顶栏模型/Provider 切换。
  - 生成参数抽屉（temperature / max tokens / top_p）。
  - assistant 消息操作：重新生成、赞/踩（可填原因）。
  - 附件按钮占位，明确“即将上线”，不触发上传。

### 6.3 类型与 i18n

- `types.ts` 增加 `Project`、`ProjectDetail`、`GenerationSettings`、`MessageFeedback`。
- zh/en 同步新增 `projects.*`、`chat.manage.*`、`chat.settings.*`、`chat.feedback.*`、`chat.regenerate`。
- 保持 key parity 测试通过。

## 7. 测试计划（小规模）

后端约 10–12 个测试：

1. 项目 CRUD + 跨 workspace 404。
2. 成员只读、owner/创建者可编辑。
3. 项目内新会话继承默认 provider/model/kb/agent 与指令快照。
4. 非法默认 provider/model/kb 返回 422。
5. 会话按标题/消息内容搜索。
6. 项目、归档、置顶过滤。
7. 重命名/置顶/移动/恢复归档。
8. 批量操作原子性 + 跨 workspace 404。
9. 重新生成追加新消息并写用量事件（脚本化 fake provider）。
10. 反馈 upsert、取消、跨用户隔离。
11. 生成参数 clamp 与 provider 透传（fake provider 记录 kwargs）。
12. 保留既有会话/隔离测试全绿。

前端：

- 单元测试：生成参数 clamp、项目默认继承 helper。
- E2E：创建项目 → 项目内新建会话 → 置顶/重命名/归档 → 重新生成（mock SSE）。
- 真实验证：本地 Provider 跑一次项目会话与重新生成。

## 8. 切片交付

### S4a 项目基础

- 迁移：`projects`，`conversations.project_id/pinned/generation_settings/updated_at`。
- `services/projects.py`、`routers/projects.py`。
- `POST /conversations` 继承项目默认值 + 指令快照。
- `/projects`、`/projects/:id` 页面；侧栏项目筛选。
- 顺带补 S3c 尾巴：管理概览增加运营位/公告数量。

### S4b 会话工作区

- 列表搜索/过滤、PATCH、批量操作。
- 侧栏搜索、置顶区、更多菜单、归档页。
- 会话移动项目。

### S4c 聊天控制

- 会话级生成参数与 Provider 模型切换。
- 重新生成、消息反馈、附件占位。
- 聊天页操作区与 i18n。

## 9. 验收标准

- 项目 CRUD 与默认配置继承可用，跨租户/越权返回 404/403 符合约定。
- 项目指令在会话创建时快照，项目后续修改不影响历史会话。
- 会话可搜索、置顶、重命名、归档/恢复、移动项目、批量操作。
- 重新生成产生新 assistant 消息，旧消息保留，用量账本新增一条。
- 生成参数只透传合法键，Provider 不支持时不导致请求失败。
- 反馈按用户隔离，可改可取消。
- 后端全量测试、ruff、前端 typecheck/unit/build/E2E 通过。

## 10. 风险与边界

- **会话可见性**：现有实现是 workspace 内共享；S4 不改变该语义。若后续要“项目内私有会话”，需单独设计 `visibility` 与列表过滤。
- **搜索性能**：先用 `ILIKE` + limit；数据量增大后再加 pg_trgm GIN 索引。
- **重新生成与 Agent/RAG**：复用发送链路，注意旧回答不进上下文，避免自我引用。
- **参数兼容性**：部分 Provider 可能拒绝 `top_p`/`max_tokens`；只传非空值，失败按现有 ProviderError 处理。
- **附件**：S4 只放入口占位，不产生“已支持上传”的误导。
- **批量删除**：S4 不提供物理删除；批量只做归档/恢复/移动。

## 11. 待确认

默认按以下方案执行，若无异议即可开工 S4a：

1. 项目 workspace 级共享，创建者/owner 可编辑，成员只读使用。
2. 项目只保留一个默认 KB。
3. 重新生成追加新消息，不覆盖旧回答。
4. 附件只做占位。
5. 项目入口放聊天侧栏，不新增顶级导航。