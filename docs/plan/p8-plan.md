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
- 循环、运行中人工审核、HTTP/代码/数据库/MCP、长期记忆后置。

## 切片

| 切片 | 内容 |
|---|---|
| P8-S0 | Agent 字段、收藏、发布快照、节点 v2、节点目录、迁移 |
| P8-S1 | `/studio` 独立工作台：配置、画布入口、发布/复制 |
| P8-S2 | React Flow 画布：节点面板、配置面板、保存/版本、试运行 |
| P8-S3 | AI Builder：生成、修改、缺口提示、应用前确认 |
| P8-S4 | 最小广场：公开列表/详情、收藏、复制、统计 |
| P8-S5（后置） | 人工审核、循环、HTTP/MCP、记忆、评价 |

## 边界

- 敏感插件在无会话确认上下文的运行中继续返回 `plugin_confirmation_required`。
- 公开 Agent 的体验/复制必须使用访问者权限，不得借用作者凭证。
- 复制工作流时清除 KB、Agent 绑定与发布字段，保留可编辑结构。