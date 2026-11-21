# P4 规划：工作流、多 Agent 协作与生产化

- **Status:** In progress（D1–D9 已确认；S1–S4 已完成 2026-11-21，S5–S6 待逐片批准）
- **Date:** 2026-11-21
- **Scope source:** [`PRODUCT-BRIEF.md`](../../PRODUCT-BRIEF.md) §3 P3/P4、[`docs/plan/p3-plan.md`](./p3-plan.md)
- **前置:** P3 已完成（2026-11-21），见 [`p3-plan.md`](./p3-plan.md)、[`p3-s6-polish.md`](../tdd/p3-s6-polish.md)

## 1. P4 目标

| 能力 | 完成标志 |
|---|---|
| 工作流编排 | 可定义含 LLM / 检索 / 工具 / 条件 / 并行节点的 DAG，按版本执行并持久化每次 run |
| 多 Agent 协作 | planner 拆解 → worker 执行 → critic 复核（≤2 轮），复用 P3 Agent/工具，结果可追溯 |
| 运行可视化 | 工作流 run 时间线：节点状态、耗时、输入输出摘要；失败节点可定位 |
| 生产可观测 | `/metrics` Prometheus 文本（请求/延迟/token/成本/队列/熔断），预算阈值告警 |
| 平台运营 | 管理员可调整 workspace plan；关键操作审计扩展 |
| 阶段验收 | 3 分钟 demo：一次 DAG run（LLM→KB→条件→LLM）→ 并行节点 → planner/critic 协作 → 指标与预算告警 |

P4 仍**不做真实支付/计费**，不追求公网多租户 SaaS。

## 2. 现状与差距

已完成（P3）：多 Agent 工具框架（supervisor + retrieval/math、`kb_search`/`calculator`）、Prompt 模板与会话快照、成本快照与面板、管理后台与审计、SSE/trace、分页与 API 文档。

| 差距 | 现状 | 影响 |
|---|---|---|
| 无工作流 | 对话是单轮/多步 Agent，无跨节点编排与复用 | 无法演示“可编排的 AI 应用” |
| 多 Agent 仅委派 | supervisor 串行委派两个子 Agent | 缺少并行/评审式协作 |
| 可观测有限 | 访问日志 + traces 表 | 无法接 Prometheus / 做趋势告警 |
| 运营受限 | plan 固定、审计仅模型启停 | 演示运营闭环不完整 |
| 部署 | 局域网 HTTP | 公网演示需额外域名/证书 |

## 3. 关键决策（待确认）

| # | 决策 | 建议 | 备选 |
|---|---|---|---|
| D1 | P4 核心 | **工作流 DAG + 多 Agent 协作**为主线，生产化作为支撑 | 只做生产化/公网（差异化弱） |
| D2 | 工作流定义 | **DB 存储 + 不可变版本**：`workflows`、`workflow_versions`（nodes/edges JSON），节点类型白名单 | YAML 文件（无版本/权限） |
| D3 | 执行语义 | **asyncio 引擎**：顺序 + `parallel`（并发 ≤3）+ `condition`；节点超时、重试 ≤2；run/node 状态入库 | 引入 Temporal/Celery 编排（过重） |
| D4 | 节点类型 | `llm`、`kb_search`、`tool`、`agent`、`condition`、`parallel`/`join`；**不允许任意 Python** | 支持自定义代码节点（安全风险） |
| D5 | 多 Agent 协作 | **planner → worker（并行）→ critic（≤2 轮）**，复用 P3 工具与步数预算 | 继续单 supervisor 串行 |
| D6 | 前端 | **表单式编辑器 + run 时间线**；拖拽画布（React Flow）作为可选 stretch | 直接上拖拽画布（工期风险） |
| D7 | 指标 | **`/metrics` Prometheus 文本**（请求、延迟、token、成本、队列、熔断）；可选 compose profile | 必装 Prometheus/Grafana（部署复杂） |
| D8 | 公网/HTTPS | **保持局域网**；如提供域名，加 Caddy profile 作为可选 | P4 强制公网 HTTPS（需域名/证书） |
| D9 | 权限/计费 | 仅管理员可改 workspace plan + 扩展审计；**不做支付、复杂 RBAC** | 组织/SSO/账单（超出范围） |

