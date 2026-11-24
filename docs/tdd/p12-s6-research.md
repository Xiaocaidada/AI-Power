# P12-S6 深度研究

日期：2026-11-24
状态：已完成（深度研究 MVP）

## 目标

在统一聊天模式上提供可确认、可暂停、可恢复、可复用的深度研究任务：计划 → 多阶段检索 → 交叉验证 → 结构化报告 → 追问/局部重生成。

## 实现

### 任务模型

复用 `chat_tasks`，新增 `kind="research"`，不新增表：

- `input`：provider/model、thinking_level、topic、questions、scope（web/knowledge/hybrid）、kb_ids、search_provider_id、language、max_steps。
- `plan`：`confirmed`、`status`、步骤数组（`title/query/status/summary/source_indexes`）。
- `checkpoint`：`completed_steps`、`sources`、`step_outputs`、`llm_calls`、`tokens`、`message_id`。
- `result`：`report`、`sections`、`agreements`、`conflicts`、`sources`、`step_summaries`、`followups`、`token_usage`。

### 流程

1. `POST /research/tasks`：LLM 生成 3–N 步计划（失败时使用确定性模板），状态 `waiting_approval`，不检索。
2. `PATCH /research/tasks/{id}/plan`：仅计划未确认且仍待确认时可编辑。
3. `POST /research/tasks/{id}/confirm`：写入 `plan.confirmed`，状态转 `queued` 并入队。
4. Worker 每步：
   - 按 scope 调用网页搜索（编号来源）和/或知识库检索；
   - 去重来源，写入 `research_sources` 事件；
   - LLM 提取摘要与 claims，写入 `research_step_completed`。
5. 全部步骤后做交叉验证，生成背景/方法/发现/对比/结论五节报告与来源列表。
6. 若任务绑定会话，自动追加一条 `deep_research` 助手消息并持久化网页来源。
7. `research_report_ready` → `task_completed`。

### API

- `POST /research/tasks`（201）
- `GET /research/tasks`（仅 research）
- `GET /research/tasks/{id}`
- `PATCH /research/tasks/{id}/plan`
- `POST /research/tasks/{id}/confirm`
- `POST /research/tasks/{id}/followup`
- `POST /research/tasks/{id}/sections/{section}/regenerate`
- `POST /research/tasks/{id}/save-to-knowledge`
- `POST /research/tasks/{id}/save-to-project`
- 控制/事件复用 `/chat-tasks/{id}/pause|resume|cancel|retry|events`

### 聊天模式

`deep_research` 标记为已实现。在会话中发送该模式时：

- 先校验/解析搜索 Provider，未配置返回 422 `search_not_configured`，不发外部请求；
- 自动创建研究任务并持久化计划；
- SSE 返回 `meta → stage(research_planning) → research_plan → delta → done`；
- 助手消息通过 `mode_meta.research_task_id` 关联任务，前端可跳转研究页。

### 限制

- 步骤数默认 5，最多 8。
- 每步来源上限 `RESEARCH_STEP_SOURCE_LIMIT`（5），总来源上限 `RESEARCH_MAX_SOURCES`（30），超限明确失败 `research_source_limit`。
- LLM 调用上限 `RESEARCH_MAX_LLM_CALLS`（10）→ `research_llm_limit`。
- Token 上限 `RESEARCH_MAX_TOTAL_TOKENS`（150000）→ `research_token_limit`。
- 失败保留 checkpoint；重试从下一步继续，已完成步骤不重复。

### 复用

- 报告通过 `reuse.save_generated_document` 走正常入库队列，按内容哈希去重。
- 保存到项目时复用项目 KB（`projects.kb_ids`）并建立 `project_documents` 关联；项目无 KB 时要求显式选择。

## 测试

`tests/test_p12_s6_research.py`：

- 计划确认后才执行（确认前无检索、无报告）。
- 计划编辑与确认后锁定（409 `plan_locked`）。
- 两步研究完成：报告五节、来源编号、步骤摘要、事件顺序。
- 会话内自动追加 `deep_research` 消息并持久化网页来源。
- 报告追问。
- 保存到知识库与重复去重。
- 跨用户 404。
- LLM 调用上限与来源上限返回类型化失败并保留 checkpoint。
- 聊天模式 `deep_research` 创建计划并返回 `research_plan` SSE。

## 边界

已解决：

- 计划未确认不执行。
- 每个步骤有状态、来源与事件。
- 搜索/检索/模型失败有类型化错误码，不伪造来源。
- 刷新/断线可通过任务详情与事件回放恢复。
- 暂停/取消/重试沿用长任务运行层。
- 报告可追问、可局部重生成、可保存到知识库/项目。

后续切片/边界：

- 逐文件固定“参考文件”（当前通过知识库范围检索，不按 document_id 锁定）：如需精确引用某几个文件，后续加 `document_ids` 过滤。
- 不抓取需要登录的页面，不绕过付费墙；只使用搜索 API 返回的标题/摘要/URL，不抓正文。
- 多 Provider 并聚合来源未实现（与 P12-S2 边界一致，单次任务使用一个搜索 Provider）。
- 报告追问不创建长任务，同步调用模型。

明确不做（真实外部集成）：

- 不伪造搜索结果或来源 URL。
- 不自动发布/发送报告到外部系统。