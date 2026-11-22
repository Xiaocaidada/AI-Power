# 首页内容与公告 API

面向公开门户、登录用户通知与管理员内容运营。

## 1. 公开接口（无需登录）

### `GET /home`

返回首页聚合内容：

```json
{
  "banners": [{ "kind": "banner", "title": "…", "link_url": "/models" }],
  "featured": [{ "kind": "featured", "title": "…" }],
  "activities": [{ "kind": "activity", "title": "…" }],
  "announcements": [{ "id": "…", "title": "…", "category": "update" }]
}
```

- 只返回 `enabled=true` 且处于 `starts_at`/`ends_at` 窗口内的运营位。
- 只返回 `status=published`、已到发布时间且未过期的公告，最多 3 条。

### `GET /announcements?category=&limit=`

- `category`：`notice|update|event|maintenance`。
- `limit`：1–50，默认 20。
- 排序：置顶优先，其次按发布时间/创建时间倒序。

### `GET /announcements/{announcement_id}`

返回公告详情。仅 `published` 且未过期可见；其他情况返回 `404`（不泄露草稿/归档存在性）。

```bash
curl -s http://HOST:8002/announcements
curl -s http://HOST:8002/announcements/<announcement_id>
```

## 2. 登录用户通知

需要 JWT（API Key 不适用）。

### `GET /notifications?limit=`

```json
{
  "unread_count": 2,
  "items": [
    {
      "id": "…",
      "title": "…",
      "category": "notice",
      "read_at": null
    }
  ]
}
```

`items` 为当前可见公告，`read_at=null` 表示未读；`unread_count` 统计全部可见未读公告（不只是当前页）。

### `POST /notifications/{announcement_id}/read`

标记单条已读，返回带 `read_at` 的通知对象。公告不可见时返回 `404`。

### `POST /notifications/read-all`

```json
{ "marked": 3 }
```

只标记当前用户可见且未读的公告。已读记录按 `(announcement_id, user_id)` 唯一，跨用户隔离。

## 3. 管理员接口

`/admin/content/*` 仅 `users.role=admin`，其他用户返回 `404`。

### 运营位

- `GET /admin/content/placements`：包含禁用与过期项。
- `POST /admin/content/placements`
- `PATCH /admin/content/placements/{id}`
- `DELETE /admin/content/placements/{id}`

字段：

| 字段 | 说明 |
|------|------|
| `kind` | `banner\|featured\|activity` |
| `title` / `subtitle` / `body` | 展示文案 |
| `image_url` / `link_url` / `link_label` | 图片、跳转、按钮文案 |
| `sort_order` | 同类型内排序，越小越靠前 |
| `enabled` | 是否启用 |
| `starts_at` / `ends_at` | 可选展示窗口（ISO 8601） |

### 公告

- `GET /admin/content/announcements`：包含草稿/归档/定时项。
- `POST /admin/content/announcements`
- `PATCH /admin/content/announcements/{id}`
- `DELETE /admin/content/announcements/{id}`

字段：

| 字段 | 说明 |
|------|------|
| `title` / `summary` / `body` | 标题、摘要、正文 |
| `cover_url` | 封面（可空） |
| `category` | `notice\|update\|event\|maintenance` |
| `pinned` | 置顶 |
| `status` | `draft\|published\|archived` |
| `published_at` | 定时发布时间；置为 `published` 且为空时自动写当前时间 |
| `expires_at` | 过期时间，到期后公开端不可见 |

创建/更新/删除都会写入 `audit_logs`（`content.*`）。

## 4. 安全约束

- `image_url`、`cover_url`、`link_url` 只接受站点相对路径（`/…`）或 `http(s)://`，拒绝 `javascript:`、`data:` 等。
- 公告可见性由服务端判定；前端不依赖隐藏字段。
- 已读记录按用户隔离，通知接口不接受 `user_id` 参数。
- 管理端非管理员统一 `404`，不暴露内容管理面。