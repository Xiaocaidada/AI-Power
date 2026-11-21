# TDD Evidence — P0 S3: Document upload + async ingestion

- **Date:** 2026-11-21
- **Scope:** S3（文档上传 + 解析 + 分块 + bge-m3 embedding + pgvector 存储）
- **Source:** [`PRODUCT-BRIEF.md`](../../PRODUCT-BRIEF.md)、[`docs/product/CAPABILITY.md`](../product/CAPABILITY.md)（P0）、[`ADR-0002`](../adr/0002-ingestion.md)
- **Test runner:** pytest（Python 3.13.15）；默认 SQLite，pgvector 集成测试按 `TEST_POSTGRES_URL` 选择性启用
- **Commits:** RED `a69712c`，GREEN `ab32f2e`（分支 `feat/p0-s3-ingestion`）

## User Journeys

1. 作为用户，我想把 PDF/MD/TXT 上传到自己的知识库。
2. 作为用户，我想看到文档的处理状态和失败原因。
3. 作为用户，我想重复上传同一文件时复用已有文档，而不是重复向量化。
4. 作为用户，我想让我的文档与其他用户隔离。
5. 作为用户，我想删除文档时一并移除它的 chunks。
6. 作为用户，我想在没有可用文本或页数超限时得到明确失败，而不是静默成功。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| RED | `.venv/Scripts/python.exe -m pytest` | `17 failed, 20 errors, 68 passed, 1 skipped` |
| GREEN | 同上 | `105 passed, 1 skipped` |
| Coverage | `... -m pytest --cov=app --cov-report=term-missing` | `TOTAL 1045 41 96%` |
| Lint | `... -m ruff check .` | `All checks passed!` |
| Format | `... -m ruff format .` | `46 files left unchanged` |

**RED 证据（节选）**

- `tests/test_chunking.py` / `test_parsing.py` / `test_embedding_provider.py` → `ModuleNotFoundError: No module named 'app.services'` / `app.providers.embedding`
- `tests/test_documents.py::test_upload_requires_auth` → `assert 404 == 401`（路由尚未实现）
- `tests/test_ingestion.py::*` → `fake_ingestion` fixture 导入失败

**GREEN 前实现范围**：解析器（PDF/MD/TXT）、分块、`EmbeddingProvider`、`EmbeddingVector`、Document/Chunk/ChunkEmbedding/IngestionJob 模型、上传/状态/删除端点、入库状态机、共享 ownership 助手。

## 真实链路冒烟

### 1. bge-m3 embedding（VM）

```
OpenAICompatEmbeddingProvider(http://192.168.29.100:8000/v1, model=bge-m3, dims=1024)
→ 返回 1024 维向量
```

### 2. 端到端入库（真实解析器 + 真实 bge-m3，临时 SQLite）

```
{'status': 'ready', 'error_code': None, 'pages': 1, 'chunks': 7, 'embeddings': 7, 'dim': 1024}
```

### 3. pgvector 集成（WSL Postgres）

```
TEST_POSTGRES_URL=...@192.168.29.100:5432/ai_power_test
tests/test_postgres_vector.py .                                          [100%]
```

验证了：`vector(1024)` 存储、`vector_dims = 1024`、`<->` 最近邻排序命中正确 chunk。

**环境发现**：Docker 跑在 WSL（`192.168.29.100`），Windows 的 `localhost:5432` 连接被拒；`docker exec ... psql -c "含空格的 SQL"` 在 Windows 下会被拆参，需用 stdin 管道。

## Test Specification

### Chunking（`tests/test_chunking.py`，6）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 短文本产生单个 chunk，页码与 index 正确 | `test_short_text_produces_single_chunk` | PASS |
| 2 | 长文本按窗口切分并保留重叠 | `test_long_text_splits_with_overlap` | PASS |
| 3 | 页码在 chunk 上保留 | `test_page_numbers_are_preserved` | PASS |
| 4 | 空白页被跳过 | `test_blank_pages_are_skipped` | PASS |
| 5 | chunk_index 跨页全局递增 | `test_chunk_index_increments_across_pages` | PASS |
| 6 | overlap ≥ max_chars 时报错 | `test_overlap_must_be_smaller_than_max_chars` | PASS |

### Parsing（`tests/test_parsing.py`，5）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 7 | 文本解析器按 UTF-8 读取 | `test_text_parser_reads_utf8` | PASS |
| 8 | MIME 分发到 PDF/文本解析器 | `test_parser_for_mime_dispatches_pdf_and_text` | PASS |
| 9 | 未知 MIME 被拒绝 | `test_parser_for_mime_rejects_unknown` | PASS |
| 10 | 扩展名映射到 MIME（大小写不敏感） | `test_detect_mime_by_extension` | PASS |
| 11 | 未知扩展名即使声明 text/plain 也被拒绝 | `test_detect_mime_rejects_unknown_extension_even_with_text_type` | PASS |