> **待确认（2026-11-21）**：D1–D9 按建议执行，或指出要改的项。确认前不写代码。

## 4. 切片与顺序

原则：先工作流数据模型与引擎，再节点/可视化，再多 Agent 协作，再可观测与运营，最后收口。

### P4-S1 工作流模型与执行引擎 — **已完成（2026-11-21）**（约 1.5–2 周）

- 表：`workflows(id, workspace_id, name, description, created_by, deleted_at)`、`workflow_versions(id, workflow_id, version, definition JSON, created_at)`（不可变）、`workflow_runs(id, workflow_id, version_id, workspace_id, user_id, status, error_code, started_at, finished_at, total_ms)`、`workflow_node_runs(id, run_id, node_id, node_type, status, attempts, input_summary, output_summary, error_code, duration_ms)`。
- `definition`：`{nodes:[{id,type,config}], edges:[{from,to,condition?}]}`；启动时校验 DAG（无环、入口唯一、节点配置 Pydantic）。
- 引擎（`app/services/workflow/`）：按拓扑执行；节点超时/重试；`llm` 复用 provider + AgentRunner 的计量；`kb_search` 复用工具；运行结果持久化，SSE `workflow_start/node_start/node_end/workflow_end`。
- API：workflow CRUD、版本创建、`POST /workflows/{id}/runs`、`GET /workflows/runs/{run_id}`、`GET /workflows/{id}/runs`。
- 测试：DAG 校验（环、孤儿节点）、顺序执行、节点失败重试、run 状态机、workspace 隔离。

> **完成证据**：`docs/tdd/p4-s1-workflows.md`。线性 DAG 的 `llm`/`kb_search` 节点、版本化定义、run/node 持久化、SSE 与 API 已完成；分支/并行留待 S2。

### P4-S2 节点类型与运行可视化 — **已完成（2026-11-21）**（约 1.5 周）

- 增加 `parallel`（fan-out/join，并发上限）、`condition`（表达式白名单）、`tool`、`agent` 节点。
- 每节点输入/输出摘要（截断，不存全文）；失败节点记录 `error_code`。
- 前端 `/workflows`：列表、表单式创建/编辑（线性 + 分支）、run 列表与时间线；运行中轮询/SSE 展示节点状态。
- 验收：LLM→KB→condition→LLM 跑通；parallel 两分支并发；单节点失败可重试并看到错误。

> **完成证据**：`docs/tdd/p4-s2-workflow-nodes.md`。`tool`/`agent`/`condition`/`parallel`/`join` 节点、分支跳过与合并、并发上限、`/workflows` 页面（JSON 定义编辑 + SSE 时间线）已完成；编辑器不是拖拽画布。

### P4-S3 多 Agent 协作 — **已完成（2026-11-21）**（约 1–1.5 周）

- 新增协作模式：`planner` 拆解任务为子任务 → `worker` 并行执行（复用 retrieval/math/general）→ `critic` 评分/提出修改（≤2 轮）。
- 全局预算：总步数、并发、单任务超时；每步配额检查；所有 worker/critic 调用计入同一消息/run 成本。
- 前端：协作 run 的 agent 时间线（planner/worker/critic 节点）。
- 验收：planner 产出 ≥2 子任务并并行；critic 最多两轮后收敛；trace 记录各角色耗时与 token。

> **完成证据**：`docs/tdd/p4-s3-collaboration.md`。planner/worker/critic 流程、revise 重做、全局步数预算、run/step 持久化与 `/collaborations` 时间线已完成；成本只记协作表。

### P4-S4 生产可观测与预算告警 — **已完成（2026-11-21）**（约 1 周）

