# P6-S6 辅助与收口 — 实施规划

- **Date:** 2026-11-24
- **Status:** 已完成
- **上级规划:** [`p6-plan.md`](./p6-plan.md)
- **API:** [`assist.md`](../api/assist.md)

## 1. 切片

1. **个人控制台**：聚合 Provider/模型/会话/项目/KB/Agent/插件/未读通知与近 30 天用量。
2. **提示词库**：分类、搜索、按用户收藏、一键在对话中使用。
3. **文件中心**：跨知识库文档列表、搜索/状态过滤、原文件下载。
4. **全局搜索**：会话、项目、Agent、提示词、知识库、文件统一搜索。
5. **用量口径说明**：平台账本与第三方 Provider 账单分离。
6. **收口**：文档、部署与安全测试复核。

## 2. 决策

| # | 决策 | 理由 |
|---|------|------|
| 1 | 控制台只读聚合，不复制数据 | 避免一致性问题 |
| 2 | 提示词分类为 workspace 级，收藏按用户 | 分类便于共享，收藏是个人偏好 |
| 3 | 一键使用跳转 `/chat?promptVersion=<id>` | 复用现有 Prompt 快照机制 |
| 4 | 文件中心只读 + 下载，不新增上传入口 | 上传仍走知识库上下文 |
| 5 | 下载做路径归属校验 | 防止越出 `UPLOAD_DIR` |
| 6 | 全局搜索每类最多 5 条 | 控制响应与噪声 |
| 7 | 全局搜索先 ILIKE，后续再加 trigram | 规模优先简单 |
| 8 | 用量说明明确“第三方账单为准” | 避免把平台估算当供应商账单 |

## 3. 数据与接口

- `prompt_templates.category`
- `prompt_favorites(template_id, user_id)` 唯一
- `GET /dashboard`
- `GET /prompt-templates?q=&category=&favorite=`
- `PATCH /prompt-templates/{id}`
- `POST/DELETE /prompt-templates/{id}/favorite`
- `GET /files?q=&status=&limit=&before=`
- `GET /documents/{id}/download`
- `GET /search?q=`

## 4. 安全

- 所有查询按 `workspace_id` 过滤，跨 workspace 404/空结果。
- 搜索与文件名查询参数化；`%`/`_` 转义。
- 下载前校验文件路径位于 `UPLOAD_DIR` 内。
- 提示词收藏按用户唯一，用户之间互不影响。
- 控制台只返回当前 workspace/用户可见计数。

## 5. 边界

- 全局搜索不做向量/语义检索。
- 文件中心不提供批量删除/移动。
- 提示词分类为自由文本，不做受控词表。
- 控制台不做自定义布局。