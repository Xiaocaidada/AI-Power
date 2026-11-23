# P9 Knowledge Studio 规划

## 目标

在现有知识库上渐进式建设 Visual Knowledge Studio：

> 知识库管理 → 处理画布 → 检索画布 → AI 构建 → 评估优化

不重建现有上传、解析、切片、embedding、检索与评估能力。

## 架构决策

- 复用 `workflows` / `workflow_versions` / `workflow_runs`，新增 `kind`
  （`agent | knowledge_process | knowledge_retrieval`）。
- 三类画布共享 React Flow 交互，但使用独立节点目录、校验器与执行器。
- 知识处理以文档为单位异步执行；中间结果写 `workflow_artifacts` 与
  `knowledge_chunk_drafts`，用户确认后原子应用到 `chunks/chunk_embeddings`。
- 知识检索后续采用在线同步执行，不进入 Arq 队列；失败回退内置混合检索。
- KB 绑定不可变工作流版本：`process_workflow_version_id` /
  `retrieval_workflow_version_id`；文档记录实际处理版本。
- AI Builder 复用 `agent_builder_sessions` 并扩展 `scope`。
- 评估扩展既有 `eval_*`，不另建评测平台。

## 切片

| 切片 | 内容 |
|---|---|
| P9-S0 | `workflows.kind`、类型化产物/暂存表、KB/文档版本绑定、共享画布抽取 |
| P9-S1 | 知识处理画布 MVP：解析/清洗/固定/Markdown/递归切片/embedding/暂存索引；模板；调试预览；应用 |
| P9-S1.5 | 上传/重新处理自动执行 KB 绑定的处理流程并应用 |
| P9-S2 | 知识检索画布：查询改写、向量/词法/混合检索、rerank、Top-K、上下文、绑定；对话/Agent 调用与降级 |
| P9-S3 | AI 双画布生成/修改/解释/修复、多轮、缺失资源、失败运行上下文（已完成） |
| P9-S4 | 流程版本评估对比、Precision/NDCG、运行分析、AI 优化建议与应用/回滚 |
| P9-S5 | URL/HTML 数据源、文件夹/元数据；Excel/PPT；OCR 单独立项 |
| P9-S6 | 权限/项目联动、配额成本、压测、迁移与可观测性 |

## S1 边界

- 处理流程为单链（start → … → output），暂不支持分支/条件/循环。
- 解析复用现有 PDF/MD/TXT/CSV/DOCX；OCR/PPT/Excel 后置。
- 自定义处理流程通过“试运行 → 应用”或上传自动执行绑定流程生效。
- 应用会替换该文档现有 chunks；未应用运行不影响线上索引。
- 切片调试只展示前若干条/截断文本，完整内容保留在暂存表。