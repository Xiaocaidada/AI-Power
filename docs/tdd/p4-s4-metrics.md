# TDD Evidence — P4-S4: Prometheus 指标与预算告警

- **Date:** 2026-11-21
- **Scope:** `/metrics` 文本指标、HTTP/SSE/token/cost/队列/熔断指标、每日成本预算告警、可选 Prometheus profile
- **Source:** [`docs/plan/p4-plan.md`](../plan/p4-plan.md) P4-S4（D7 指标、预算）

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 新增指标测试 | `pytest tests/test_metrics.py` | **4 passed** |
| 后端全量 | `pytest -q` | **300 passed, 3 skipped** |
| Lint/Format | `ruff check` / `ruff format --check` | 通过 |

## 交付

- **指标注册表**（`app/metrics.py`）：进程内 counter/gauge/histogram，输出 Prometheus 文本（`# HELP` / `# TYPE`），不引入额外依赖。
- **HTTP 指标**：`ai_power_http_requests_total{method,path,status}` 与 `ai_power_http_request_duration_seconds` 直方图（路径使用路由模板，避免高基数）；`/metrics` 自身不计数。
- **SSE**：`ai_power_sse_active_streams` 包裹对话、工作流、协作三类流式响应。
- **token/成本**：`ai_power_tokens_total{kind,provider,model}`、`ai_power_cost_usd_total{provider,model}`，来自消息 finalize、工作流与协作的 usage 记录。
- **运行状态**：`/metrics` 抓取时查询 `ingestion_jobs` 各状态数量，并按 provider 输出 `ai_power_circuit_open`。
- **预算告警**（`app/services/budget.py`）：按 workspace 计划（free 1 USD / pro 50 USD 每日）汇总当日 `usage_events.cost`；超限时每天写一条 `audit_logs`（`budget.exceeded`，含成本/阈值/日期），Redis 标记去重；可选 `BUDGET_WEBHOOK_URL` POST 通知。
- **部署**：`deploy/prometheus.yml` + compose `prometheus` 服务（`profiles: ["observability"]`，默认不启动），抓取 `api:8000/metrics`。
- **配置**：`QUOTA_FREE_DAILY_COST_USD`、`QUOTA_PRO_DAILY_COST_USD`、`BUDGET_WEBHOOK_URL`。

## Test Specification（新增 4）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 注册表输出 counter/gauge/histogram 文本 | `test_metrics_registry_renders_prometheus_text` | PASS |
| 2 | `/metrics` 返回 HTTP、队列与熔断指标 | `test_metrics_endpoint_exposes_http_queue_and_circuit_series` | PASS |
| 3 | 熔断打开时 gauge 为 1 | `test_metrics_circuit_gauge_reflects_open_state` | PASS |
| 4 | 超预算每天只写一条审计 | `test_budget_alert_is_written_once_per_day` | PASS |

## Known Gaps

- **进程内指标**：重启即清零，多副本不聚合；适合单实例演示。
- **`/metrics` 无鉴权**：依赖局域网访问控制；公网部署需加 token/网络策略。
- **预算只统计消息 `usage_events`**：工作流/协作成本在各自 run 表，未计入每日预算。
- **告警仅审计记录**：管理端审计页可查，无站内横幅/邮件；webhook 可选且未在测试中验证。
- **无 Grafana/Alertmanager**：只提供 Prometheus compose profile。
- **直方图为默认桶**，未按业务延迟调优。
- **前端无指标页面**。