### Embedding（`tests/test_embedding_provider.py`，5）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 12 | 按 `index` 排序返回向量，请求含 model/input | `test_embed_returns_vectors_in_index_order` | PASS |
| 13 | 维度不匹配 → `embedding_bad_response` | `test_embed_rejects_dimension_mismatch` | PASS |
| 14 | HTTP 失败 → `embedding_http_error` | `test_embed_raises_on_http_error` | PASS |
| 15 | 连接失败 → `embedding_unreachable` | `test_embed_raises_when_unreachable` | PASS |
| 16 | 响应缺 data → `embedding_bad_response` | `test_embed_rejects_missing_data` | PASS |

### Documents API（`tests/test_documents.py`，14）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 17 | 上传需要认证 | `test_upload_requires_auth` | PASS |
| 18 | 上传到他人知识库 → 404 | `test_upload_to_foreign_knowledge_base_returns_404` | PASS |
| 19 | 不支持的扩展名 → 415 | `test_upload_rejects_unsupported_extension` | PASS |
| 20 | 上传后入库完成，状态 ready，chunk/embedding 落库 | `test_upload_ingests_and_marks_ready` | PASS |
| 21 | 重复上传复用文档（200 + duplicate=true），不重复 chunk | `test_duplicate_upload_reuses_existing_document` | PASS |
| 22 | 读取他人文档 → 404 | `test_get_other_users_document_returns_404` | PASS |
| 23 | 删除他人文档 → 404 | `test_delete_other_users_document_returns_404` | PASS |
| 24 | 所有者删除 → 204，后续 404，chunks/embeddings 清空 | `test_owner_can_delete_document_and_chunks` | PASS |
| 25 | 解析失败 → failed + `parse_failed` | `test_parser_failure_marks_document_failed` | PASS |
| 26 | embedding 失败 → failed + `embedding_failed` | `test_embedder_failure_marks_document_failed` | PASS |
| 27 | 页数超限 → failed + `too_many_pages` | `test_page_limit_marks_document_failed` | PASS |
| 28 | 空文件 → 400 | `test_empty_upload_is_rejected` | PASS |
| 29 | 超过大小限制 → 413 | `test_oversize_upload_is_rejected` | PASS |
| 30 | 响应不暴露 storage_path，存储名为 UUID | `test_storage_path_is_not_exposed_and_uses_uuid_name` | PASS |

### Ingestion service（`tests/test_ingestion.py`，7）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 31 | 成功时 document/job/chunks/embeddings 状态一致 | `test_ingest_document_marks_ready_and_stores_chunks` | PASS |
| 32 | 解析异常 → `parse_failed`，job failed | `test_ingest_document_marks_failed_on_parse_error` | PASS |
| 33 | embedding 异常 → `embedding_failed` | `test_ingest_document_marks_failed_on_embedding_error` | PASS |
| 34 | 页数超限 → `too_many_pages` | `test_ingest_document_enforces_page_limit` | PASS |
| 35 | 重复执行不产生重复 chunks/embeddings | `test_ingest_document_is_idempotent_on_retry` | PASS |
| 36 | 已删除文档不再入库 | `test_ingest_document_ignores_deleted_document` | PASS |
| 37 | embedding 按 batch size 分批（3 chunks → [2,1]） | `test_ingest_document_batches_embeddings` | PASS |

### pgvector（`tests/test_postgres_vector.py`，1，opt-in）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 38 | Postgres 存储 1024 维向量，L2 排序命中正确 | `test_pgvector_stores_1024_dimensions_and_orders_by_l2_distance` | PASS（显式启用时） |

## Coverage

```
TOTAL                             1045     41    96%
```

未覆盖的主要是可解释的边角：真实 PDF 解析路径、部分入库异常分支、`EmbeddingVector` 在 SQLite 上的距离比较器（SQLite 不支持 `<->`）。

## Known Gaps

- **BackgroundTasks 非持久化**：进程重启会丢任务；P1 换 Arq/Celery。
- **PDF 解析未用真实 PDF 验证**：仅验证了文本格式与分发；扫描件/加密 PDF 未覆盖。
- **无 OCR / docx / html**：非目标。
- **无重试端点**：失败文档只能重新上传。
- **原始文件残留**：软删文档后文件仍在 `UPLOAD_DIR`，待 P1 清理任务。
- **token_count 为 NULL**：未接入 tokenizer。
- **pgvector 测试默认跳过**：需要 `TEST_POSTGRES_URL`，避免默认套件依赖 Docker。
- **无 HNSW/IVFFlat 索引**：S4 检索阶段再建。
- **无前端**：上传/状态/删除仅在 API 层验证。

## Merge Evidence

- RED checkpoint：`a69712c test: add P0 S3 ingestion and document coverage`
- GREEN checkpoint：`ab32f2e feat: implement document upload and async ingestion`
- 本报告随文档提交保留；若后续 squash，请把 RED/GREEN 摘要、真实 bge-m3 冒烟与 pgvector 结果写入 squash commit 正文。