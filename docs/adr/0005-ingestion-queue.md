# ADR-0005: P1 持久化入库队列与文件生命周期

- **Status:** Accepted
- **Date:** 2026-11-21
- **Deciders:** 项目作者
- **Related:** [`ADR-0002`](./0002-ingestion.md)、[`docs/plan/p1-plan.md`](../plan/p1-plan.md) S2、[`docs/tdd/p1-s2-queue.md`](../tdd/p1-s2-queue.md)

## Context

P0 使用 FastAPI `BackgroundTasks` 执行 `ingest_document`：

- 进程重启/崩溃会丢失未完成任务，文档可能永久停留在 `parsing`/`embedding`。
- 失败文档只能重新上传，没有重试端点。
- 软删文档后原始文件残留在 `UPLOAD_DIR`。
- `ingestion_jobs` 只有 `queued/running/succeeded/failed`，没有租约、开始/结束时间与死信状态。

P1 已引入 Redis（登录限流），用户确认采用 Arq。

## Decision

### 1. Arq worker + Redis

- `app/worker.py` 定义 `WorkerSettings`，由 compose 的 `worker` 服务执行 `arq app.worker.WorkerSettings`。
- API 只负责入队：`ArqJobQueue.enqueue_ingestion(document_id)` → `enqueue_job("ingest_document_job", str(document_id), _job_id=f"ingest:{document_id}")`。
- 首次上传使用 `_job_id=f"ingest:{document_id}"` 去重；**手动重试与租约回收使用随机后缀**（`unique=True`），避免与 `keep_result` 窗口内的旧 job id 冲突而被 Arq 静默忽略。
- API 与 worker 共享 `uploads` 命名卷（同一 `UPLOAD_DIR`），否则 worker 读不到文件。

### 2. 任务状态机

`queued → running → succeeded | failed | dead`

- `attempts` 每次执行 +1；`started_at` / `finished_at` 记录时间。
- 执行时设置 `lease_expires_at = now + INGESTION_LEASE_MINUTES`（默认 15 分钟），成功/失败后清空。
- 失败先记为 `failed`；worker 按次数决定重试或 `dead`。

### 3. 应用级重试（不使用 Arq 自带重试）

- `WorkerSettings.max_tries = 1`，避免 Arq 重试与业务 attempts 双重计数。
- `ingest_document` 返回 `IngestionOutcome(status, error_code, attempts)`。
- 失败且 `attempts < INGESTION_MAX_ATTEMPTS`（默认 3）：
  - `schedule_retry(document_id)`：文档回到 `uploaded`、job 回到 `queued`，保留 attempts；
  - 以 `_defer_by = 2 ** attempts` 秒重新入队（2s、4s），job id 使用 `retry:{uuid}` 唯一后缀。
- 达到上限：`mark_job_dead(document_id)` → job `dead`，文档保持 `failed`，不再自动重试。
- 手动 `POST /documents/{id}/retry` 将 attempts 归零，给用户一次完整重试预算。

### 4. 租约回收

- 每分钟 cron `recover_stale_jobs_job`：
  - 查找 `status=running AND lease_expires_at < now` 的任务；
  - 重置为 `queued`、清空租约并以唯一 job id 重新入队。
- 覆盖 worker 崩溃/重启场景。
- 代价：执行时间超过租约（15 分钟）仍存活的任务可能被再次入队；入库是幂等的（先删旧 chunk 再写入），因此可接受。

### 5. 入队失败处理

- 上传/重试时入队抛错 → 文档 `failed + queue_unavailable`，job `failed`，返回 **503** 且 detail 携带 `document_id`。
- 不留下"看似排队、实际永不执行"的记录；用户可通过 retry 端点重试。

### 6. 文件生命周期

- 删除文档：软删 + 同步删除 chunks/embeddings + 删除磁盘文件（失败只记 warning）。
- 每日 03:00 cron `cleanup_orphan_files_job`：删除 `UPLOAD_DIR` 中无 `documents` 记录且修改时间超过 24 小时的文件。
- 重复上传命中已有文档时，仍立即删除新写入的临时文件。

### 7. token_count

继续为 NULL。P1 不引入 tokenizer；上下文预算按字符计算（ADR-0003）。

## Consequences

### Positive

- 任务可跨进程重启恢复；失败可重试、可观测（attempts/时间/错误）。
- 入库不再依赖请求生命周期；API 响应更快（不再等待解析/向量化）。
- 死信与租约让"卡住"成为可查询状态，而不是静默丢失。
- 文件泄漏有同步删除 + 定期兜底。

### Negative / Risks

- **至少一次执行**：租约过期回收可能导致同一文档被处理两次；依赖入库幂等（删除旧 chunk 后重建）。
- **Arq/Redis 成为硬依赖**：Redis 故障时上传返回 503（`/readyz` 可见）。
- **无任务优先级/限流**：大量上传会同时占用 worker；P2 可加队列分片或并发上限。
- **cron 包装函数覆盖率低**：`recover_stale_jobs_job` / `cleanup_orphan_files_job` 逻辑薄，核心逻辑在可测试的服务函数中。
- **token_count 仍为空**。

### Alternatives Considered

| 方案 | 未采用原因 |
|---|---|
| 继续用 BackgroundTasks | 不持久，P1 明确要修复 |
| Celery | 同步模型更重，需要额外配置；Arq 与 async 栈一致 |
| Arq 自带 `max_tries` | 无法自然映射 `dead` 状态与业务 attempts；与手动重试冲突 |
| 用 Postgres 做队列表 + 轮询 | 少一个 Redis 依赖，但需自建租约/唤醒，重复造轮子 |
| 删除文件只靠 cron | 用户删除后磁盘仍占用，体验不一致 |
| 直接删除物理文件且忽略错误 | 文件锁/权限问题会 500；改为 warning + cron 兜底 |

## Follow-ups

1. 观察 worker 并发与长文档（>15 分钟）是否需要调大租约或任务超时。
2. P2：任务优先级、每用户并发限制、失败告警。
3. 如需 token_count，引入 tokenizer 并回填。
4. 为 cron 包装函数补集成测试（真实 Redis + worker）。