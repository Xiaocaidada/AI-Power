# TDD Evidence — P0 S4: Retrieval + citations + RAG chat

- **Date:** 2026-11-21
- **Scope:** S4（向量检索、上下文预算、引用、RAG 对话、HNSW、Recall@k 评测入口）
- **Source:** [`PRODUCT-BRIEF.md`](../../PRODUCT-BRIEF.md)、[`docs/product/CAPABILITY.md`](../product/CAPABILITY.md)（§2.2 I1/I3、§3.2 SSE、§3.4 Protocol、§3.5 索引）、[`ADR-0003`](../adr/0003-retrieval.md)
- **Test runner:** pytest（Python 3.13.15）；默认 SQLite；pgvector 集成按 `TEST_POSTGRES_URL` 选择性启用
- **Commits:** RED `6e78a55`，GREEN `d30a6e5`（分支 `feat/p0-s4-retrieval`）

## User Journeys

1. 作为用户，我在开启了知识库的对话里提问，回答会基于我上传的文档。
2. 作为用户，我想看到回答引用了哪些文档、哪一页、哪段文字。
3. 作为用户，我不希望检索到别人的文档，或同一账号其他知识库的文档。
4. 作为用户，当知识库为空时我仍能正常对话，并知道没有检索到资料。
5. 作为用户，当检索服务不可用时，我希望得到明确错误，而不是假装回答有依据。
6. 作为维护者，我想用固定数据集量化 Recall@5，评估检索质量。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| RED | `.venv/Scripts/python.exe -m pytest tests/test_retrieval.py tests/test_rag_chat.py tests/test_retrieval_postgres.py` | `12 failed, 6 errors`（多为 `ModuleNotFoundError: app.services.retrieval / app.services.rag`；pgvector 用例跳过） |
| GREEN | `.venv/Scripts/python.exe -m pytest` | `133 passed, 3 skipped` |
| Coverage | `... --cov=app --cov-report=term-missing` | `TOTAL 1200 45 96%` |
| Lint | `... -m ruff check .` | `All checks passed!` |
| Format | `... -m ruff format .` | 全部文件已格式化 |

**RED 证据（节选）**

- `test_search_orders_by_distance_and_limits_top_k` → `ModuleNotFoundError: No module named 'app.services.retrieval'`
- `test_fit_context_keeps_rank_order_within_budget` → `ModuleNotFoundError: No module named 'app.services.rag'`
- `test_rag_*`（需要 `fake_retrieval` fixture）→ fixture 导入失败（ERROR）
- `test_retrieval_settings_must_be_positive` → `DID NOT RAISE ValidationError`
- `tests/test_rag_chat.py::test_plain_conversation_has_no_citations` 在 RED 阶段已通过（纯对话路径未被改动）

**GREEN 前实现范围**：`RetrievedChunk` / `Citation`、方言感知检索（pgvector `<->` / SQLite Python 回退）、`fit_context`、`build_citations`、`build_rag_messages`、HNSW 索引常量、`retrieval_*` 配置、`citation` SSE、`retrieval_failed` 502、共享 `build_embedder`、Recall@k 评测函数与 CLI。

## 真实链路冒烟

### 1. bge-m3 真实检索（VM，SQLite 存储）

三篇中文文档（退款 / 配送 / 发票），查询「用户想退货，钱多久能退回来？」：

```
top_k: [('退款政策.txt', 0.6637), ('发票开具.txt', 0.8544), ('配送范围.txt', 0.8984)]
citation: Citation(index=1, page_no=1, snippet='订单签收后 7 天内可以申请无理由退款…')
```

检索排序语义正确：退款文档排第一。

### 2. pgvector + HNSW 集成（WSL Postgres）

```
tests/test_postgres_vector.py tests/test_retrieval_postgres.py ... [100%]
```

覆盖：`vector(1024)` 存储、HNSW 索引幂等创建（`vector_l2_ops`）、SQL 检索排序与 `user_id + kb_id` 过滤。

**环境发现**：WSL 容器重建后 `ai_power_test` 数据库丢失，测试报 `database "ai_power_test" does not exist`；用 stdin 管道重建后通过：

```bash
printf 'CREATE DATABASE ai_power_test;\n' | docker exec -i ai_power-postgres-1 psql -U ai_power -d postgres
```

## Test Specification

