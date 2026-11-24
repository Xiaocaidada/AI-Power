# P12 网页模型对话拓展规划

日期：2026-11-24
状态：P12-S1 至 P12-S8 已完成，S9–S10 未开工

## 1. 目标

在现有对话、Agent、MCP/Plugin、知识库、记忆与工作流能力上，把网页版对话升级为综合 AI 工作空间：

- 统一对话模式：普通、网页搜索、深度研究、学习、Agent。
- 网页搜索支持多个 Provider，由用户配置自己的 API Key。
- 长任务支持计划、进度、暂停/继续、取消、刷新恢复。
- 对话成果可保存为知识库文档、代码片段、任务清单、分享链接。
- 模型能力真实门控：不支持的能力可展示但不可选，不静默降级。
- 外部依赖能力（图片生成、语音、实时语音、OAuth 应用）单独成轨，不伪造成功。

## 2. 已确认决策

1. 网页搜索提供多个 Provider：Tavily、Brave、Serper、SearXNG；用户自行配置 API Key / Base URL。
2. 思考等级可以全部展示；当前模型不支持时置灰、不可选，后端二次校验。
3. 深度研究、学习模式、成果复用按建议优先级推进。
4. 多模态先保留现有图片理解与文件处理；图片生成、语音、实时语音延后。
5. 分享链接 MVP 默认工作区可见、可撤销；公开分享后续再加。

## 3. 现有基础

| 能力 | 已有 | P12 复用方式 |
|---|---|---|
| 对话/SSE | 文本流、引用、终止、重试 | 扩展 mode/stage/source 事件 |
| Agent | 自定义 Agent、工具、MCP、Plugin、记忆 | 增加计划、审批、暂停/继续 |
| 工作流/协作 | 异步 run、事件回放、取消、检查点 | 长任务运行层参考其模式 |
| 知识库 | 多 KB、URL/HTML 导入、处理画布 | 搜索来源、保存回答为文档 |
| 记忆 | 提取、注入、反馈、评测 | 对话成果提取记忆 |
| 评测 | 检索/回答指标 | 研究/学习效果可复用评测思路 |
| 导出 | Markdown/JSON | 扩展成果导出与分享 |

## 4. 总体架构

### 4.1 统一模式

`ChatMode`：

```text
chat | web_search | deep_research | study | agent
```

模式不是独立聊天系统，统一复用：

- 输入框与模式选择器；
- 附件体系；
- 消息流与消息操作；
- 会话历史；
- 模型/Provider 选择。

### 4.2 能力组合

采用“主模式 + 能力参数”：

- `messages.mode`：主模式。
- `messages.mode_meta`：
  - `thinking_level`: `fast|standard|deep`
  - `search_provider_id`
  - `research_task_id`
  - `study_session_id`
  - `agent_task_id`
  - `web_search_enabled`

主模式决定执行形态，能力参数允许组合，例如：

- 学习模式 + 网页搜索；
- 深度研究 + 深度思考；
- Agent + MCP/Plugin。

### 4.3 两种执行模型

| 类型 | 场景 | 机制 |
|---|---|---|
| 短任务 | 普通对话、网页搜索、学习回答 | 现有聊天 SSE |
| 长任务 | 深度研究、Agent 多步骤 | `chat_tasks` + `chat_task_events`，支持回放/重连/暂停 |

长任务不占用单条 HTTP SSE，避免刷新、断线、暂停不可恢复。

### 4.4 能力注册表

Provider/Model 能力声明：

- `tools`
- `vision`
- `reasoning_levels`（fast/standard/deep）
- `audio_input` / `audio_output`
- `image_generation`

前端只允许选择当前模型真实支持的能力；后端二次校验并返回类型化错误。

## 5. 数据模型规划

### 5.1 模式与消息

- `conversations.default_mode`
- `messages.mode`
- `messages.mode_meta` JSON
- `messages.web_source_count`（可选冗余）

### 5.2 搜索 Provider

`search_provider_configs`：

- `id`
- `workspace_id`
- `owner_user_id`
- `provider`: `tavily|brave|serper|searxng`
- `name`
- `base_url`（SearXNG/自定义）
- `api_key_encrypted` / `key_hint`
- `max_results`
- `timeout_seconds`
- `enabled`
- `shared`
- `is_default`
- `created_at` / `updated_at`

API：

- `GET/POST /search-providers`
- `PATCH/DELETE /search-providers/{id}`
- `POST /search-providers/{id}/test`
- `POST /search-providers/{id}/default`

密钥使用现有 Provider 加密方式，永不明文返回。

### 5.3 网页来源

`message_web_sources`：

- `message_id`
- `citation_index`
- `title`
- `site`
- `url`
- `snippet`
- `published_at`
- `retrieved_at`
- `provider_config_id`

与知识库 `message_citations` 分开，避免混淆文档引用和网页引用。

### 5.4 长任务

`chat_tasks`：

- `id`
- `workspace_id` / `user_id` / `conversation_id`
- `kind`: `research|agent`
- `status`: `queued|running|waiting_approval|paused|completed|failed|cancelled`
- `input`
- `plan` JSON
- `checkpoint` JSON
- `result` JSON
- `error_code`
- `created_at` / `started_at` / `finished_at`

