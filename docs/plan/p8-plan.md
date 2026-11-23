# P8 Agent Studio 规划

## 目标

把 Agent 从“配置项”升级为应用平台，围绕一句话主叙事：

> 描述需求 → AI 生成可编辑画布 → 手动微调 → 试跑 → 发布/复制

四层能力收敛到一个独立工作台 `Agent Studio`，广场作为公开发现面。

## 决策

- 复用 `custom_agents` 作为 Agent 应用实体，新增 `mode`、画布绑定、发布快照与统计字段。
- 复用现有 `workflows` / `workflow_versions` / 异步 run 引擎；画布只负责编辑 definition。
- 节点能力清单为单一事实源：`GET /workflows/catalog` 同时服务前端表单、后端校验与 AI Builder Prompt。
- AI Builder 输出完整 definition，服务端校验并自动修复，前端展示缺口后由用户确认应用。
- 发布使用脱敏快照：不含凭证、私有 KB/插件 ID；复制只复制配置并要求重新绑定资源。
- v1 节点：`start`、`llm`、`agent`、`kb_search`、`tool`、`condition`、`parallel`、`join`、`output`。
- 基础节点 v1 交付后，S5c 补齐运行中人工审核、循环、HTTP/MCP、长期记忆、评价与举报；代码/数据库节点仍后置。

## 切片

| 切片 | 内容 |
|---|---|
| P8-S0 | Agent 字段、收藏、发布快照、节点 v2、节点目录、迁移 |
| P8-S1 | `/studio` 独立工作台：配置、画布入口、发布/复制 |
| P8-S2 | React Flow 画布：节点面板、配置面板、保存/版本、试运行 |
| P8-S3 | AI Builder：生成、修改、缺口提示、应用前确认 |
| P8-S4 | 最小广场：公开列表/详情、收藏、复制、统计 |
| P8-S5a | AI Builder 多轮会话、差异预览、解释/优化、失败运行自动修复 |
| P8-S5b | Agent 分级筛选（我的/创建/复制/收藏/发布）、精选与热门、独立体验页、统一运行记录、项目默认自定义 Agent |
| P8-S5c | 人工审核节点与审核收件箱、循环节点、HTTP/MCP 节点、长期记忆、Agent 评价与举报 |
| P8-S5d | 边界补齐：受限 code 节点、只读 database 节点、MCP resources/prompts、记忆向量召回、审核崩溃恢复、评价隐藏 |

## P8-S5c 决策

- 审核节点在运行内阻塞轮询 `workflow_reviews`，不引入新的运行状态；超时/驳回/取消有明确错误码。
- 循环节点为节点内迭代（foreach/repeat + 可选逐次模型调用 + until 条件），不改变 DAG 无环约束。
- HTTP/MCP 复用 SSRF 防护（HTTPS 限制、DNS/私网校验、allowlist、无重定向、超时与响应截断）。
- MCP 仅实现 streamable HTTP 的 `initialize` / `tools/list` / `tools/call`，服务器由管理员维护、凭证加密。
- 长期记忆按 workspace/user 隔离，Agent 显式开启后每次对话注入相关记忆；工作流提供读写节点。
- 评价按用户唯一；评分聚合回写 `custom_agents`；举报由管理员驳回或下架 Agent，均写审计。

## P8-S5d 边界补齐决策

- `code` 节点不是 Python 解释器：只支持 AST 白名单表达式（无导入/属性遍历/循环/函数定义），用于字符串与 JSON 转换。
- `database` 节点只连管理员维护的 PostgreSQL（`postgresql+asyncpg`），只执行单条 SELECT/WITH，绑定参数，只读事务，行数与超时受限。
- MCP 增加 resources/list+read 与 prompts/list+get 节点及管理员发现接口；stdio 与 OAuth 仍后置。
- 记忆写入时生成向量（可关闭），召回复合词法/余弦阈值；嵌入失败自动回退词法。
- 审核节点保存 `workflow_runs.checkpoint`：worker 重启/崩溃后运行进入 `waiting_review`，启动与每分钟 cron 重新入队，从审核节点继续而不重跑已完成节点。
- 管理员可隐藏/恢复单条评价并即时重算评分。

## 边界

- 敏感插件在无会话确认上下文的运行中继续返回 `plugin_confirmation_required`。
- 任意代码执行、stdio MCP、OAuth、子图回边循环不实现。
- 公开 Agent 的体验/复制必须使用访问者权限，不得借用作者凭证。
- 复制工作流时清除 KB、Agent 绑定与发布字段，保留可编辑结构。