### Retrieval service（`tests/test_retrieval.py`，19）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 结果按 L2 距离升序，`top_k` 生效，query 只 embedding 一次 | `test_search_orders_by_distance_and_limits_top_k` | PASS |
| 2 | 只返回指定 `user_id + kb_id` 的 chunk | `test_search_filters_by_user_and_knowledge_base` | PASS |
| 3 | 非 `ready` / 已软删文档不参与检索 | `test_search_excludes_documents_that_are_not_ready_or_deleted` | PASS |
| 4 | 空知识库返回空列表 | `test_search_returns_empty_when_knowledge_base_has_no_chunks` | PASS |
| 5 | 空白 query 直接返回空，不调用 embedding | `test_search_returns_empty_for_blank_query_without_embedding` | PASS |
| 6 | embedding 未返回查询向量 → `embedding_bad_response` | `test_search_rejects_embedder_returning_missing_query_vector` | PASS |
| 7 | 维度不一致时 `_l2_distance` 报错而非静默比较 | `test_l2_distance_rejects_dimension_mismatch` | PASS |
| 8 | `build_embedder` 使用配置的 endpoint/model/维度 | `test_build_embedder_uses_configured_endpoint` | PASS |
| 9 | `top_k < 1` 抛 `ValueError` | `test_search_rejects_non_positive_top_k` | PASS |
| 10 | embedding provider 错误向上传播 | `test_search_propagates_embedding_provider_errors` | PASS |
| 11 | citation 从 1 开始编号、使用真实 chunk/document id、snippet 折叠空白并截断到 240 | `test_build_citations_numbers_from_one_with_real_chunk_ids` | PASS |
| 12 | 上下文预算内按排名保留 chunk | `test_fit_context_keeps_rank_order_within_budget` | PASS |
| 13 | 首个 chunk 超预算时截断而非丢弃 | `test_fit_context_truncates_oversized_first_chunk` | PASS |
| 14 | 非正预算抛 `ValueError` | `test_fit_context_rejects_non_positive_budget` | PASS |
| 15 | system prompt 包含编号参考、文件名/页码、untrusted DATA 声明，且位于历史之前 | `test_rag_messages_place_untrusted_references_before_history` | PASS |
| 16 | 无页码时引用格式为 `[1] (notes.txt)` | `test_rag_messages_reference_without_page_number` | PASS |
| 17 | 无检索结果时 system prompt 声明无参考资料 | `test_rag_messages_without_chunks_declare_missing_context` | PASS |
| 18 | HNSW SQL 使用 `USING hnsw` + `vector_l2_ops` + `IF NOT EXISTS` | `test_hnsw_index_sql_uses_l2_operator_class` | PASS |
| 19 | `RETRIEVAL_TOP_K` / `RETRIEVAL_MAX_CONTEXT_CHARS` 必须 ≥ 1 | `test_retrieval_settings_must_be_positive` | PASS |

### RAG chat（`tests/test_rag_chat.py`，7）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 20 | 事件顺序 `meta → citation → delta* → usage → done`；citation 字段与数据库 chunk 一致 | `test_rag_conversation_emits_citations_for_retrieved_chunks` | PASS |
| 21 | 送给 provider 的首条消息是含参考与注入防护的 system prompt | `test_rag_system_prompt_contains_reference_and_injection_guard` | PASS |
| 22 | 只引用会话绑定知识库的 chunk | `test_rag_only_cites_chunks_from_conversation_kb` | PASS |
| 23 | 未绑定知识库的会话没有 system prompt / citation | `test_plain_conversation_has_no_citations` | PASS |
| 24 | 检索失败 → 502 `retrieval_failed`，不持久化消息、不调用 LLM | `test_rag_retrieval_failure_returns_502_before_persisting` | PASS |
| 25 | 空知识库正常流式回答并声明无资料 | `test_rag_empty_knowledge_base_streams_without_citations` | PASS |
| 26 | 同一 KB 下他人拥有的 chunk 永不进入引用 | `test_rag_never_cites_chunks_owned_by_another_user` | PASS |

### Evaluation（`tests/test_evaluation.py`，2）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 27 | 文档级 Recall@k 只统计命中相关问题 | `test_recall_counts_questions_with_a_relevant_hit` | PASS |
| 28 | 空数据集 recall 为 0，不触发 embedding | `test_recall_is_zero_for_empty_dataset` | PASS |

### pgvector opt-in（`tests/test_retrieval_postgres.py`，2）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 29 | HNSW 索引幂等创建且使用 `vector_l2_ops` | `test_hnsw_index_is_created_idempotently` | PASS（显式启用时） |
| 30 | SQL 检索路径按距离排序并过滤 KB | `test_retrieval_uses_pgvector_ordering_and_filters` | PASS（显式启用时） |

## Coverage

```
TOTAL                             1200     45    96%
```

新增模块：`app/services/rag.py` 100%、`app/services/evaluation.py` 100%、`app/routers/conversations.py` 100%、`app/services/retrieval.py` 93%。未覆盖的 5 行是 `_search_with_distance`（Postgres 专用路径，由 opt-in 集成测试覆盖）。

## Known Gaps

- **50 题评测集未构造**：`scripts/eval_retrieval.py` 已就绪，但缺少人工标注的真实语料；Recall@5 基线待补（C6）。
- **引用未持久化**：`messages` 表无 citations 字段，历史会话无法回放引用。
- **无重排 / 查询改写**：P0 非目标。
- **HNSW 参数未调优**：使用默认 `m` / `ef_construction`，10k chunk P95 未实测。
- **无检索超时**：依赖 embedding provider 的 HTTP timeout（60s）。
- **无并发/限流测试**：20 并发目标未验证。
- **citation 事件未做端到端浏览器验证**：前端尚未开始。

## Merge Evidence

- RED checkpoint：`6e78a55 test: add P0 S4 retrieval and RAG chat coverage`
- GREEN checkpoint：`d30a6e5 feat: implement retrieval, citations, and RAG chat`
- 真实 bge-m3 冒烟与 pgvector 结果见上；如后续 squash，请把 RED/GREEN 摘要与冒烟数据写入 squash commit 正文。