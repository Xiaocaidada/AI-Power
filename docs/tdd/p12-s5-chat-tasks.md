# P12-S5 长任务运行层

日期：2026-11-24
状态：已完成（长任务运行层 MVP）

## 决策记录

按安全默认自行确定：

- 分享链接：仅工作区成员可用，不开放匿名公开；默认 7 天，最长 30 天（已实现）。
- 代码片段：仅创建者可见；任务按项目/工作区，不跨工作区共享。
- 学习简答：继续确定性匹配，不启用 LLM 判分。
- SearXNG：允许用户配置内网地址，不新增日限额。
- 长任务：S5 只搭运行层；深度研究与 Agent 执行分别留给 S6/S7。

## 目标

提供可恢复、可暂停、可取消、可重试的通用长任务运行层，供后续深度研究和 Agent 执行复用。

## 实现

### 数据

- `chat_tasks`：
  - workspace/user、conversation、kind、title、status
  - input/plan/checkpoint/result
  - error_code、attempts
  - pause_requested_at、cancel_requested_at、lease_expires_at
  - created/started/finished
- `chat_task_events`：
  - task_id、seq、event、payload、created_at
  - `(task_id, seq)` 唯一
- 迁移：`c0d1e2f3a4b5_p12_s5_chat_tasks.py`。

### 运行模型

- 状态：`queued|running|waiting_approval|paused|completed|failed|cancelled`。
- `llm_steps` 为当前内置 kind：每个 step 是一次真实非流式模型调用（`usage_events.source='chat_task'`）。
- 创建时 `auto` 会解析成具体 provider/model，避免入库后无法执行。
- 每步完成后：
  - 更新 `checkpoint.completed_steps` 与 outputs
  - 更新 plan step 状态
  - 追加 `step_completed`
- 失败保留已完成 checkpoint；重试从下一步继续，不重复已成功步骤。
- 租约 `lease_expires_at` 每步续期；启动与每分钟 cron 重新入队过期 `running` 任务。

### API

- `POST /chat-tasks`（202）
- `GET /chat-tasks?conversation_id=&status_filter=`
- `GET /chat-tasks/{id}`
- `POST /chat-tasks/{id}/pause`
- `POST /chat-tasks/{id}/resume`
- `POST /chat-tasks/{id}/cancel`
- `POST /chat-tasks/{id}/retry`
- `GET /chat-tasks/{id}/events?after=`（`Last-Event-ID` 兼容）

### 事件

- `task_created`
- `task_started`
- `step_started`
- `step_completed`
- `task_pause_requested` / `task_paused`
- `task_resumed`
- `task_cancel_requested` / `task_cancelled`
- `task_retry_requested`
- `task_requeued`
- `task_completed`
- `task_failed`
- `seq` 单调递增；SSE 回放后 tail，终态或暂停时关闭。

### 控制语义

- 暂停：queued 立即 paused；running 只记录请求，在下一步开始前进入 paused。
- 取消：queued/paused 立即 cancelled；running 在步骤边界 cancelled；重复取消幂等。
- 恢复：paused → queued 并重新入队，checkpoint 保留。
- 重试：failed → queued 并重新入队，checkpoint 保留。

## 测试

- `tests/test_p12_s5_chat_tasks.py`：
  - 两步任务完成、结果与 checkpoint。
  - 事件 seq 连续、回放过滤。
  - 暂停/恢复。
  - running 请求在步骤边界暂停。
  - 取消幂等。
  - 失败后从 checkpoint 重试。
  - 跨用户 404。
  - 过期租约重新入队。
- 全量：`ruff check .`、`pytest -n auto`。

## 边界

已解决：

- 刷新/断线后可通过 `GET /chat-tasks/{id}` 与 events 回放恢复状态。
- 暂停在安全步骤边界生效。
- 取消幂等。
- 事件 seq 单调。
- 重试不重复已完成步骤。
- 过期运行任务自动重新入队。

后续切片：

- `kind="research"` 的研究步骤与报告：`P12-S6`。
- `kind="agent"` 的工具执行、审批与时间线：`P12-S7`。
- `waiting_approval` 状态已预留，但审批 API/UI 尚未实现。
- 长任务前端页面：随 S6/S7 的业务页面一起提供。
- 任务级 token/成本上限：与计费策略一起设计。

明确不做（真实外部集成）：

- 不执行外部支付、发布、删除、发送等副作用。
- 不伪造研究结果或 Agent 工具成功。
- 不提供匿名任务访问。

需要用户决策：

- 无（本次已按安全默认确定）。