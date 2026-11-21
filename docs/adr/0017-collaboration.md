# ADR-0017: planner → worker → critic 协作

- **Status:** Accepted
- **Date:** 2026-11-22
- **Context:** P3 的 supervisor 只能串行委派，缺少并行执行与复核。P4 需要可演示的“多 Agent 协作”，同时控制成本。

## Decision

- **三角色流程**：planner 拆解 → worker 并行执行 → critic 复核；critic 返回 `accept`（含最终答案）或 `revise`（反馈），最多 `COLLABORATION_MAX_ROUNDS`（默认 2）轮。
- **计划协议**：planner 必须输出 JSON，2–`COLLABORATION_MAX_TASKS` 个任务，`agent ∈ retrieval|math|general`，id 唯一；不合法即失败（`invalid_plan`）。
- **worker**：复用 P3 `AgentRunner`，通过 `root_agent` 指定 retrieval/math，general 映射 supervisor；并发受 `COLLABORATION_PARALLEL_LIMIT` 限制，单任务超时。
- **全局预算**：`COLLABORATION_MAX_STEPS` 限制所有 LLM/Agent 步；每步检查 workspace 配额；token 与成本写入 `collaboration_runs` 与 `collaboration_steps`。
- **接口**：`POST /collaborations/runs` SSE；`GET /collaborations/runs/{id}` 与分页列表；workspace 隔离。
- **前端**：`/collaborations` 显示计划、worker/critic 时间线与最终结果。

## Consequences

- 支持并行与“评审-修订”，演示效果强于单 supervisor。
- 依赖模型遵循 JSON 协议；revise 会重跑全部 worker，成本可能翻倍。
- critic 无数值评分；协作成本未写 `usage_events`。
- 同步 SSE 执行，长协作占用连接。

## Alternatives

- **仅 supervisor 串行**：无法演示并行/复核。
- **把协作做成工作流节点**：耦合两种编排语义，调试复杂。
- **引入多 Agent 框架（AutoGen/LangGraph）**：依赖重、可控性差。