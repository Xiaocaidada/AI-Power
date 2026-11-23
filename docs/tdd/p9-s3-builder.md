# P9-S3 知识画布 AI Builder

## 范围

把现有 Agent Builder 泛化为双知识画布：生成/修改/解释/修复、多轮、diff、缺失资源、失败运行上下文。

## 数据与 API

- `agent_builder_sessions.scope`：`agent | knowledge_process | knowledge_retrieval`。
- 会话创建/列表支持 `scope` 与 `workflow_id`；会话内 agent_id 与 workflow kind
  必须与 scope 匹配。
- 既有接口沿用：
  - `POST /agent-builder/sessions`
  - `GET /agent-builder/sessions?scope=&workflow_id=`
  - `POST /agent-builder/sessions/{id}/messages`
  - `POST /agent-builder/sessions/{id}/apply`
- `/agent-builder/generate` 保持 Agent scope。

## 生成与校验

- 按 scope 注入不同节点清单：
  - Agent：原 manifest。
  - 处理：`knowledge_builder_manifest`（单链、解析/清洗/切片/embedding/索引）。
  - 检索：`retrieval_builder_manifest`（单链、查询改写/检索/重排/Top-K/上下文）。
- 资源目录按 scope 裁剪：处理仅 KB；检索模型 + KB；Agent 全量。
- 模型返回 definition 后按 scope 校验：
  `validate_definition` / `validate_knowledge_process` /
  `validate_knowledge_retrieval`；失败回喂错误修复最多 3 次。
- 缺失资源检查复用 `_missing_resources`：模型对、KB、Agent、MCP。
- `apply` 同样按会话 scope 校验，写入 draft 与消息历史。
- 失败修复复用 `build_run_context`：处理画布可传运行 `run_id`，读取节点错误摘要。

## 前端

- `KnowledgeBuilderPanel`（scope/workflow/definition/lastRunId）：
  - 多轮消息、会话复用/新建
  - 构建模型选择（平台 + 个人）
  - 模式：生成/修改/解释/自动修复
  - diff、建议、缺失资源展示
  - 应用前确认；应用后写回画布并自动保存新版本
- 处理画布与检索画布各新增“AI 构建”标签。
- 处理画布在运行页产生 run_id 后启用自动修复；检索画布暂无持久 run，隐藏修复模式。

## 验证

- 后端 `ruff` 通过；`pytest -n auto` 全量通过。
- `tests/test_p9.py` 增加 scoped builder 用例：处理会话生成/应用、检索会话解释、
  workflow kind 不匹配返回 422。
- 前端 typecheck、33 个 Vitest、15 个 Playwright、生产构建通过。
- 迁移 `f3a4b5c6d7e8_p9_s3_builder_scope.py` 已在真实 Postgres 执行。

## 边界

- 处理画布 AI 自动修复依赖已持久化的失败运行；检索测试不持久化 run，暂不提供自动修复。
- 检索改写节点仍需用户配置可用 provider/model；缺失资源只提示不虚构。
- AI 应用只修改画布草稿并保存新版本，不改已发布版本。
