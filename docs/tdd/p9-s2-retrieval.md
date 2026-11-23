# P9-S1.5/S2 上传自动处理与知识检索画布

## S1.5 绑定流程自动执行

- 文档上传/重新处理时，若 KB 已绑定 `process_workflow_version_id`：
  - `ingest_document` 创建一条 `workflow_runs`（kind 由 workflow 决定），调用
    `execute_knowledge_process_run` 执行已发布的处理流程。
  - 成功后调用 `apply_knowledge_run`，事务性替换 chunks/embeddings，写
    `documents.process_version_id`，文档置为 `ready`。
  - 失败返回处理错误码，沿用现有 ingestion 重试/失败状态机。
- 重新处理绑定流程时保留旧 chunks，直到新运行应用成功；未绑定 KB 仍使用原
  内置解析/切片/embedding 路径。
- 测试：上传即执行绑定流程并应用；reprocess 再次执行；文档版本字段写入。

## S2 知识检索画布

### 节点与校验

- `start`、`rewrite_query`、`vector_search`、`lexical_search`、
  `hybrid_search`、`rerank`、`top_k`、`context`、`output`。
- 与处理画布一致的单链校验：唯一 start/output、一进一出、无分支/环。
- `GET /workflows/catalog?kind=knowledge_retrieval` 返回节点目录与两套模板
  （混合检索+重排、向量检索）。

### 执行

- 新增检索原语（`app/services/retrieval.py`）：
  - `vector_search_chunks`
  - `lexical_search_chunks`
  - `hybrid_search_chunks`（RRF）
  - `rerank_chunks`（KB Reranker，失败回退）
- `run_retrieval_workflow`：线性执行节点，维护 query/chunks/context/citations；
  `rewrite_query` 使用平台 Provider + `ModelCompletion`（source
  `knowledge_retrieval`）；`context` 使用 `fit_context`。
- 支持节点轨迹（node/type/status/count/duration）用于画布测试。

### 绑定与调用

- KB 新增 `retrieval_workflow_version_id` 绑定：
  - `GET/PUT /knowledge-bases/{id}/retrieval/binding`
  - `POST /knowledge-bases/{id}/retrieval/test`
- `retrieve_with_diagnostics` 在解析 KB 后检查绑定版本：
  - 有绑定：执行自定义检索流程，成功返回 `mode=workflow`。
  - 流程异常：记录指标并回退内置向量/混合检索，不阻断对话。
  - 空结果按流程结果返回，不强制回退。
- 因此普通对话、Agent `kb_search`、检索测试与评估共享同一自定义检索路径。

### 前端

- 新页面 `/knowledge/:id/retrieval`：
  - 检索画布（复用 React Flow/节点配置）
  - 模板创建、保存版本、绑定 KB
  - 检索测试：查询、召回片段（向量/词法/重排排名）、上下文、耗时、节点轨迹
- 知识库详情页新增“检索画布”入口。
- Playwright 覆盖处理画布与检索画布的渲染。

## 验证

- 后端 `ruff` 通过；`pytest -n auto` 全量通过。
- `tests/test_p9.py` 7 个用例：处理画布、非法分支、绑定上传/reprocess、检索
  画布绑定与聊天检索路径、非法检索分支、失败检索流程回退。
- 前端 typecheck、33 个 Vitest、15 个 Playwright、生产构建通过。

## 边界

- 检索流程为单链；无多查询分支/条件。
- `rewrite_query` 使用平台 Provider（用户私有 Provider 不作为检索改写默认）。
- 自定义检索失败静默回退并记录 warning/指标；画布测试会直接显示错误。
- 检索流程不做节点级持久化运行记录（测试接口同步返回轨迹）。
- 上传自动处理目前同步在 ingestion job 内执行；大文档会占用 worker 时间。