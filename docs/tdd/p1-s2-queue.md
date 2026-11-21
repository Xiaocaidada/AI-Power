# TDD Evidence — P1-S2: Durable ingestion queue and file lifecycle

- **Date:** 2026-11-21
- **Scope:** P1-S2（Arq worker、任务状态机、租约回收、重试/死信、手动重试端点、文件清理）
- **Source:** [`docs/plan/p1-plan.md`](../plan/p1-plan.md) S2、[`ADR-0005`](../adr/0005-ingestion-queue.md)、[`ADR-0002`](../adr/0002-ingestion.md)
- **Test runner:** pytest（Python 3.13.15）；默认 SQLite；队列用 InlineQueue 依赖覆盖
- **Commits:** RED/GREEN 见提交历史

## User Journeys

1. 作为用户，上传后不必等待解析/向量化完成，接口立即返回；后台任务在进程重启后仍会完成。
2. 作为用户，失败文档可以点击重试，而不是重新上传。
3. 作为运维者，我能看到任务开始/结束时间、尝试次数、死信状态。
4. 作为用户，删除文档后磁盘文件也被清理。
5. 作为维护者，worker 崩溃后过期租约的任务会被自动重新入队。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| RED | `.venv/Scripts/python.exe -m pytest tests/test_queue.py tests/test_worker.py tests/test_maintenance.py tests/test_documents.py tests/test_migrations.py` | `ImportError: cannot import name 'IngestionOutcome'`；`ModuleNotFoundError: app.services.queue`；conftest `fake_queue` 导入失败 |
| GREEN | `.venv/Scripts/python.exe -m pytest` | `169 passed, 3 skipped` |
| Coverage | `... --cov=app --cov-report=term-missing` | `TOTAL 1576 81 95%` |
| Lint | `... -m ruff check .` | `All checks passed!` |
| Format | `... -m ruff format --check .` | 通过 |

**GREEN 前实现范围**：`IngestionOutcome` / 租约 / `schedule_retry` / `mark_job_dead`、Arq 队列服务、worker（重试退避、死信、租约回收、孤儿清理）、`POST /documents/{id}/retry`、上传入队失败 503、删除文件、迁移 0002、compose worker。

## 真实环境验证

### 1. 迁移 0002（WSL Postgres）

```
alembic upgrade head → Running upgrade 98341c2813c8 -> 0270a2ddcf33
ingestion_jobs 列   → started_at, finished_at, lease_expires_at（新增）
索引                → ix_ingestion_jobs_status
```

### 2. 容器端到端（API + worker + 真实 bge-m3）

见文末「端到端验证」。

## Test Specification

### Queue service（`tests/test_queue.py`，4）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 入队使用 `ingest_document_job` 与 `_job_id=ingest:<doc>` 去重 | `test_arq_queue_enqueues_with_deduplicated_job_id` | PASS |
| 2 | 只回收租约过期的 running 任务并重新入队 | `test_recover_stale_jobs_requeues_only_expired_leases` | PASS |
| 3 | 达到上限标记 dead，清空租约并写 finished_at | `test_mark_job_dead_sets_dead_and_finished_at` | PASS |
| 4 | 重试前把 job 重置为 queued、文档回到 uploaded | `test_schedule_retry_resets_job_and_document` | PASS |

### Worker（`tests/test_worker.py`，3）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 5 | 失败且未达上限：调度重试并以 2^attempt 秒退避入队 | `test_worker_retries_failed_ingestion_with_backoff` | PASS |
| 6 | 达到上限：标记 dead，不再入队 | `test_worker_marks_dead_after_max_attempts` | PASS |
| 7 | 成功：不重试、不标记 dead | `test_worker_does_nothing_on_success` | PASS |

### Maintenance（`tests/test_maintenance.py`，1）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 8 | 只删除超过 24h 且无 Document 记录的文件 | `test_cleanup_orphan_files_removes_only_old_unreferenced_files` | PASS |

