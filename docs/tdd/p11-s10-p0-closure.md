# P11-S10：剩余 P0 收尾

日期：2026-11-24

## 范围

- A-P0-2：Agent 模板与模板入口（验证既有实现并标记完成）。
- A-P0-4：项目多 Agent 关联、项目文件关联与 `project_files` 工具。
- K-P0-5：处理版本对比报告。
- M-P0-6：记忆检索过滤维度。

## A-P0-2

P11-S4 已提供：

- `GET /workflows/catalog?kind=agent` 返回 `assistant` / `research` / `reviewed` 三个模板。
- `POST /agents/from-template` 原子创建 Agent + 工作流版本。
- `/studio` 列表展示模板并支持命名后创建。

本轮新增回归测试，确认目录与创建链路可用；无代码变更。

## A-P0-4

数据模型（迁移 `f1a2b3c4d5e6`）：

- `project_agents(project_id, agent_id, added_by_user_id, created_at)`，`(project_id, agent_id)` 唯一。
- `project_documents(project_id, document_id, added_by_user_id, created_at)`，`(project_id, document_id)` 唯一。

API：

- `GET/POST/DELETE /projects/{id}/agents`
- `GET/POST/DELETE /projects/{id}/files`
- 读：工作区成员；写：项目所有者或工作区 owner。
- 创建/更新项目默认 Agent 时自动建立关联。
- 项目存在关联 Agent 时，创建会话显式选择未关联 Agent 返回 `422 agent_not_in_project`。

工具：

- 新增 `project_files`：列出项目附件，或按 `document_id` 读取附件前 8 个 chunk（截断 3500 字符）。
- 项目上下文中的自定义 Agent 会话与工作流 Agent 节点自动加入该工具。
- 未绑定项目、未关联文档、跨工作区文档均返回类型化错误。

前端：

- 项目详情新增“项目 Agent”“项目文件”区块，支持关联/移除。
- 新对话页选中项目时，Agent 选择器只展示项目关联 Agent。

## K-P0-5

`GET /knowledge-bases/{id}/processing/versions/compare`：

- 以已应用处理版本的文档为样本，最多读取 5000 个 chunk。
- 每个版本输出：文档数、块数、平均/最小/最大字符、元数据/父块/关键词/摘要覆盖率、重复块比例。
- 知识库“评估与优化”页新增“处理版本对比”表格。

边界：不重新运行处理工作流，也不比较未应用草稿；比较的是已应用输出。

## M-P0-6

`GET /memories` 与 `select_memories` 新增过滤：

- `created_after` / `created_before` / `updated_after` / `updated_before`
- `source_type`（manual/chat/project/workflow_run/document）
- `used_in`（chat/agent/workflow）
- `has_relations`
- `related_to`（一跳关系）

前端全部记忆页新增来源、使用场景、创建日期与“仅有关联”筛选。

## 验证

- `ruff check app tests alembic` 通过。
- 全量 `pytest -n auto` 通过；新增 `tests/test_p11_s10_p0_closure.py`（4 个测试）。
- `npm run typecheck`、`npm test`（43）、`npm run build` 通过。

## 边界

- 项目文件工具只读已入库 chunk，不做文件名向量检索。
- 项目 Agent 关联是选择约束：项目一旦有关联 Agent，显式选择其他 Agent 会被拒绝；未关联项目的旧项目保持原有行为。
- 处理版本对比不重新执行处理配置；未应用草稿不参与。
- 记忆关系过滤只做一跳，不做多跳路径查询。
- 外部数据源、多模态、实体消歧、实时协同与市场计费仍不做。