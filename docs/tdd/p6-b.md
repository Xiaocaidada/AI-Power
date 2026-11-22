# P6-B 实施证据

## 范围

按 `docs/plan/p6-b-plan.md` 完成 B0–B4。

### B0 对话生命周期

- `PATCH /conversations/{id}/messages/{message_id}`：编辑用户提问并截断后续消息；流式回复中拒绝编辑（409）。
- `POST /conversations/{id}/messages/{message_id}/reply`：基于编辑后的用户消息重新生成回复。
- `DELETE /conversations/{id}/permanent` 与 `POST /conversations/batch {action:"delete"}`：硬删除会话；`usage_events` 通过 `ON DELETE SET NULL` 保留。
- 侧栏：删除菜单、批量选择（归档 / 删除）、删除确认。

### B1 聊天附件

- `chat_attachments` 表与 `POST/GET/DELETE /attachments`、下载接口。
- 支持 `.pdf/.md/.txt/.docx/.csv` 文本解析；`.png/.jpg/.jpeg/.webp` 以 data URL 发送，仅限非 Agent 且模型具备 `vision`。
- 会话创建与消息发送通过 `attachment_ids` 关联；历史消息附件文本进入模型上下文；会话详情返回附件。
- 文件中心新增“对话附件”；路径下载校验 `UPLOAD_DIR` 包含关系。

### B2 知识库补全

- `PATCH /knowledge-bases/{id}` 名称/描述；创建时也接受描述。
- DOCX/CSV 解析。
- 文档列表支持 `q/tag` 过滤，`PATCH /documents/{id}` 更新标签。

### B3 多知识库

- `conversation_knowledge_bases` 关联表；`ConversationCreate.kb_ids`，`ConversationDetail.kb_ids`。
- 检索与 `kb_search` 工具支持多个 KB，按 chunk 去重；首个 KB 提供 embedding/rerank 设置。
- 新建会话页多选知识库；会话 header 显示“N 个知识库”。

### B4 辅助收尾

- `GET /usage/recent` 返回最近调用与 trace 状态；用量页新增“最近调用”表。
- 全局搜索新增模型（公共广场）与插件。
- `/help` 帮助中心与门户导航/页脚入口。

## 迁移

`alembic/versions/a1b2c3d4e5f6_p6_b.py`：

- `knowledge_bases.description`
- `documents.tags`
- `chat_attachments`
- `conversation_knowledge_bases`
- Postgres：`usage_events.message_id` 外键改为 `SET NULL`，回填现有会话 KB 关联

已在真实 Postgres 上执行并验证：

- `alembic_version = a1b2c3d4e5f6`
- `usage_events_message_id_fkey` 的 `confdeltype = n`（SET NULL）
- `chat_attachments`、`conversation_knowledge_bases`、`knowledge_bases.description` 存在

## 验证

- 后端：`ruff check` 通过；新增 `tests/test_p6_b.py` 7 个用例通过；全量测试分组执行全部通过（并发工作流用例首次偶发超时，单独重跑与整组重跑均通过）。
- 前端：`npm run typecheck`、`npm test -- --run`（13 文件 / 33 用例）、`npm run build`、`npm run test:e2e`（7 用例）通过。
- 容器：`api` 启动时迁移成功、`/readyz=200`；`/attachments` 未认证返回 401。

## 边界

- 图片附件不支持 Agent 模式；`auto` 路由不接受图片，需显式选择 vision 模型。
- 多 KB 检索使用第一个 KB 的 embedding/rerank 配置；跨不同 embedding 模型的 KB 不做分组召回。
- 附件正文进入 prompt 前按 20k/40k 字符截断；每轮最多 4 张图片、单图 4MB。
- 编辑提问的截断为硬删除消息；`usage_events` 保留（账本只追加）。