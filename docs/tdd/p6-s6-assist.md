# P6-S6 辅助与收口 — 实现证据

- **Date:** 2026-11-24
- **Scope:** 个人控制台、提示词分类/收藏、文件中心、全局搜索、用量口径说明。
- **计划:** [`p6-s6-plan.md`](../plan/p6-s6-plan.md)
- **API:** [`assist.md`](../api/assist.md)

## 1. 数据模型

迁移 `f4a5b6c7d8e9_p6_s6_assist.py`：

- `prompt_templates.category`（默认 `general`，索引）
- `prompt_favorites`
  - `template_id`、`user_id`、`created_at`
  - 唯一约束 `(template_id, user_id)`

## 2. 后端

### 控制台

- `app/services/dashboard.py`
  - Provider/模型/会话/项目/KB/Agent/插件/未读通知计数。
  - 近 30 天请求、token、成本（`usage_events`）。
  - 最近 5 个会话与项目。
- `GET /dashboard`

### 提示词库

- `app/services/prompts.py`
  - `list_templates` 支持 `q`/`category`/当前用户收藏过滤。
  - 收藏写入按用户唯一；模板更新。
- `GET /prompt-templates?q=&category=&favorite=`
- `PATCH /prompt-templates/{id}`
- `POST/DELETE /prompt-templates/{id}/favorite`

### 文件中心

- `GET /files`：跨 KB 文档列表，支持文件名与状态过滤、游标分页。
- `GET /documents/{id}/download`：返回原文件。
  - workspace 作用域；路径必须位于 `UPLOAD_DIR` 内。

### 全局搜索

- `app/services/search.py`
  - 会话（标题 + 消息内容）、项目、可见 Agent、提示词、KB、文档。
  - 每类最多 5 条；结果含 `type/id/title/subtitle/href`。
  - 所有查询按 workspace 过滤，跨 workspace 为空。

### 用量口径

- 用量页新增说明：平台账本与第三方 Provider 账单可能不同，以供应商账单为准。

## 3. 前端

- `/dashboard`：计数卡片、30 天用量、最近会话/项目、搜索/文件入口。
- `/files`：跨 KB 文件列表、搜索/状态过滤、下载。
- `/search`：按类型分组结果。
- `/settings/prompts`：
  - 分类输入/过滤、关键词搜索、仅看收藏。
  - 星标收藏（按用户）。
  - “在对话中使用”跳转 `/chat?promptVersion=<id>`。
- 新会话页读取 `promptVersion` 自动选中 Prompt 模板。
- 侧栏：文件、总览、搜索入口。

## 4. 验证

```text
.venv/Scripts/python.exe -m pytest tests/test_assist.py tests/test_migrations.py \
  tests/test_prompt_templates.py -q
15 passed

.venv/Scripts/python.exe -m pytest -q
full backend suite passed (exit 0)

.venv/Scripts/python.exe -m ruff check app tests alembic
All checks passed!

cd web && npm run typecheck
passed

cd web && npm test -- --run
24 passed

cd web && npm run build
built in 4.21s

cd web && npm run test:e2e
7 passed（新增控制台/全局搜索）

docker compose up -d --build api worker web
alembic_version = f4a5b6c7d8e9；prompt_favorites 与 prompt_templates.category 存在
/readyz → database ok, redis ok

真实 PostgreSQL 冒烟（临时用户，已清理）：
project 201 / KB 201 / prompt favorite 200 → favorite=true 命中 1 条
dashboard → projects=1, knowledge_bases=1, conversations=0
search?q=needle → 3 条（knowledge_base / project / prompt）
files → 0 条（无文档）
```

## 5. 已知边界

- 全局搜索为 ILIKE，不是语义/向量检索。
- 文件中心不提供上传、批量移动/删除。
- 提示词分类为自由文本。
- 控制台为只读聚合，不支持自定义布局。
- 下载仅返回原文件；不提供在线预览。