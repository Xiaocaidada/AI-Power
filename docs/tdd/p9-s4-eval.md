# P9-S4 知识评估与优化

## 目标

在既有 `eval_*` 上扩展知识检索评估，不另建评测平台：

- 按检索流程版本运行评测，与内置检索可对比。
- 新增 Precision@5/10、文档级 Recall@5/10、NDCG@5/10。
- 运行分析：节点耗时/失败、最差问题、未命中问题、最慢问题。
- 基于评测结果生成 AI 优化建议；应用创建新版本并绑定 KB，可回滚。

## 数据模型

- `eval_runs.retrieval_workflow_version_id`：本次评测使用的不可变检索流程版本。
  `config.retrieval_workflow` 同时保存 `{workflow_id, version, name}` 快照。
- `eval_run_items` 新增：
  - `precision_at_5/10`、`recall_at_5/10`（文档级）、`ndcg_at_5/10`
  - `retrieval_mode`（`workflow|builtin`）
  - `retrieval_trace`（节点/类型/状态/耗时/条数，单题上限 50 条）
- `knowledge_optimizations`：
  - 归属：`workspace_id/kb_id/eval_run_id/workflow_id/base_version_id`
  - 建议：`summary/rationale/suggestions/proposed_definition/diff/metrics_snapshot`
  - 生命周期：`proposed|applied|reverted|dismissed`
  - 应用/回滚：`applied_version_id/previous_binding_version_id/applied_at/reverted_at`

## 指标

`app/services/knowledge/metrics.py`：

- `precision_at_k`：top-k 中相关文档数 / k（文档去重）。
- `recall_at_k`：top-k 覆盖的相关文档数 / 标注相关文档数。
- `ndcg_at_k`：二值相关性 DCG / IDCG。
- `aggregate_retrieval_traces`：按节点类型聚合 runs/failures/avg_ms/avg_count。
- `metric_delta`：版本对比的 base/candidate/delta。

原有 `recall_at_1/3/5` 保持“是否命中”语义；文档级召回以
`recall_at_5_docs/recall_at_10_docs` 暴露，避免破坏既有前端与历史运行。

## 评测执行

- `POST /evaluations/runs` 接受 `retrieval_workflow_version_id`：
  - 校验版本存在、属于当前 workspace、workflow `kind=knowledge_retrieval`、
    定义通过线性校验；否则 422 `invalid_retrieval_workflow`。
- `run_evaluation`：
  - 有版本：逐题执行 `run_retrieval_workflow`（`collect_traces=True`），
    排序文档取 `result.chunks`（为空时回退 `selected`）。
  - 无版本：沿用 `retrieve_chunks` 内置路径。
  - 自定义流程异常按题目隔离，写 `error_code`，不失败整次运行。
  - 每题写入 Precision/Recall/NDCG 与节点轨迹；运行级指标聚合节点耗时。
- 答题/LLM-as-judge 逻辑不变；失败题不进入答题。

## 运行分析

`GET /evaluations/runs/{run_id}/analysis`：

- `run`：运行概要（含 metrics/version id）。
- `node_timing`：节点类型维度运行次数、失败数、平均耗时、平均条数。
- `worst_questions`：按 NDCG@5 升序、命中排名兜底的前 10 题。
- `missed_questions`：未命中 / NDCG=0 / 出错的题目前 20 条。
- `slowest_questions`：检索延迟最高的前 10 题。

## AI 优化

`app/services/knowledge/optimizer.py`：

- 输入：已完成的评测、指标、最差问题、节点耗时、当前检索流程定义与节点清单。
- 模型返回 JSON：`summary/rationale/suggestions/definition?`。
- `definition` 必须通过 `validate_knowledge_retrieval`，失败回喂修复最多 3 次。
- 仅评测了内置检索时只产出建议，不生成可应用定义。
- 使用 `ModelCompletion`，来源 `knowledge_eval`，写入统一用量账本。

端点（`/knowledge-bases/{kb_id}/optimizations`）：

- `POST`：生成建议（需 `eval_run_id/provider_id/model`）。
- `GET`：列表；`GET /{id}`：含 `proposed_definition/diff` 详情。
- `POST /{id}/apply`：校验定义 → 创建新不可变 `workflow_versions` →
  绑定 `knowledge_bases.retrieval_workflow_version_id` → 记录应用审计。
- `POST /{id}/rollback`：仅当当前绑定仍等于应用版本时，恢复应用前绑定。
- `POST /{id}/dismiss`：忽略建议。

应用/回滚都只改绑定，不删除历史版本；已应用建议再次应用返回 409。

## 前端

- 新页面 `/knowledge/:id/evaluation`，知识库详情页新增“评估优化”入口：
  - 选择评测集、检索流程版本（或内置）、Top-K/候选数/混合/重排后启动。
  - 运行历史：状态、模式、版本；勾选两次运行进行指标对比。
  - 运行详情：指标卡、节点耗时、最差/未命中问题、逐题 P@5/R@5/NDCG@5。
  - AI 优化：选择已完成运行与模型，生成建议；查看理由/建议/diff，
    应用（确认后绑定新版本）、忽略、回滚（确认后恢复原绑定）。

## 验证

- `ruff check .` 通过；`pytest -n auto` 全量通过。
- 新增 `tests/test_p9_s4.py`：
  - 指标纯函数与轨迹聚合/对比。
  - 绑定检索版本的评测写入 Precision/Recall/NDCG、workflow 模式、节点轨迹。
  - 分析接口返回节点耗时、最差/最慢问题。
  - 优化建议生成、列表、应用（新版本 + 绑定）、回滚（恢复原绑定）。
  - 跨 KB 运行 404。
- 前端 `npm run typecheck`、33 个 Vitest、`e2e/p9.spec.ts` 3 个 Playwright、构建通过。
- 迁移 `a4b5c6d7e8f9` 已在真实 Postgres 执行并核对。

## 边界

- 评测仍为 Arq 异步任务；大批量题目按顺序执行。
- 优化建议仅针对检索流程；内置检索只能得到文字建议。
- 应用优化不会自动重新评测；建议在应用后再次运行评测验证。
- 回滚仅在 KB 绑定未被其他操作改变时生效（`binding_changed` 409）。
- 节点轨迹/问题列表有截断，完整数据保留在 `eval_run_items`。