- `/metrics`：HTTP 请求数/延迟直方图、SSE 活跃流、token/成本计数、队列长度、死信、熔断状态（文本格式，不依赖额外库或轻量 `prometheus_client`）。
- 预算：workspace 日成本阈值（settings/plan），超阈值写审计 + 管理端提示；可选 webhook。
- compose 可选 `profiles: ["observability"]` 启动 Prometheus（Grafana 可选）。
- 验收：抓取 `/metrics` 能看到关键序列；超预算触发一次告警记录。

> **完成证据**：`docs/tdd/p4-s4-metrics.md`。指标注册表、HTTP/SSE/token/成本/队列/熔断指标、每日预算审计与可选 Prometheus profile 已完成；预算只覆盖消息用量。

### P4-S5 运营增强与可选 HTTPS（约 0.5–1 周）

- 管理端：修改 workspace plan、查看 run 失败率；审计扩展（plan 变更、workflow 发布）。
- 可选：Caddy 反向代理 + 自动 HTTPS（仅当用户提供域名；默认不启用）。
- 验收：管理员改 plan 后配额立即生效；审计可查。

### P4-S6 收口（约 1 周）

- 工作流 SDK/示例脚本、quickstart 扩展、压测脚本覆盖 workflow run。
- ADR：0016（工作流引擎）、0017（多 Agent 协作）、0018（指标与预算）。
- README/CLAUDE 更新；P4 TDD 证据；Playwright 覆盖 workflow run 时间线。
- 不做：暗色主题已完成；不新增移动端。

## 5. 排期（约 5–7 周）

| 顺序 | 切片 | 预估 |
|---|---|---|
| 1 | P4-S1 工作流引擎 | 1.5–2 周 |
| 2 | P4-S2 节点与可视化 | 1.5 周 |
| 3 | P4-S3 多 Agent 协作 | 1–1.5 周 |
| 4 | P4-S4 指标与预算 | 1 周 |
| 5 | P4-S5 运营与可选 HTTPS | 0.5–1 周 |
| 6 | P4-S6 收口 | 1 周 |

## 6. P4 明确不做

- 真实支付/计费/发票、充值退款。
- 复杂 RBAC、SSO、SCIM、组织层级。
- 任意 Python/JS 代码节点、插件市场。
- 公网强制 HTTPS（仅可选 Caddy profile）。
- 微调/训练、自建向量库或推理引擎、移动端 App。
- 拖拽式画布（除非 S2 有余量，作为 stretch）。

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| 工作流范围膨胀 | 节点类型白名单；先顺序+并行+条件，不做循环/子工作流 |
| DAG 执行死锁/环 | 创建时拓扑校验；运行时步数/超时上限；run 可取消 |
| 多 Agent 成本爆炸 | 并发 ≤3、总步数预算、critic ≤2 轮、每步配额检查 |
| 可视化工期 | 表单式编辑器优先；React Flow 仅 stretch |
| 指标依赖 | `/metrics` 文本优先，Prometheus 仅 compose profile |
| 公网安全 | 默认局域网；HTTPS/Caddy 需域名与用户确认 |
| 测试依赖真实模型 | 全部用脚本化 provider + 固定 workflow 定义（延续 D10） |

## 8. P4 完成定义（DoD）

1. DAG 工作流可创建、发布版本、执行；run/node 状态与耗时可通过 API/UI 查看。
2. 条件与并行节点可用，并发有上限；失败节点可重试并定位。
3. planner/worker/critic 协作可演示，轮次与成本有上限，trace 可追溯。
4. `/metrics` 暴露请求/延迟/token/成本/队列/熔断；预算告警落审计。
5. 管理员可改 workspace plan，配额立即生效；关键操作有审计。
6. 前后端测试通过，覆盖率 ≥80%；至少 1 条 workflow Playwright；CI 绿灯。
7. 文档：ADR-0016/0017/0018、P4 TDD 证据、quickstart 扩展。

## 9. 门禁

- 本计划需用户确认 D1–D9 后才进入编码。
- 与 P1–P3 相同：**每片编码前需用户明确批准**；每片完成产出 TDD 证据并合回 `main`。
- 未列入本计划的 P5 功能不得提前实现。