`chat_task_events`：

- `task_id`
- `seq`
- `event`
- `payload`
- `created_at`

提供 `after` / `Last-Event-ID` 回放与 tail，复用现有 run event 经验。

### 5.5 学习模式

`study_sessions`：

- `workspace_id` / `user_id` / `conversation_id`
- `topic`
- `level`: `beginner|intermediate|advanced`
- `mode`: `explain|guided|practice|quiz|review`
- `goals`
- `kb_ids`
- `status`
- `mastery` JSON（已掌握/薄弱知识点）

`study_attempts`：

- `session_id`
- `question` JSON
- `answer`
- `score`
- `feedback`
- `created_at`

### 5.6 成果复用

- `code_snippets`：workspace/user/project、language、title、code、source message。
- `tasks` 或 `project_tasks`：标题、状态、优先级、来源消息、项目。
- `conversation_shares`：token hash、scope、expires_at、revoked_at、created_by。
- 回答保存为 KB 文档：复用现有 ingestion，新增“生成文档”来源路径，不伪造外部文件。

## 6. SSE 事件扩展

在现有 `meta/citation/delta/usage/done/error` 基础上增量增加：

- `mode`：当前模式与能力。
- `stage`：搜索/研究/学习/Agent 阶段。
- `web_source`：单条网页来源。
- `task_start` / `task_update` / `task_end`：长任务。
- `approval_required` / `approval_resolved`。
- `thinking`：思考等级与状态，不输出隐藏推理链。
- `artifact`：生成的文档/代码/任务清单/报告。

现有事件语义不变，旧客户端可忽略新事件。

## 7. 切片规划

### P12-S1：统一模式与能力框架

范围：

- `ChatMode`、`conversations.default_mode`、`messages.mode/mode_meta`。
- 输入框模式选择器与状态展示。
- Provider/Model 能力声明与前后端门控。
- 思考等级展示、禁用、不可选。
- 统一消息记录：模式、模型、思考等级。

验收：

- 旧会话默认 `chat`。
- 不同模式可切换并持久化。
- 不支持能力展示但不可选。
- 跨工作区/无权访问 404。
- 前后端测试与构建通过。

边界：S1 不执行网页搜索/研究/学习/Agent 长任务，只建立框架与状态。

### P12-S2：网页搜索多 Provider（已完成）

范围：

- 搜索 Provider 配置中心与加密 Key。
- Tavily/Brave/Serper/SearXNG 适配器。
- 搜索模式：关键词生成、多轮搜索、结果去重。
- 网页来源引用、末尾来源列表、点击打开。
- 搜索阶段事件、停止、重试、追问。
- 每请求记录实际 Provider。

验收：

- 未配置 Key 时明确提示，不发外部请求。
- Provider 测试连接有类型化结果。
- 搜索结果有标题/站点/URL/摘要/时间。
- 来源不可达时明确标注。
- 外部调用在测试中使用 mock，不真实联网。
- 搜索过程可停止、重试。

边界：MVP 一次请求使用一个 Provider；多 Provider 聚合并发后续增强。

### P12-S3：学习模式（已完成）

范围：

- 学习会话、难度、目标、资料。
- 讲解/引导/练习/测验/复习五种方式。
- 单选、多选、判断、填空、问答（MVP 可先 3 类）。
- 自动判分、错题解释、相似练习。
- 掌握度与复习建议。

验收：

- 学习会话可恢复。
- 测验题结构化、可判分。
- 错题有解释与建议。
- 模式切换保留上下文。
- 不把普通聊天自动当作学习记录。

边界：不做班级、作业、课程体系；不做完整 LMS。

### P12-S4：对话成果复用（已完成）

范围：

- 回答保存为 KB 文档（生成来源，复用 ingestion）。
- 代码块识别与代码片段保存。
- 任务清单提取与保存到项目。
- 对话/多轮导出增强。
- 工作区可见、可撤销分享链接。
- 保留原始消息/附件来源。

验收：

- 保存回答后 KB 文档可检索。
- 代码片段有语言/标题/来源。
- 任务清单可标记状态。
- 分享链接可撤销、越权不可读。
- 导出保留代码块/表格/引用结构。

边界：公开分享、PDF 导出后续再做；分享 MVP 不做匿名公开。

### P12-S5：长任务运行层（已完成）

范围：

- `chat_tasks` / `chat_task_events`。
- 创建、查询、取消、暂停、继续。
- 事件回放/tail/重连。
- 检查点与失败重试。

验收：

- 刷新/断线后恢复任务状态。
- 暂停在安全边界生效。
- 取消幂等。
- 事件 `seq` 单调。
- 不重复执行已完成步骤。

### P12-S6：深度研究（已完成）

范围：

- 研究目标、范围、参考文件。
- 研究计划生成、查看、编辑、确认。
- 多阶段搜索与资料提取。
- 一致/冲突标注、交叉验证。
- 研究时间线、暂停/继续/取消。
- 结构化报告、来源列表、保存到 KB/项目。
- 报告追问与局部重生成。

