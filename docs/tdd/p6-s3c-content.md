# P6-S3c 首页运营内容、公告与通知 — 实现证据

- **Date:** 2026-11-23
- **Scope:** 首页 Banner/推荐位/活动、公告发布与可见窗口、登录用户通知/未读、管理员内容 CRUD 与前端。
- **计划:** [`P6 规划`](../plan/p6-plan.md)
- **API:** [`content.md`](../api/content.md)

## 1. 数据模型

迁移 `c1d2e3f4a5b6_p6_content.py`（接在 `b0c1d2e3f4a5` 之后）：

- `home_placements`
  - `kind`（banner/featured/activity）、`title`、`subtitle`、`body`
  - `image_url`、`link_url`、`link_label`
  - `sort_order`、`enabled`、`starts_at`、`ends_at`
- `announcements`
  - `title`、`summary`、`body`、`cover_url`
  - `category`（notice/update/event/maintenance）
  - `pinned`、`status`（draft/published/archived）
  - `published_at`、`expires_at`
- `announcement_reads`
  - `announcement_id`、`user_id`、`read_at`
  - 唯一约束 `(announcement_id, user_id)`

## 2. 服务与接口

- `app/services/content.py`
  - 运营位可见窗口过滤（enabled + starts/ends）。
  - 公告可见性：`published` + 已到发布时间 + 未过期。
  - 通知聚合：可见公告 LEFT JOIN 当前用户已读，返回 `unread_count` 与 `read_at`。
  - 已读写入幂等；`read-all` 只处理当前用户可见未读。
  - 运营位/公告时间窗口校验：结束时间必须晚于开始/发布时间。
- `app/routers/content.py`
  - 公开：`GET /home`、`GET /announcements`、`GET /announcements/{id}`。
  - 登录：`GET /notifications`、`POST /notifications/{id}/read`、`POST /notifications/read-all`（JWT）。
  - 管理员：`/admin/content/placements`、`/admin/content/announcements` 的 GET/POST/PATCH/DELETE，非管理员 404。
  - 管理员写操作落 `audit_logs`（`content.placement_*`、`content.announcement_*`）。

## 3. 前端

- 首页 `/`：
  - 消费 `GET /home` 展示 Banner、推荐/活动卡片与最新公告。
  - 模型推荐仍使用公共模型广场；`/home` 为空时页面保持原样。
- 公告：
  - `/announcements`：分类筛选、置顶/分类/日期、空状态。
  - `/announcements/:id`：正文、封面、分类与发布时间；登录用户进入详情自动标记已读。
- 门户导航：
  - 新增“公告”入口。
  - 登录后右上角通知铃铛：未读数徽标、最近通知、全部已读、查看全部公告。
- 管理后台：
  - `/admin/content`：运营位/公告两个标签页，列表 + 新建/编辑弹窗 + 删除。
  - 管理员侧边栏增加“内容管理”入口。

## 4. 验证

```text
.venv/Scripts/python.exe -m pytest tests/test_content.py tests/test_migrations.py -q
7 passed

.venv/Scripts/python.exe -m pytest -q
full backend suite passed (exit 0)

.venv/Scripts/python.exe -m ruff check app tests alembic
All checks passed!

cd web && npm run typecheck
passed

cd web && npm test -- --run
24 passed

cd web && npm run build
built in 8.91s

cd web && npm run test:e2e
4 passed（含新增公开首页/公告/详情）

docker compose up -d --build api worker web
GET /home → 200 {"banners":[],"featured":[],"activities":[],"announcements":[]}
GET /announcements → 200 []
web / 与 /announcements → 200
/readyz → database ok, redis ok
alembic_version = c1d2e3f4a5b6；三张新表均存在
```

全量后端测试（退出码 0）覆盖既有接口；本切片遵守跨用户 404、管理员 404、URL 白名单等约束。

## 5. 已知边界

- 首页运营位暂不做拖拽排序与图片上传，只接受 URL。
- 公告正文为纯文本（保留换行），未接富文本/Markdown 渲染。
- 通知中心只覆盖公告类通知；工作流/Webhook 等事件通知不在本切片。
- 管理概览页尚未加入内容数量统计。