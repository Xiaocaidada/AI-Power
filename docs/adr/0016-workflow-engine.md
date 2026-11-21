# ADR-0016: 工作流引擎与节点模型

- **Status:** Accepted
- **Date:** 2026-11-22
- **Context:** P4 需要可复用的 AI 编排能力，同时避免引入 Temporal 等重型基础设施。

## Decision

- **DB 存储 + 不可变版本**：`workflows` + `workflow_versions(definition JSON)`；发布新版本而不是修改旧版本。
- **节点白名单**：`llm`、`kb_search`、`tool`、`agent`、`condition`、`parallel`、`join`；**不允许任意代码节点**。
- **校验**：唯一 id、单入口、全部可达、无环；condition 恰好 true/false 两条出边；parallel ≥2 出边、join ≥2 入边；其他节点 ≤1 出边。
- **执行器**：事件驱动调度。节点在所有入边被决定后运行；未选中的分支标记 `skipped` 并向后传播；join 等待所有活跃入边；parallel 并发受 `WORKFLOW_PARALLEL_LIMIT` 限制。
- **可靠性与成本**：节点超时、ProviderError 重试、每个 LLM 节点检查配额；`workflow_runs` / `workflow_node_runs` 持久化状态、尝试次数、耗时与截断摘要；run 成本只记在 run 表。
- **接口**：`POST /workflows/{id}/runs` 同步 SSE（`workflow_start/node_start/node_end/workflow_end`）。

## Consequences

- 无需额外基础设施；演示与部署简单。
- 长工作流占用请求连接；不支持跨进程恢复/断点续跑。
- 工作流成本未进入 `usage_events`，用量页不显示。
- 无拖拽画布，前端使用 JSON 定义编辑。

## Alternatives

- **Temporal/Celery 编排**：可靠但组件多、学习成本高，超出作品集范围。
- **任意 Python 节点**：灵活但存在代码执行风险。
- **YAML 文件定义**：缺版本/权限/审计。