验收：

- 计划确认后才执行。
- 每个研究步骤有来源与状态。
- 报告包含背景、方法、发现、对比、结论、来源。
- 步骤/搜索/Token 有上限，超限明确失败。
- 失败可重试，已完成步骤不丢失。

边界：不抓取需要登录的网页；不绕过付费墙；不伪造来源。

### P12-S7：Agent 执行升级（已完成）

范围：

- 执行计划生成与展示。
- 多步骤工具调用时间线。
- 高风险操作审批（发送、修改、删除、发布、账户/支付）。
- 暂停/继续、失败步骤重试。
- 任务成果输出（报告/文件/代码/任务总结）。

验收：

- 未审批的高风险操作不执行。
- 审批可拒绝、可取消。
- 暂停/继续在工具边界生效。
- 工具调用与结果可追溯。
- 失败不丢已完成步骤。

边界：审批只覆盖有外部影响的操作；纯查询工具不打断。

### P12-S8：思考模式真实生效（已完成）

范围：

- 模型思考等级能力声明。
- 快速/标准/深度映射到 Provider 真实参数。
- 消息记录与 UI 展示。
- 不支持等级：展示、置灰、不可选、后端 422。

验收：

- 不同模型展示不同可用等级。
- 不支持时不会静默降级。
- 历史消息可查看当次等级。
- 不展示隐藏推理链，只展示整理摘要。

### P12-S9：多模态扩展（外部依赖）

范围：

- 图片生成/编辑适配器。
- 语音识别 STT、语音合成 TTS。
- 实时语音对话（WebSocket/WebRTC，单独阶段）。
- 能力门控与密钥配置。

边界：

- 需要真实图像/语音模型服务与密钥。
- 未配置时明确提示，不伪造生成/播放成功。
- 实时语音不纳入首批。

### P12-S10：Skills 与外部应用

范围：

- 平台内 Skills 定义、启用、匹配、执行记录。
- Google Drive/Gmail/Calendar/GitHub 等 OAuth 连接器。
- 授权、撤销、权限范围、调用历史。
- 高风险操作审批。

边界：

- 需要 OAuth 应用注册、回调域名、审核与 Token 加密。
- 未授权时明确提示。
- 不在代码/日志/回复中输出真实密钥。

## 8. 推荐顺序

第一批（形成完整体感）：

1. P12-S1 统一模式与能力框架
2. P12-S2 网页搜索多 Provider
3. P12-S3 学习模式
4. P12-S4 对话成果复用

第二批（长任务与执行）：

5. P12-S5 长任务运行层
6. P12-S6 深度研究
7. P12-S7 Agent 执行升级
8. P12-S8 思考模式生效

第三批（外部能力）：

9. P12-S9 多模态扩展
10. P12-S10 Skills 与外部应用

## 9. 测试策略

- 后端：pytest；搜索/语音/OAuth 全部 mock，不在 CI 真实联网。
- 前端：Vitest 覆盖模式选择、能力门控、成果操作。
- E2E：模式切换、搜索引用、学习测验、成果保存、分享撤销、任务回放。
- 迁移：每个切片独立 Alembic revision，验证 upgrade/downgrade。
- 外部能力：提供手动冒烟脚本，使用用户自己的 Key，CI 不依赖外部账号。

## 10. 明确不做

- 不直接抓取 Google/Bing 结果页；使用合规搜索 API 或自托管 SearXNG。
- 不伪造外部发送/支付/发布成功。
- 不展示模型隐藏推理链。
- 不在未授权时执行外部写操作。
- 不做真实支付、短信、邮件、KYC、物流等业务集成。
- 不在首批做公开匿名分享、实时语音、外部 OAuth 应用。

## 11. 风险与控制

| 风险 | 控制 |
|---|---|
| 搜索成本/限流 | 每 Provider 限额、超时、结果数上限、错误重试 |
| 深度研究成本失控 | 最大步骤/查询/Token/时长，超限失败 |
| 外部 Key 泄露 | Fernet 加密、掩码返回、不写日志 |
| 网页内容不可信/注入 | 声明为不可信数据、限制抓取、来源标注 |
| 长任务丢失 | 检查点、事件回放、幂等步骤 |
| 模式过多导致 UI 混乱 | 统一选择器与状态栏，不新建独立聊天页 |
| 能力虚假可用 | 能力注册表 + 后端二次校验 |
| 分享泄露 | 默认工作区、可撤销、过期时间 |

## 12. 验收基线

每个 P12 切片至少满足：

- 新增/修改 API 有权限与跨租户 404 测试。
- 外部能力未配置时有类型化错误，不伪造成功。
- 前端有加载/空态/错误态/禁用态。
- SSE 新事件不破坏旧事件契约。
- 长任务支持刷新恢复与取消幂等。
- 全量 `ruff`、`pytest -n auto`、`npm run typecheck`、`npm test`、`npm run build` 通过。
- 涉及迁移时实际部署并验证表/列存在。