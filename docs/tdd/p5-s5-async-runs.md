# P5-S5 异步运行与取消 — TDD 证据

- **Date:** 2026-11-23
- **Scope:** 工作流/协作 run 入 Arq、事件日志、SSE 回放与断线重连、queued/running 取消。
- **ADR:** [`ADR-0023`](../adr/0023-async-runs.md)

## 1. 行为缺口（RED）

P4 的 `POST /workflows/{id}/runs` 与 `POST /collaborations/runs` 在请求内同步执行并返回 SSE：

- 无法返回 `202 + run_id`；
- 没有 `/runs/{id}/events` 可回放；
- 刷新页面后没有事件源；
- 没有取消入口；
- 断开请求会取消 run。

新增/改造用例覆盖上述缺口，后端实现后通过。

## 2. 后端用例

`tests/test_async_runs.py`（7 条）：

| 用例 | 覆盖 |
|---|---|
| `test_create_run_returns_202_and_replays_events` | 202 + queued、事件 `seq=1..n`、完整回放、`after` |
| `test_run_events_and_cancel_are_workspace_scoped` | events/cancel 跨 workspace 404 |
| `test_cancel_queued_workflow_run_is_idempotent` | queued 直接 cancelled、重复取消、单条终态事件 |
| `test_cancel_running_workflow_stops_at_node_boundary` | 阻塞 provider → 取消标志 → 节点结束处停止 |
| `test_collaboration_run_is_queued_and_replays_events` | 协作 202、事件顺序、详情 completed |
| `test_unknown_workflow_run_events_return_404` | 不存在 run 的 404 |
| `test_worker_execution_is_idempotent_for_terminal_runs` | 终态 run 再次投递不重复写事件 |

`tests/test_sdk.py` 新增：

- 同步 `workflow_run` 先 POST 202 再 GET 事件；
- 异步 `workflow_run` 同上。

回归（后端实现后）：

```text
.venv/Scripts/python.exe -m pytest -q
370 collected, 366 passed, 4 skipped
```

```text
.venv/Scripts/python.exe -m ruff check app tests scripts sdk/python alembic
All checks passed!
```

## 3. 前端 / E2E

- 工作流与协作页改为“提交 → 设置 `?run=<id>` → 订阅事件”；刷新后从 URL 恢复。
- `streamRunEvents` 按 `id` 记录游标，连接中断后 `after=<seq>` 重连（最多 5 次）。
- 运行记录列表展示 `queued/running/completed/failed/cancelled`，支持取消。
- Playwright：

```text
3 passed
- login smoke
- workflow run shows node timeline and output
- workflow run reconnects from the run URL after reload
```

## 4. 真实部署验证（2026-11-23）

```text
docker compose exec api alembic upgrade head
d6e7f8a9b0c1 -> e7f8a9b0c1d2 (head)
/readyz -> database ok, redis ok
worker -> 9 functions (ingest, evaluation, workflow, collaboration + 5 cron)
```

真实 API（`http://192.168.29.100:8002`）使用 `workflow:run` API Key：

```json
{
  "run_202_status": "queued",
  "run_events": ["workflow_start", "node_start", "node_end", "workflow_end"],
  "run_seqs": [1, 2, 3, 4],
  "run_status": "completed",
  "replay_event_count": 4,
  "cancel_http_status": 200,
  "cancel_response_status": "running",
  "cancel_requested": true,
  "cancel_final_status": "cancelled",
  "cancel_last_event": "workflow_end",
  "cancel_last_status": "cancelled"
}
```

说明：提交返回 queued；事件按 seq 回放；`after=0` 可再次完整回放；运行中的两节点工作流取消后终态为 cancelled。

## 5. 已知边界

- worker 崩溃/被强制终止时，run 可能停留在 `running`，尚未实现心跳 stale-run 自动回收。
- 取消只在节点/步骤边界生效；正在执行的单个 LLM 调用不会被强制中断。
- 事件日志暂未设置 TTL/归档。
- 这是 breaking change：旧的同步 SSE POST 已移除；SDK、示例脚本、前端与 E2E 已同步更新。