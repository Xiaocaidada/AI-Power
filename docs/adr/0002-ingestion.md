# ADR-0002: P0 入库流水线与向量存储

- **Status:** Accepted
- **Date:** 2026-11-21
- **Deciders:** 项目作者
- **Related:** [`docs/product/CAPABILITY.md`](../product/CAPABILITY.md)、[`ADR-0001`](./0001-p0-stack.md)、[`docs/tdd/p0-s3-ingestion.md`](../tdd/p0-s3-ingestion.md)

## Context

S3 需要把上传的 PDF/MD/TXT 变成可检索的向量，并保持用户隔离与可解释的失败状态。当前环境：

- Docker（含 pgvector Postgres 与 Redis）运行在 WSL Ubuntu-22.04，宿主 IP `192.168.29.100`；Windows 的 `localhost:5432` 不通。
- 开发/测试默认 SQLite；Postgres + pgvector 通过容器提供。
- bge-m3 在 `http://192.168.29.100:8000/v1`（vLLM，1024 维）。
- 本机没有持久化任务队列；P0 不引入 Redis 队列。

需要锁定：入库执行方式、向量类型、分块策略、幂等语义、文件存储与失败码。

## Decision

### 1. 执行器：FastAPI BackgroundTasks（P0）

上传请求只做校验、落库与保存文件，然后通过 `BackgroundTasks` 调用 `ingest_document(document_id)`。它**不是持久化队列**：进程重启会丢失未完成任务。

- P0 接受该限制，换取零额外基础设施。
- P1 换 Arq/Celery，并引入 job 租约、重试与死信（能力契约 2.5 已定义）。

### 2. 向量存储：pgvector + 方言感知类型

- `ChunkEmbedding.embedding` 使用自定义 `EmbeddingVector`：
  - Postgres → `vector(1024)`（pgvector）。
  - SQLite → `JSON`（测试）。
- `init_db()` 在 Postgres 上执行 `CREATE EXTENSION IF NOT EXISTS vector`。
- 距离查询通过自定义 Comparator 暴露 `l2_distance` / `cosine_distance`（使用 `<->` / `<=>` 操作符）。
- Postgres 集成测试通过 `TEST_POSTGRES_URL` 选择性启用；默认套件只跑 SQLite。

### 3. 分块：字符窗口 + 重叠 + 页码

- 默认 `CHUNK_MAX_CHARS=1000`、`CHUNK_OVERLAP_CHARS=150`。
- PDF 按页解析，chunk 保留 `page_no`；纯文本页 `page_no=None`。
- 空白页跳过；`chunk_index` 全局递增。
- 不做语义分块/重排（P2 再评估）。

### 4. 幂等：`(user_id, kb_id, content_hash)` 唯一

- 部分唯一索引（`deleted_at IS NULL`）保证同 KB 内重复内容只有一份。
- 重复上传返回已有文档：HTTP 200 + `duplicate=true`，不重复向量化。
- 软删后允许重新上传。
- 同一文件上传到不同 KB 视为不同文档（避免跨 KB 复用导致归属错乱）。

### 5. 文件与限制

- 文件以 `UUID + 白名单后缀` 存放在 `UPLOAD_DIR`；原文件名只存 DB，不用于路径。
- 允许 `.pdf` / `.md` / `.txt`，按扩展名判定 MIME，忽略客户端声明的 `content_type`。
- 默认上限：20MB、200 页；超限分别返回 413 / `too_many_pages`。
- 删除文档：软删 + 同步删除 chunks/embeddings；原始文件暂不删除。

### 6. 失败码

`parse_failed`、`unsupported_type`、`too_many_pages`、`empty_document`、`embedding_failed`、`embedding_count_mismatch`、`embedding_dimension_mismatch`、`ingestion_failed`。

## Consequences

### Positive

- 零新增基础设施即可跑通完整入库链路；测试可用 fake parser/embedder 快速验证状态机。
- 同一份代码在 SQLite（测试）与 Postgres/pgvector（生产）上运行；pgvector 行为有独立集成测试。
- 幂等与用户隔离在数据库与查询两层同时保证。

### Negative / Risks

- **BackgroundTasks 不持久**：重启/崩溃丢任务，文档可能停留在 `parsing`/`embedding`。P1 必须补队列与恢复。
- **原始文件残留**：软删文档后文件仍在磁盘，需要 P1 清理任务。
- **PDF 解析未用真实 PDF 验证**：`pypdf` 是薄封装，仍可能遇到扫描件/加密 PDF。
- **无 OCR**：扫描 PDF 会得到空文本 → `empty_document`。
- **token_count 未计算**：当前为 NULL；P1 用 Qwen tokenizer 补。
- **SQLite 与 Postgres 行为差异**：JSON 向量没有索引；Postgres 测试需显式启用。

### Alternatives Considered

| 方案 | 未采用原因 |
|---|---|
| P0 直接上 Celery/Arq | 需要 Redis 队列与 worker 运维，超出当前阶段 |
| 向量直接存 `chunks.embedding` | 与能力契约的 `chunk_embeddings` 表不一致，且不利于独立索引 |
| 只用 `pgvector.Vector` 类型 | SQLite 测试无法建表，测试反馈变慢 |
| 无重叠分块 | 边界语义容易断裂，检索质量差 |
| 跨 KB 复用同一 hash 的文档 | 文档归属会落到错误的知识库 |

## Follow-ups

1. P1：持久化队列 + job 租约/重试/死信；清理残留文件；计算 token_count。
2. 增加真实 PDF（含加密/扫描件）测试，决定是否引入 OCR。
3. S4：为 `chunk_embeddings` 建 HNSW/IVFFlat 索引，并加入 Recall@5 评测集。
4. 提供文档重试端点（当前只能重新上传）。