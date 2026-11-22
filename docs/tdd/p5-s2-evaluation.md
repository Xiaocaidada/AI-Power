# TDD Evidence — P5-S2: 评测平台与 LLM-as-judge

- **Date:** 2026-11-22
- **Scope:** 评测数据集/题目/运行/题目结果、Arq 评测任务、检索指标、可选答案生成 + LLM-as-judge、导入 50 题 / 20 文档、运行对比、`/evaluation` 前端
- **Source:** [`docs/plan/p5-plan.md`](../plan/p5-plan.md) P5-S2、[`ADR-0020`](../adr/0020-evaluation-platform.md)
- **用户调整（2026-11-22）**：保留 50 题 / 20 文档；加入 LLM-as-judge。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 新增评测 API/服务测试 | `pytest tests/test_evaluations.py -q` | **8 passed** |
| 队列/迁移测试 | `pytest tests/test_queue.py tests/test_migrations.py -q` | **16 passed** |
| 后端全量 | `pytest -q` | **332 passed, 3 skipped**（335 collected） |
| Lint/Format | `ruff check .` / `ruff format --check .` | 通过 |
| 前端单测 | `npm test` | **22 passed** |
| 类型/构建 | `npm run typecheck` / `npm run build` | 通过 |
| E2E | `npm run test:e2e` | **2 passed** |

## Test Specification

| # | What is guaranteed | Test |
|---|---|---|
| 1 | 检索评测算出 Recall@1/MRR，保留每题命中排名与 Top 文档 | `test_retrieval_evaluation_persists_metrics_and_items` |
| 2 | 可选答案生成 + LLM judge 落库，聚合平均分/及格率/忠实率 | `test_evaluation_supports_llm_as_judge` |
| 3 | 导入 bundle 时 filename 映射到 KB 文档，未知文件 422 | `test_dataset_import_maps_filenames_to_kb_documents` |
| 4 | 数据集、运行、对比均 workspace 隔离 | `test_dataset_and_run_are_workspace_scoped` |
| 5 | 运行前校验相关文档在所选 KB 且 ready | `test_run_rejects_documents_not_ready_in_selected_kb` |
| 6 | 两次运行可按 ID 对比 | `test_compare_runs` |
| 7 | Judge JSON 解析容错与非法值拒绝 | `test_judge_response_parsing_rejects_invalid_payloads` |
| 8 | 空指标、证据命中、judge 聚合计算 | `test_compute_metrics_handles_empty_and_judge_fields` |
| 9 | Arq 评测任务使用稳定 job id | `test_arq_queue_enqueues_evaluation_with_stable_job_id` |
| 10 | 迁移创建 4 张 eval 表 | `test_alembic_upgrade_head_creates_schema` |

## Real 50-question retrieval comparison

数据集：`中文检索评测集 50 题`（20 文档 / 50 题，`eval/dataset.json`），KB 使用默认分块（1000/150），`top_k=5`、`candidate_k=20`。

| 配置 | Recall@1 | Recall@3 | Recall@5 | MRR | 检索 P50 | 检索 P95 |
|---|---|---|---|---|---|---|
| 纯向量 | 0.960 | 1.000 | 1.000 | 0.9767 | 27.17ms | 130.50ms |
| 混合检索 | 0.960 | 1.000 | 1.000 | 0.9767 | 28.08ms | 42.82ms |
| 混合 + 重排 | **0.980** | 1.000 | 1.000 | **0.9900** | 56.71ms | 133.22ms |

结论：50 题集上 Recall@3/5 已饱和；重排把 Recall@1 从 0.96 提升到 0.98、MRR 从 0.9767 提升到 0.9900，代价是 P95 从 ~43ms 升到 ~133ms。混合检索在本数据集上未改变 Top-1（语料较短、词面区分度高），但延迟 P95 更低。

> 运行记录：`vector=01a201d8-894e…`、`hybrid=01a201d8-8960…`、`hybrid+rerank=01a201d8-896f…`（本地演示库）。

## Real LLM-as-judge check

- 知识库：`P5 检索演示 0bc2`（1 篇 refund 文档）
- 问题：`退款多久到账？`
- 配置：hybrid + rerank + answer + judge，本地 `local-qwen`
- 结果：
  - 检索：`hit_rank=1`，检索耗时 `486.6ms`
  - 答案：`退款一般在3个工作日内原路退回；跨境支付可能需要5到7个工作日[1]。`
  - Judge：`score=5`、`faithful=true`、`reason=答案完全准确且被支持`
  - token：prompt `761` / completion `43`；cost `0`（本地模型未定价）

说明：50 题全量 answer+judge 在本地 Qwen 上耗时较长，因此默认关闭；上面的 50 题对比只跑检索指标。

## Frontend / API

- 新增 `/evaluation`：数据集卡片、JSON 导入、运行表单（KB/检索参数/answer/judge/模型）、运行列表与进度、指标卡、题目结果表、两次运行对比。
- 新增 API：
  - `GET/POST /evaluations/datasets`、`POST /evaluations/datasets/import`、`GET/DELETE /evaluations/datasets/{id}`
  - `POST /evaluations/runs`、`GET /evaluations/runs`、`GET /evaluations/runs/{id}`
  - `GET /evaluations/compare?ids=...`
- 新增 `scripts/seed_eval_platform.py`：通过 API 上传 20 篇文档、等待 ready、导入 50 题。
- Arq worker 新增 `run_evaluation_job`；评测 job 使用稳定 id `eval:<run_id>`。

## Known Gaps

- **50 题 Recall@5 饱和**：当前数据集更适合看 Top-1/MRR；扩题留待以后。
- **无 gold answer**：judge 评的是 groundedness/relevance，不是与标准答案的精确一致。
- **Judge 噪声**：本地 Qwen 的评分与理由有模型偏好；不建议跨模型直接比绝对分。
- **默认不跑 judge**：50 题 × answer+judge 在本地太慢；演示建议 1–5 题或更快的模型。
- **无显式取消**：run 在 worker 中执行，暂无取消接口。
- **评测成本未入统一账本**：eval run/item 有 token/cost，但 `usage_events`/预算尚未覆盖（P5-S4）。
- **无 Playwright 覆盖 `/evaluation`**：本片以 API/单测 + 浏览器手工验证为主。