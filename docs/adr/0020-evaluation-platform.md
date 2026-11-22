# ADR-0020: 评测平台与 LLM-as-judge

- **Status:** Accepted
- **Date:** 2026-11-22
- **Context:** P5-S1 提供了纯向量、混合检索、可选重排与多种分块/检索参数，但唯一的质量验证仍是 `scripts/eval_retrieval.py`：结果不落库、不能对比配置、不能查看失败题，也无法评估答案质量。用户明确要求保留现有 **50 题 / 20 文档** 数据集，并加入 **LLM-as-judge**。

## Decision

### 数据模型

- `eval_datasets`：workspace 级数据集（名称、描述、软删除）。
- `eval_questions`：问题、相关文档 ID 列表、可选证据短语列表。
- `eval_runs`：数据集 + KB + 配置快照 + 状态/进度 + 聚合指标 + token/成本。
- `eval_run_items`：每题命中排名、RR/证据命中、检索耗时、Top 文档/分块、答案、judge 分数/忠实性/理由/错误。

数据集不绑定 KB；运行时校验所有相关文档都属于所选 KB 且 `ready`，避免“数据集与知识库错配”产生假指标。

### 执行

- `POST /evaluations/runs` 创建 `queued` run 并投递 Arq `run_evaluation_job`；worker 逐题执行并持续更新 `progress_done`。
- 每题检索复用 `retrieve_chunks`，选项来自 run 配置快照（`top_k`、`candidate_k`、hybrid、rerank），保证以后重跑同一配置可复现。
- 指标：
  - Recall@1/3/5、MRR（文档级）；
  - 证据命中率（题目带 `evidence` 时，Top-K chunk 文本包含任一证据短语）；
  - 检索延迟 P50/P95；
  - 可选 judge：`judged_count`、平均分、及格率（≥4）、忠实率、judge 错误数；
  - token/成本（按 `model_catalog` 价格快照）。
- 检索/答案 ProviderError 会让 run 失败并写 `error_code`；judge 失败只记在单题 `judge_error`，不中断整轮。

### LLM-as-judge

- **可选**：`answer_enabled` 生成答案，`judge_enabled` 再评审；两者默认关闭，避免 50 题 × 2 次本地模型调用的耗时与成本。
- 答案生成复用 `build_rag_messages` + `fit_context`，与线上 RAG 一致。
- Judge 输入：问题、检索到的参考段落、生成答案；系统提示要求只输出 JSON：
  `{"score": 1-5, "faithful": boolean, "reason": string}`。
- Judge 只评价 **groundedness / relevance**，不声称与标准答案逐字一致；当前数据集没有 gold answer。
- Judge 模型可单独指定；未指定时与答案模型相同。
- 解析容错：允许 markdown 包裹 JSON；score 支持整数值的浮点；非法分数/缺少 `faithful` 记为 `judge_bad_response`。

### 数据集导入

- `POST /evaluations/datasets/import` 接受现有 `eval/dataset.json` bundle：
  - `documents[].filename` 映射到所选 KB 的同名文档；
  - `questions[].relevant_filenames` 转成 document ID；
  - 缺失文件名、重复文件名返回 422。
- 保留 50 题 / 20 文档，不扩充，避免评测时间过长。
- `scripts/seed_eval_platform.py` 通过公开 API 完成“上传 20 篇文档 → 等待 ready → 导入 50 题”的一键准备。

### 前端

- `/evaluation`：
  - 数据集列表与 JSON 导入；
  - 发起评测（KB、top_k、candidate_k、hybrid、rerank、answer、judge、模型选择）；
  - 运行列表/进度轮询；
  - 指标卡、失败题表、答案与 judge 理由；
  - 勾选两次运行做指标对比（B − A）。

## Consequences

- 评测结果持久化、可对比，面试时可以展示“同一 50 题，vector vs hybrid vs rerank”的真实数据。
- 50 题数据集的 Recall@5 仍会饱和（1.0），Top-1/MRR 更敏感；不宣称它是大规模基准。
- LLM judge 有模型偏好与噪声；分数用于相对比较，不作为绝对真值。当前没有 gold answer，因此 judge 评估的是“答案是否被参考段落支持”，不是“是否等于标准答案”。
- 50 题全量 answer+judge 在本地 Qwen 上可能耗时数十分钟；默认关闭，UI 明确提示，适合小样本或更快模型。
- Run 在 Arq worker 中执行，worker 不可用时保持 `queued`；暂无显式取消（可在后续切片补）。
- 评测成本目前只存在 eval run/item 上，尚未进入 `usage_events` / 预算（P5-S4 统一账本）。

## Alternatives

- **继续用脚本**：无法保存配置快照、对比运行或展示失败题。
- **RAGAS 全量**：指标丰富但依赖 judge 模型、额外依赖与成本，P5 先用自建轻量指标。
- **每题都强制 judge**：本地模型太慢，50 题不可演示；改为可选。
- **用 gold answer 做精确匹配**：现有数据集没有标准答案，且中文生成答案匹配噪声大。
- **扩到 100+ 题**：用户明确要求保留 50/20 以控制时间；后续可作为数据集版本升级。