# TDD Evidence — P5-S1: 混合检索、重排与知识库参数/分块管理

- **Date:** 2026-11-22
- **Scope:** pg_trgm 词法召回、RRF 融合、bge-reranker-v2-m3 重排、KB 分块/检索参数、分块浏览/统计/重新分块、检索调试 API 与前端页签
- **Source:** [`docs/plan/p5-plan.md`](../plan/p5-plan.md) P5-S1、[`ADR-0019`](../adr/0019-hybrid-retrieval.md)

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 新增单测/API 测试（RED） | `pytest tests/test_rerank.py tests/test_retrieval_hybrid.py tests/test_knowledge_features.py -q` | **17 failed, 2 passed**（模块/接口未实现） |
| 新增单测/API 测试（GREEN） | 同上 | **19 passed** |
| Postgres 集成（opt-in） | `TEST_POSTGRES_URL=... pytest tests/test_retrieval_postgres.py -q` | **3 passed**（HNSW + trigram 索引、pgvector 排序、pg_trgm 混合召回） |
| 后端全量 | `pytest -q` | **323 passed, 3 skipped**（326 collected；随后 JWT-only 调试接口/指标 HELP 微调，targeted 13 passed） |
| Lint/Format | `ruff check .` / `ruff format --check .` | 通过 |
| 前端单测 | `npm test` | **22 passed** |
| 类型/构建 | `npm run typecheck` / `npm run build` | 通过 |
| Playwright 回归 | `npm run test:e2e` | **2 passed** |

## RED / GREEN

### RED

首次运行新增测试时：

- `app.providers.rerank` 不存在；
- `retrieve_with_diagnostics` / `fuse_rrf` / KB 设置与分块接口不存在；
- `/knowledge-bases/{id}/settings|chunks|stats`、`/documents/{id}/reprocess` 返回 404；
- KB 分块参数尚未参与入库。

### GREEN

- `app/providers/rerank.py`：vLLM/TEI 兼容 `POST {base_url}/rerank`，解析 `results[].{index,relevance_score}`，错误映射 `rerank_http_error` / `rerank_unreachable` / `rerank_bad_response`。
- `app/services/knowledge_settings.py`：`KnowledgeBaseSettings`（chunking + retrieval），默认继承全局 settings，非法 JSON 回退默认值。
- `app/services/retrieval.py`：向量/词法召回、`fuse_rrf`、可选重排、阶段耗时、指标、失败回退。
- `app/services/ingestion.py`：按 KB 的 `chunking` 参数分块；KB 不存在/已删除时失败 `kb_not_found`。
- `app/routers/knowledge_bases.py`：设置、分块、统计、检索调试接口。
- `app/routers/documents.py`：`reprocess` 删除旧分块并按当前设置重建。
- 前端：知识库详情页新增“文档 / 分块 / 检索调试 / 设置”页签；分块卡片、分页、筛选；检索结果展示向量/词法/融合/重排分数与耗时；重新分块确认框。

## Test Specification

