# 检索评测基线（Recall@k）

- **Date:** 2026-11-21
- **Dataset:** [`eval/dataset.json`](../../eval/dataset.json)（v1）
- **Runtime questions:** [`eval/questions.jsonl`](../../eval/questions.jsonl)（确定性文档 ID）
- **Related:** [`ADR-0003`](../adr/0003-retrieval.md)、[`docs/tdd/p0-s4-retrieval.md`](../tdd/p0-s4-retrieval.md)、[`CAPABILITY.md`](../product/CAPABILITY.md) §2.1 C6

## 1. 数据集设计

| 项目 | 值 |
|---|---|
| 文档数 | 20 |
| 问题数 | 50 |
| 每篇问题数 | 2–3 |
| 文档长度 | 约 120–220 字 |
| 领域 | 客服政策、人事制度、技术运维、公共服务 |
| 标注方式 | 构造时人工指定 `relevant_filenames`，每题至少 1 篇相关文档 |
| 语言 | 中文；部分问题使用同义改写（如「钱多久能退回来」→ 退款时效） |

所有文档与问题均为本项目自写，随仓库分发，不依赖外网抓取、无第三方版权与网络波动问题。

确定性 ID：`document_id_for(filename) = uuid5(EVAL_NAMESPACE, "document/<filename>")`，
因此重建知识库后 `eval/questions.jsonl` 的标签仍然有效；`tests/test_eval_dataset.py` 会校验
数据集完整性以及提交的 `questions.jsonl` 与数据集一致。

## 2. 评测方法

- **指标**：文档级 Recall@k —— 前 k 个检索结果中出现任一相关文档即记为命中。
- **Embedding**：真实 bge-m3（`http://192.168.29.100:8000/v1`，1024 维）。
- **索引**：Postgres 使用 pgvector + HNSW（`vector_l2_ops`）；SQLite 使用 Python 线性打分（测试路径）。
- **流程**：`scripts/seed_eval.py` 通过真实入库流水线（解析 → 分块 → bge-m3）写入 20 篇文档，再运行 `scripts/eval_retrieval.py`。

```bash
# 1) 播种（使用 DATABASE_URL 指向的数据库）
.venv/Scripts/python.exe scripts/seed_eval.py

# 2) 评测
.venv/Scripts/python.exe scripts/eval_retrieval.py \
  --dataset eval/questions.jsonl \
  --user-id 668f2249-d66d-524f-bfbd-c498da940b60 \
  --kb-id fd2b3942-bd84-5b96-a1c0-04fa1041323f \
  --top-k 5
```

## 3. 结果

| 环境 | Recall@1 | Recall@3 | Recall@5 |
|---|---|---|---|
| SQLite（线性打分） | 0.960 (48/50) | 1.000 (50/50) | 1.000 (50/50) |
| Postgres + pgvector + HNSW | 0.960 (48/50) | 1.000 (50/50) | 1.000 (50/50) |

两种方言结果一致，说明 SQL 检索路径与 Python 回退路径行为对齐。

**P0 基线：Recall@5 = 1.000，Recall@1 = 0.960（50 题）。**

## 4. Recall@1 失败样例

两题在 Top-1 未命中，Top-3 已恢复：

| 问题 | Top-1 | Top-2 | Top-3 | 相关文档 |
|---|---|---|---|---|
| 每个月最多能补卡几次？ | `membership.md` 0.8843 | `api-rate-limit.md` 0.8946 | `attendance.md` 0.9164 | `attendance.md` |
| 出差回来的发票最晚什么时候交？ | `invoice.md` 0.8185 | `travel-expense.md` 0.8648 | `attendance.md` 0.9118 | `travel-expense.md` |

分析：

- 第一题被「每月」「次数」等数量词拉向积分/限流文档，说明短问句缺少领域锚点（「补卡」未被充分加权）。
- 第二题被「发票」主导，而真正答案是差旅报销的「单据提交期限」；属于典型词面干扰。
- 两者都说明：**Recall@5 饱和不代表检索质量已到上限**，Top-1 才是更敏感的信号；后续应在更难语料上评估。

## 5. 局限

- **语料偏简单**：20 篇短文档、主题区分度高，Top-5 几乎必然覆盖；Recall@5=1.0 不应外推到真实知识库。
- **文档级标签**：不区分同一文档内多个 chunk 的位置；chunk 级 Recall 未测。
- **单轮问题**：未覆盖多轮指代、跨文档多跳问题。
- **无重排**：P0 不使用 reranker；Top-1 的两次失败可能被 reranker 修复，需实验验证。
- **HNSW 未调参**：20 个向量时索引近似行为不可观测。

## 6. 下一步

1. 扩充到 100+ 题，加入同主题近似文档、长文档与多跳问题。
2. 增加 chunk 级 Recall 与 MRR。
3. 用 bge-reranker 对 Top-5 重排，比较 Recall@1 / MRR 变化（C6 要求行为变更必须有数据）。
4. 在 10k chunk 规模上测检索 P95 与 HNSW 参数。

## 7. P5-S1 说明（2026-11-22）

本文件 §3 的结果仍来自**纯向量检索**。P5-S1 已接入 `pg_trgm` 词法召回 + RRF 融合与可选 bge-reranker 重排（见 [`ADR-0019`](../adr/0019-hybrid-retrieval.md)），但尚未在评测集上重跑；vector vs hybrid vs hybrid+rerank 的对比属于 P5-S2。

## 8. P5-S2 重跑：vector vs hybrid vs rerank（2026-11-22）

通过评测平台对同一 `eval/dataset.json`（20 文档 / 50 题）跑三次，KB 默认分块（1000/150），`top_k=5`、`candidate_k=20`：

| 配置 | Recall@1 | Recall@3 | Recall@5 | MRR | 检索 P50 | 检索 P95 |
|---|---|---|---|---|---|---|
| 纯向量 | 0.960 | 1.000 | 1.000 | 0.9767 | 27.17ms | 130.50ms |
| 混合检索 | 0.960 | 1.000 | 1.000 | 0.9767 | 28.08ms | 42.82ms |
| 混合 + 重排 | **0.980** | 1.000 | 1.000 | **0.9900** | 56.71ms | 133.22ms |

解读：

- 50 题短文档集上 Recall@3/5 已饱和，Top-1/MRR 才是有效信号。
- 重排修复了 1 道 Top-1 错误，MRR +0.0133；代价是 P95 从约 43ms 升到约 133ms。
- 本数据集上混合检索未改变 Top-1，但 P95 更低；不能据此推断其他语料。
- 50 题全量 answer+judge 在本地 Qwen 上耗时较长，本次只跑检索指标；judge 已用单题真机验证（见 [`p5-s2-evaluation.md`](../tdd/p5-s2-evaluation.md)）。