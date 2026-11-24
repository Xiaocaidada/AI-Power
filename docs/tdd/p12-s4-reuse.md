# P12-S4 对话成果复用

日期：2026-11-24
状态：已完成（成果复用 MVP）

## 目标

把对话回答转成可长期使用的成果：

- 回答保存为知识库文档并进入现有 ingestion。
- 识别并保存代码块。
- 识别并保存项目任务，支持状态流转。
- 工作区可见、可撤销的对话分享链接。
- 导出保留代码块、表格、引用与网页来源。

## 实现

### 数据

- `code_snippets`：workspace/user、project、conversation/message 来源、标题、语言、代码。
- `project_tasks`：workspace、project、creator、标题、状态（todo/doing/done）、优先级、
  对话/消息来源。
- `conversation_shares`：workspace、conversation、creator、token 哈希、过期时间、撤销时间。
- 迁移：`a8b9c0d1e2f3_p12_s4_reuse.py`。

### 回答保存为知识库

- `POST /conversations/{id}/messages/{message_id}/save-to-knowledge`
- 仅允许已完成 assistant 回答。
- 服务端生成真实 Markdown 文件（标题、来源、回答、网页来源），写入 `UPLOAD_DIR`。
- 创建 `Document` + `IngestionJob`，复用现有队列、分块与 embedding；返回 `202`。
- 相同 workspace/KB/content_hash 返回原文档并标记 `duplicate=true`。
- 文档元数据保留 `conversation_id`、`message_id` 与 `source_url=conversation://...`。

### 代码片段

- `GET /conversations/{id}/messages/{message_id}/code-blocks`：识别围栏代码块。
- `GET/POST /code-snippets`、`DELETE /code-snippets/{id}`。
- 片段保留语言、标题与来源消息；仅创建者可见。
- 前端 `/snippets` 页面展示、复制、删除与回到来源对话。

### 项目任务

- `GET /conversations/{id}/messages/{message_id}/task-candidates`：
  识别 Markdown 复选框与 `TODO:` 行。
- `POST /project-tasks` 批量保存到项目。
- `GET /project-tasks?project_id=`、`PATCH/DELETE /project-tasks/{id}`。
- 项目页展示任务，可切换 todo/doing/done、删除。
- 任务为 workspace/project 级读取；只有创建者或 workspace owner 可修改。

### 分享链接

- `POST /conversations/{id}/shares`：生成随机 token，仅返回一次；数据库只存 SHA-256。
- `GET /conversations/{id}/shares`：列出有效/撤销状态（不返回 token）。
- `DELETE /conversations/{id}/shares/{share_id}`：撤销。
- `GET /shares/{token}`：需要登录且必须是该工作区成员；非成员 404。
- 分享详情清除个人反馈与记忆引用，保留消息、引用与网页来源。
- 前端对话菜单“分享”创建/复制/撤销；`/share/:token` 只读页面。

### 导出

- Markdown 导出保留原始消息内容（代码块、表格、列表结构不变），并追加引用与网页来源。
- JSON 导出保留完整消息、引用、网页来源与附件元数据。

### 新建页备注

- “网页搜索”快捷按钮放在自动路由模型选项右侧，直接切换普通/网页搜索模式。

## 测试

- `tests/test_p12_s4_reuse.py`：
  - 代码块与任务候选提取。
  - 保存到知识库、文档 ready、分块存在、重复内容去重。
  - 代码片段创建/列表/跨用户隔离/404。
  - 项目任务批量创建、来源消息、状态更新。
  - 分享非成员 404、邀请成员后可读、撤销后 404。
- 全量：`ruff check .`、`pytest -n auto`、`npm run typecheck`、`npm test -- --run`、`npm run build`。

## 边界

已解决：

- 回答 → 知识库真实文档，不伪造检索结果。
- 代码块与任务识别、保存、来源追踪。
- 任务状态流转。
- 分享链接成员校验、过期、撤销、个人数据清理。
- 导出保留 Markdown 结构并补充网页来源。

后续切片：

- 公开匿名分享、密码/水印/访问统计：需要产品与安全决策。
- PDF/Word 导出：需要额外渲染管线。
- 代码片段共享/项目关联 UI：当前片段仅个人可见。
- 任务负责人、截止日期、看板视图：后续增强。

明确不做（真实外部集成）：

- 不发送邮件/IM 分享通知。
- 不接入第三方文件存储或公开对象存储。
- 不生成 PDF/Word 或第三方文档服务链接。

需要用户决策：

- 是否开放公开匿名分享。
- 是否允许代码片段/任务跨工作区共享。
- 分享有效期默认值与最大时长。