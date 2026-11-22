# P5-S6 收口（功能范围）— TDD 证据

- **Date:** 2026-11-23
- **Scope（按用户要求缩小）:** 只实现两个新增功能——批量上传队列、会话导出；跳过 ≥3 条新增 Playwright、压测、覆盖率冲刺与完整演示脚本。
- **相关:** [`P5 计划`](../plan/p5-plan.md)

## 1. 批量上传

已有 `<input multiple>` 会并发触发多个上传，但只有一个全局进度，多个文件会互相覆盖。改为逐文件任务队列：

- `web/src/lib/uploadBatch.ts`：扩展名/大小校验，生成 `UploadTask`（`uploading|ready|duplicate|failed`）。
- `KnowledgeDetailPage`：多选/拖拽进入同一个 `uploadBatch`，顺序上传；每行独立进度、完成、重复或失败原因；完成后刷新文档/分块/统计。

测试：

```text
web/src/lib/uploadBatch.test.ts
2 passed
- 接受 pdf/md/txt，拒绝其他扩展名
- 超大文件标记 failed，合法文件保持 uploading
```

## 2. 会话导出

新增 `GET /conversations/{id}/export?format=markdown|json`：

- 复用会话详情加载；消息与引用完整导出。
- Markdown 包含标题、Provider/Model/Created、用户/助手正文与引用来源；JSON 为会话详情结构。
- `Content-Disposition: attachment; filename="conversation-<id>.md|json"`。
- 支持 JWT 与带 `kb:read` 的 API Key；跨 workspace 404。
- 前端聊天页新增导出按钮与 Markdown/JSON 选择对话框，通过 `apiDownload` 携带 token 下载。

后端用例（`tests/test_exports.py`，5 条）：

| 用例 | 覆盖 |
|---|---|
| `test_export_conversation_markdown` | 200、Markdown 内容、文件名/类型 |
| `test_export_conversation_json` | JSON 结构、消息角色/内容 |
| `test_export_conversation_supports_read_api_key` | `kb:read` API Key |
| `test_export_conversation_is_workspace_scoped` | 跨 workspace 404 |
| `test_export_rejects_unknown_format` | 非法 format 422 |

## 3. 回归

```text
.venv/Scripts/python.exe -m pytest
375 collected, 371 passed, 4 skipped
```

```text
.venv/Scripts/python.exe -m ruff check app tests scripts sdk/python alembic
All checks passed!
```

前端：

```text
npm test -- --run
24 passed
npm run build
built in 3.80s
npm run test:e2e
3 passed
```

## 4. 真实部署验证（2026-11-23）

API/web 已重建，`/readyz` 正常。真实 API 导出：

```json
{
  "markdown_status": 200,
  "markdown_type": "text/markdown; charset=utf-8",
  "markdown_disposition": "attachment; filename=\"conversation-<id>.md\"",
  "markdown_has_user": true,
  "json_status": 200,
  "json_messages": 2
}
```

批量上传以 `uploadBatch.test.ts`、类型检查与生产构建验证；未新增浏览器用例。

## 5. 明确跳过

按用户要求，S6 以下项目未执行：

- 新增 ≥3 条 Playwright（评测页、Webhook 投递、异步 run 重连之外的扩展）；
- 检索/评测压测脚本；
- 覆盖率冲刺到 80%；
- 一条命令的完整演示脚本。