### Documents API（`tests/test_documents.py` 新增 5）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 9 | 上传后调用队列，且只入队一次 | `test_upload_enqueues_ingestion` | PASS |
| 10 | 失败文档重试后重新入库并变为 ready | `test_retry_failed_document_reingests` | PASS |
| 11 | 非 failed 文档重试 → 409 | `test_retry_ready_document_returns_409` | PASS |
| 12 | 删除文档同时删除磁盘文件 | `test_delete_removes_stored_file` | PASS |
| 13 | 队列不可用 → 503 + 文档 failed/queue_unavailable | `test_upload_marks_failed_when_queue_unavailable` | PASS |

### Migrations（`tests/test_migrations.py` 更新）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 14 | 迁移 head 包含 job 租约/时间列 | `test_alembic_upgrade_head_creates_schema` | PASS |

### 既有测试更新

- `tests/conftest.py`：新增 autouse `InlineQueue`，覆盖 `get_queue`，让上传测试同步执行入库。
- 上传测试从 `BackgroundTasks` 语义迁移到队列依赖覆盖；响应与状态断言保持不变。

## Coverage

```
TOTAL                             1576     81    95%
app/worker.py                     76%（未覆盖 cron 包装函数）
```

未覆盖：`recover_stale_jobs_job` / `cleanup_orphan_files_job` 的包装层（核心逻辑在已覆盖的服务函数）、`vector.py` 方言分支等既有边角。

## Known Gaps

- **至少一次执行**：租约过期可能重复处理；依赖入库幂等。
- **token_count 仍为 NULL**。
- **worker 并发/优先级未配置**：默认并发，多个大文档会排队。
- **cron 包装函数无集成测试**：真实 Redis + worker 的定时触发未自动化。
- **手动重试会清空 attempts**：用户可无限手动重试（每次重新给 3 次预算）。
- **无失败告警**：dead 任务只能查库/日志。

## 端到端验证

环境：`docker compose up -d api worker`（真实 Postgres/Redis/bge-m3，宿主端口 8002）。

### 1. 正常入库

```
upload                  → 202 {"status":"uploaded"}
document after worker   → ready, page_count=1
ingestion_jobs          → succeeded | attempts=1 | started_at 有值 | finished_at 有值 | lease 已清空
```

### 2. 文件生命周期

```
删除前  docker exec api test -f /app/uploads/<storage_path> → 存在
DELETE  /documents/{id} → 204
删除后  docker exec api test -f /app/uploads/<storage_path> → 不存在
documents.deleted_at    → 已写
```

### 3. 自动重试 → 死信

上传非法 PDF（`broken3.pdf`）：

```
upload                   → 202
ingestion_jobs           → dead | attempts=3
```

worker 日志显示 2s / 4s 退避重试，3 次失败后标记 `dead`。

### 4. 手动重试

```
POST /documents/{id}/retry → 202
ingestion_jobs             → dead | attempts=3（重新走满 3 次预算）
```

### 5. 真实环境发现的缺陷（已修复）

| 缺陷 | 现象 | 修复 |
|---|---|---|
| Arq 退避参数写错 | `_defer` 被当成任务 kwarg，报 `unexpected keyword argument '_defer'` | 改用 `_defer_by` |
| 重试 job id 冲突 | `retry:{attempts}` 在 `keep_result` 窗口内重复，Arq 静默忽略入队 | 每次重试使用 `retry:{uuid}` 唯一后缀 |
| 手动重试 job id 冲突 | 复用 `ingest:<doc>` 被上一轮结果占用 | `enqueue_ingestion(unique=True)` |
| 构建过慢 | `pip wheel` 走 pypi.org，单次构建 >10 分钟 | Dockerfile 默认清华镜像 + BuildKit pip cache mount；构建降至 **21s / 增量 2–39s** |

**构建镜像**：`Dockerfile` 支持覆盖镜像源：

```
docker compose build --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ api
```