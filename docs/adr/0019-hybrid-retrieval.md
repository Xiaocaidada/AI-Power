# ADR-0019: 混合检索、重排与知识库可配置分块

- **Status:** Accepted
- **Date:** 2026-11-22
- **Context:** P0 的检索只有 pgvector L2 KNN，50 题基线 Recall@5=1.000 但 Recall@1=0.960，短问句和词面干扰已经暴露 Top-1 不足；同时知识库没有可调分块/检索参数，也没有查看分块与检索过程的产品界面。

## Decision

### 混合检索

- **召回**：pgvector 向量召回 `candidate_k` 条 + Postgres `pg_trgm` 词法召回 `candidate_k` 条。
  - 词法评分：`CASE WHEN text ILIKE '%query%' THEN 1.0 ELSE similarity(text, query) END`；
  - 过滤条件与向量召回一致（workspace、KB、文档 ready 且未删除）；
  - `chunks.text` 建 `GIN (text gin_trgm_ops)` 索引。
- **融合**：RRF（Reciprocal Rank Fusion），`score = Σ 1 / (60 + rank_i)`，按 `chunk_id` 去重；同分按向量排名、chunk_index、id 排序。
- **SQLite 回退**：测试/开发路径用字符 bigram 覆盖率做词法评分，保证融合逻辑可跨方言测试。

### 重排

- **可插拔 `Reranker`**：默认实现调用 vLLM/TEI 兼容的 `POST {RERANK_BASE_URL}/rerank`（当前 `bge-reranker-v2-m3`）。
- **按 KB 开关**：默认继承 `RERANK_ENABLED`；单 KB 可关闭。
- **输入上限**：最多 `RERANK_MAX_CANDIDATES=8` 条候选，每条截断到 `RERANK_MAX_DOC_CHARS=800`，避免超过 8192 token。
- **失败回退**：超时、非 2xx、响应格式错误都只记录指标/日志，继续使用 RRF 融合顺序；检索不会因重排失败而 5xx。

### 知识库参数与分块管理

- `knowledge_bases.settings` 存 JSON：
  - `chunking.chunk_size` / `chunk_overlap`：仅对**下次入库或“重新分块”**生效；
  - `retrieval.top_k` / `candidate_k` / `hybrid_enabled` / `rerank_enabled`：对聊天 RAG、`kb_search` 工具、检索调试统一生效。
- 保留全局 `CHUNK_*`、`RETRIEVAL_*` 作为默认值；保存过的 KB 使用自己的快照，后续改全局默认不影响它。
- **旧文档不会自动重切**；`POST /documents/{id}/reprocess` 删除分块并按当前参数重新解析/向量化。
- 新增产品接口：
  - `GET/PATCH /knowledge-bases/{id}/settings`
  - `GET /knowledge-bases/{id}/chunks`（文档筛选、关键词、分页）
  - `GET /knowledge-bases/{id}/stats`
  - `POST /knowledge-bases/{id}/retrieval/search`（返回向量/词法/融合/重排排名与阶段耗时）
  - `POST /documents/{id}/reprocess`

### 可观测

- `ai_power_retrieval_requests_total{mode}`、`ai_power_retrieval_duration_seconds{mode}`；
- `ai_power_rerank_failures_total{code}`；
- 调试接口返回 `vector_ms` / `lexical_ms` / `rerank_ms` / `total_ms`。

## Consequences

- 每次检索多一次词法查询；在演示规模下可接受，`pg_trgm` 索引避免全表扫描。
- 中文分词质量取决于 trigram + 子串匹配；效果提升需要在 P5-S2 的 ≥100 题、含近似干扰数据集上量化，**当前不宣称质量提升**。
- 重排增加一次 HTTP 调用（通常几十到几百毫秒）；有候选/字符上限与失败回退。
- 分块参数是“保存后对新文档/重处理生效”，不是实时重切；界面明确提示。
- 调试接口是只读诊断，不写对话/用量；仅 JWT 可用（避免 API Key 反复触发 embedding/rerank 成本），仍受 workspace 隔离约束。
- 默认 `RERANK_ENABLED=true` 且指向局域网 `192.168.29.100:8001`；脱离该环境时需显式关闭或改地址。

## Alternatives

- **Elasticsearch/Qdrant 混合检索**：效果/扩展性更好，但多一个服务，超出个人项目演示成本。
- **jieba + tsvector**：中文分词更精确，但引入分词依赖、词典维护和索引重建成本。
- **强制部署 bge-reranker**：效果更稳定，但让无 GPU 环境无法启动；改为可选/可回退。
- **LLM listwise 重排**：无需新服务，但慢且贵，不适合每次检索。
- **只做向量检索 + 调 top_k**：无法解决词面干扰，也无法回答“检索是否变好”。