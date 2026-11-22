# ADR-0023: 工作流/协作异步运行与事件回放

- **Status:** Accepted
- **Date:** 2026-11-23
- **Context:** P4 的 `POST /workflows/{id}/runs` 与 `POST /collaborations/runs` 在请求内同步执行并直接返回 SSE；断开页面会取消 run，长任务占连接，刷新后无法恢复时间线，也没有取消入口。

## Decision

- **提交与执行分离**：POST 只校验、创建 `queued` run（保存 `kb_id`、`api_key_id` 与输入），入 Arq 队列后返回 `202 {"run_id","status":"queued"}`。API/worker 通过 `wfrun:<run_id>` / `collab:<run_id>` 稳定 job id 去重。
- **事件日志**：`workflow_run_events` / `collaboration_run_events` 存 `(run_id, seq, event, payload, created_at)`，`seq` 单调递增；事件由 worker 消费 runner 后逐条追加，页面只读事件流。
- **SSE 回放 + tail**：`GET /workflows/runs/{run_id}/events?after=seq`（协作同理）先回放已落库事件，再每 300ms 轮询 tail；事件带 `id: <seq>`，支持 `Last-Event-ID` 或 `after` 断线续传；终态后关闭。若 run 已终态但事件日志缺失终态事件，服务端合成一条终态事件，避免客户端悬挂。
- **取消**：`POST /workflows/runs/{run_id}/cancel`（协作同理）。`queued` 直接置为 `cancelled` 并写终态事件；`running` 写 `cancel_requested_at`，runner 在节点/步骤边界检查并停止，终态写 `cancelled`；重复取消幂等。
- **状态机**：`queued → running → completed|failed|cancelled`。worker 以条件更新认领 queued run，避免重复执行；终态 run 再投递也不会重复写事件。
- **权限**：提交工作流需要 `workflow:run`（JWT 或 API Key）；事件与取消也使用同一 scope，便于 SDK 用 API Key 消费。协作提交/事件/取消使用 `chat:write`。跨 workspace 一律 404。
- **用量**：异步执行仍走 P5-S4 的 `usage_events`（`source=workflow|collaboration`、node/step 归属、API Key 归属），run 汇总与账本金额一致。
- **兼容性**：这是 breaking change；SDK 的 `workflow_run` / `collaboration_run` 改为“提交 + 订阅事件”，并新增 `start_*`、`*_run_events`、`cancel_*`。`scripts/workflow_example.py` 与 Playwright 同步更新。

## Consequences

- 页面刷新/网络抖动不再丢 run；客户端可从 `after` 恢复完整时间线。
- 长任务不再占用 API 请求连接，SSE 连接只读事件。
- 事件按 run 顺序写入；单 run 只有 worker 一个写入者，避免 seq 竞争。
- worker 崩溃或 Arq job 被强制终止时，run 可能停留在 `running`；当前依赖 job timeout / 运维介入，尚未实现基于心跳的 stale-run 自动回收（后续切片）。
- 事件日志随 run 生命周期保留；长期运行需要 TTL/归档策略。
- 取消只在节点/步骤边界生效，单个正在执行的 LLM 调用不会被强制中断。

## Alternatives

- **Redis pub/sub 实时通道**：多一个实时依赖，且仍需持久化回放。
- **保持同步 SSE**：无法解决刷新丢 run、连接占用与取消。
- **每客户端直接重跑**：重复计费且破坏状态一致性。