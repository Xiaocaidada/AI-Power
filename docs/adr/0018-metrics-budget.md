# ADR-0018: 指标与预算告警

- **Status:** Accepted
- **Date:** 2026-11-22
- **Context:** P4 需要生产可观测性与成本护栏，但部署仍是单机/局域网。

## Decision

- **进程内指标注册表**：自研 counter/gauge/histogram，输出 Prometheus 文本（`/metrics`），不引入 `prometheus-client` 依赖。
- **指标范围**：HTTP 请求数/延迟、SSE 活跃流、token/成本、入库任务状态、provider 熔断状态；路径使用路由模板避免高基数。
- **预算**：按 workspace plan 的每日成本阈值（free 1 USD / pro 50 USD），在消息 finalize 时汇总当日 `usage_events.cost`；超限每天写一条 `audit_logs`（`budget.exceeded`），Redis 去重，可选 `BUDGET_WEBHOOK_URL`。
- **部署**：默认不启动 Prometheus；提供 `deploy/prometheus.yml` 与 compose `observability` profile。

## Consequences

- 单实例演示零依赖；重启后指标清零，多副本不聚合。
- `/metrics` 无鉴权，仅适合局域网；公网需前置鉴权/网络策略。
- 预算只覆盖消息用量，工作流/协作成本不在其中。
- 告警只落审计（管理端可查），无内置 Grafana/Alertmanager。

## Alternatives

- **`prometheus-client`**：生态好，但增加依赖且对演示无实质收益。
- **完整 Prometheus + Grafana + Alertmanager**：运维复杂度高，留作可选扩展。
- **数据库/云端计费**：超出 P4 的反目标。