| # | What is guaranteed | Test |
|---|---|---|
| 1 | 重排请求使用正确 URL/JSON，并按 score 降序返回 | `test_reranker_posts_openai_compatible_payload_and_sorts_results` |
| 2 | 重排请求携带 Bearer key，但代码/日志不输出 key | `test_reranker_sends_api_key_header_without_logging_it` |
| 3 | 重排 HTTP 失败映射为 typed ProviderError | `test_reranker_raises_typed_error_on_http_failure` |
| 4 | 重排响应 index 越界被拒绝 | `test_reranker_rejects_malformed_results` |
| 5 | `RERANK_ENABLED=false` 时不构造重排器 | `test_build_reranker_respects_settings_toggle` |
| 6 | RRF 分数与排序正确 | `test_rrf_fuses_vector_and_lexical_ranks` |
| 7 | 词法命中可把向量排名较低的分块提到第一 | `test_hybrid_search_uses_lexical_match_to_surface_keyword` |
| 8 | 单 KB 可关闭混合检索，结果回到纯向量顺序 | `test_hybrid_can_be_disabled_per_knowledge_base` |
| 9 | 重排可反转候选顺序并记录 `rerank_score` | `test_reranker_reorders_candidates_and_records_score` |
| 10 | 重排失败回退融合顺序，不影响回答 | `test_reranker_failure_falls_back_to_fused_order` |
| 11 | 检索结果返回各阶段耗时与 mode | `test_retrieval_reports_stage_timings` |
| 12 | KB 设置默认值、部分更新与嵌套校验 | `test_knowledge_base_settings_defaults_and_partial_update` / `..._reject_invalid_combinations` |
| 13 | KB 设置跨 workspace 404 | `test_knowledge_base_settings_are_workspace_scoped` |
| 14 | 分块参数对**新入库**生效 | `test_chunking_settings_apply_to_new_ingestion` |
| 15 | 分块浏览支持文档筛选、关键词、分页与隔离 | `test_chunk_browser_filters_paginates_and_hides_other_workspaces` |
| 16 | 统计返回文档/分块/字符数 | `test_knowledge_base_stats_count_documents_and_chunks` |
| 17 | 重新分块按当前参数重建并入队 | `test_reprocess_rechunks_document_with_current_settings` |
| 18 | 重新分块跨 workspace 404 | `test_reprocess_rejects_other_workspace` |
| 19 | Postgres 上 HNSW + trigram 索引幂等创建 | `test_hnsw_and_trigram_indexes_are_created_idempotently`（opt-in） |
| 20 | Postgres `pg_trgm` 词法候选参与 RRF | `test_hybrid_search_uses_pg_trgm_lexical_candidates`（opt-in） |

## Real-service checks

- `GET http://192.168.29.100:8001/v1/models` 返回 `bge-reranker-v2-m3`。
- `POST http://192.168.29.100:8001/v1/rerank` 返回：
  ```json
  {"results":[{"index":0,"document":{"text":"..."},"relevance_score":0.785...}, ...]}
  ```
- 客户端默认 `RERANK_BASE_URL=http://192.168.29.100:8001/v1`、`RERANK_MODEL=bge-reranker-v2-m3`；候选上限 8 条、每条 800 字符，避免超过模型 8192 token。

## End-to-end verification（本地 compose）

- 通过 API 创建知识库 `P5 检索演示 0bc2`，上传 `refund_policy.txt`，设置 `chunk_size=120` / `overlap=20` / `top_k=5` / `candidate_k=10` / hybrid+rerank，执行“重新分块”后得到 3 个分块、340 字符。
- 一键搜索 `退款多久到账`：
  - `mode = hybrid+rerank`
  - `vector_ms=9.2` / `lexical_ms=2.1` / `rerank_ms=167.1` / `total_ms=260`
  - Top-1：`vector_rank=1`、`lexical_rank=1`、`fused_score=0.0328`、`rerank_score=0.7288`
- 浏览器验证 `/knowledge/:id`：文档页显示统计与“重新分块”；分块页显示 3 个分块及文档筛选/搜索/分页；检索调试页显示 `hybrid+rerank`、各阶段耗时、向量/词法/融合/重排分数；设置页可保存分块与检索参数。
- `docker compose up -d --build api worker web` 后 `/readyz` 数据库与 Redis 正常；Postgres 中 `knowledge_bases.settings` 列与 `ix_chunks_text_trgm` 索引已存在。

## Known Gaps

- **质量提升尚未量化**：本次只验证排序机制与回退；vector vs hybrid vs rerank 的 Recall@1/MRR 对比留待 P5-S2 的 ≥100 题数据集。
- **中文词法依赖 trigram + 子串**：没有分词，专有名词/短问句效果需数据验证。
- **分块参数不自动重切**：已有文档需手动“重新分块”。
- **分块编辑/删除未做**：当前只读浏览 + 文档级重处理。
- **重排服务是局域网依赖**：服务不可用时每次检索最多等待 `RERANK_TIMEOUT_SECONDS` 后回退；未做跨进程熔断。
- **Playwright 未覆盖新页签**：本片以 API/单测与浏览器手工验证为主，E2E 留待 S6。
- **SQLite 词法回退会加载 KB 内全部分块**：仅测试/开发路径，生产走 pg_trgm。