# P6-B 剩余业务闭环规划

## 背景

P6-A（S1–S6）与 P6 Chat UI 已完成。P6-B 收口 `拓展增强.txt` 中尚未落地的核心能力。

## 切片

### B0 对话生命周期

- `PATCH /conversations/{id}/messages/{message_id}`：编辑用户提问并截断其后消息；前端二次确认后重新生成。
- `DELETE /conversations/{id}/permanent`：硬删除会话；`usage_events` 保留（只追加账本）。
- `POST /conversations/batch` 增加 `delete` 动作。
- 侧栏增加删除、批量选择（归档 / 删除）。

### B1 聊天附件与文件中心

- `chat_attachments`：工作区/用户隔离，支持 PDF/MD/TXT/DOCX/CSV；图片按模型 `vision` 能力接收。
- `POST /attachments`、`GET /attachments`、`DELETE`、下载；会话创建与消息发送通过 `attachment_ids` 关联。
- 文本附件解析后注入模型上下文；消息区显示附件卡片；文件中心增加“对话附件”。
- 安全：扩展名白名单、大小上限、UUID 存储、路径包含、跨工作区 404、敏感文本不写日志。

### B2 知识库补全

- `PATCH /knowledge-bases/{id}`：名称与描述。
- 解析支持 DOCX/CSV。
- 文档列表支持搜索与标签；`PATCH /documents/{id}` 更新标签。

### B3 多知识库检索

- `conversation_knowledge_bases` 关联表；会话创建接受 `kb_ids`，保留 `kb_id` 作为首个 KB 兼容字段。
- 检索与引用合并多个 KB，按 chunk 去重。
- 新建会话页支持多选知识库；会话 header 显示 KB 数量。

### B4 辅助收尾

- `GET /usage/recent`：最近调用、成功/失败（结合 trace）。
- 全局搜索加入模型与插件。
- `/help` 帮助中心：Provider、模型广场、对话、知识库、Agent、FAQ。

## 约束

- 不破坏 workspace 404、配额、用量账本、SSE 契约。
- 附件与文档不记录全文日志；跨用户/跨工作区统一 404。
- 每个切片补小规模测试，保留安全与隔离测试。