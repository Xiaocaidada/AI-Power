# 控制台、提示词库、文件中心与全局搜索 API

## 1. 个人控制台

### `GET /dashboard`

```json
{
  "counts": {
    "providers": 1,
    "models": 2,
    "conversations": 3,
    "projects": 1,
    "knowledge_bases": 2,
    "agents": 1,
    "plugins": 0,
    "unread_notifications": 0,
    "requests_30d": 4,
    "tokens_30d": 100,
    "cost_30d": 0.01
  },
  "recent_conversations": [],
  "recent_projects": []
}
```

- workspace 作用域；`agents` 只统计当前用户可见（自己的私有 + 共享）。
- 近 30 天数据来自统一 `usage_events` 账本。

## 2. 提示词库

### `GET /prompt-templates?q=&category=&favorite=`

- `q`：名称、描述、版本 system prompt 模糊搜索。
- `category`：自由文本分类。
- `favorite=true`：只看当前用户收藏。

每个模板返回：

```json
{
  "id": "…",
  "name": "Support reply",
  "description": "…",
  "category": "support",
  "favorite": true,
  "versions": []
}
```

### `PATCH /prompt-templates/{id}`

```json
{ "name": "…", "description": "…", "category": "sales" }
```

### `POST /prompt-templates/{id}/favorite`

收藏当前用户；返回 `{ "favorite": true }`。

### `DELETE /prompt-templates/{id}/favorite`

取消收藏；返回 `{ "favorite": false }`。

收藏按 `(template_id, user_id)` 唯一，用户之间互不影响。

## 3. 文件中心

### `GET /files?q=&status=&limit=&before=`

跨知识库列出未删除文档：

```json
[
  {
    "id": "…",
    "filename": "report.pdf",
    "mime": "application/pdf",
    "size_bytes": 12345,
    "status": "ready",
    "error_code": null,
    "page_count": 3,
    "kb_id": "…",
    "kb_name": "产品文档",
    "created_at": "…"
  }
]
```

### `GET /documents/{id}/download`

返回原文件（`Content-Disposition: attachment`）。

- 仅当前 workspace 可见；跨 workspace `404`。
- 校验存储路径必须位于 `UPLOAD_DIR` 内。

## 4. 全局搜索

### `GET /search?q=`

```json
{
  "query": "needle",
  "results": [
    {
      "type": "project",
      "id": "…",
      "title": "Needle project",
      "subtitle": "A project",
      "href": "/projects/…"
    }
  ]
}
```

搜索范围（每类最多 5 条）：

- 会话标题 + 消息内容
- 项目名称/描述/指令
- 当前用户可见的自定义 Agent
- 提示词名称/描述/版本内容
- 知识库名称
- 文件名

所有结果按 `workspace_id` 过滤；其他 workspace 返回空结果。

## 5. 用量口径

`GET /usage/*` 统计来自平台 `usage_events` 账本。使用用户自带 Provider Key 时，第三方供应商的实际账单可能与本平台统计不同，应以供应商账单为准；前端用量页显式展示该说明。