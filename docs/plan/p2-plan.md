# P2 规划：从“单用户可用”到“平台化”

- **Status:** Confirmed（决策已锁定，2026-11-21；编码需按切片逐片确认）
- **Date:** 2026-11-21
- **Scope source:** [`PRODUCT-BRIEF.md`](../../PRODUCT-BRIEF.md) §3 P2、[`docs/product/CAPABILITY.md`](../product/CAPABILITY.md)
- **前置:** P1 已完成（2026-11-21），见 [`p1-plan.md`](./p1-plan.md)、[`p1-s6-deploy.md`](../tdd/p1-s6-deploy.md)

## 1. P2 目标

| 能力 | 完成标志 |
|---|---|
| 多租户隔离 | 同一 workspace 两名成员共享资源；不同 workspace 完全隔离；跨租户一律 404 |
| 模型广场 | 目录含上下文/价格/标签/健康状态；前端可对比 2–3 个模型 |
| 路由与降级 | `auto` 路由按优先级选择；首个 token 前失败可降级；流中失败给出明确错误 |
| 配额限流 | 按 workspace / 用户 / API Key 限制请求与 token；超限 429 + 配额响应头 |
| Trace 可观测 | 每次对话可按 `request_id` 查到检索/首 token/总耗时/错误码；7 天保留 |
| 阶段验收 | 3 分钟 demo：两用户同 workspace、跨 workspace 隔离、降级、429、trace 查看 |

P2 不追求收入：**不做计费/支付/成本面板**（P3）。

## 2. 现状与差距

已完成（P1）：

- 认证/刷新、用户级隔离、SSE 对话与引用、知识库与持久化队列、用量事件、API Key、完整前端、Docker 部署与压测。
- 请求 ID、结构化日志、每日备份、20 并发 20/20。

P2 必须补的差距：

| 差距 | 现状 | 影响 |
|---|---|---|
| 资源只属于个人 | 所有表按 `user_id` 过滤 | 无法团队协作，不符合“多租户” |
| 模型只有实时列表 | `/providers` 调上游 `list_models` | 无价格/上下文/标签，无法对比与路由 |
| 无路由/降级 | 会话固定 provider/model | 单 provider 故障即失败 |
| 无限额 | 仅登录限流 | 无法防滥用，无配额演示 |
| 无 trace | 只有访问日志与 `usage_events` | 无法解释一次回答的耗时构成 |
| P1 欠账 | 无分页、Python 聚合、无 Playwright、Key 无过期 | P2 数据量下会暴露 |

## 3. 关键决策（待确认）

| # | 决策 | 建议 | 备选 |
|---|---|---|---|
| D1 | 多租户形态 | **Workspace + 成员角色（owner/member）**；每个用户注册时自动创建个人 workspace；资源全部挂 `workspace_id` | 保持用户级 + 分享链接（轻，但不满足“多租户”） |
| D2 | 活跃租户切换 | **`X-Workspace-Id` 请求头** + 成员校验；JWT 不绑定 workspace | 切换时重签 JWT（每次切换多一次登录态变更） |
| D3 | 广场数据 | **DB 目录表 + 种子脚本**（provider 实时模型合并健康状态） | 纯实时 `/models`（无元数据、无法对比） |
| D4 | 路由策略 | 会话可显式选模型或选 `auto`；`auto` 按目录 `priority` 排序并在**首 token 前**降级 | 只在客户端重试（体验差、不可观测） |
| D5 | 配额模型 | **请求/分钟 + token/天**，按 workspace 计划（free/pro 静态配置）；Key 可单独限流 | 只做登录限流（不满足 P2） |
| D6 | Trace 存储 | **`traces` 表 + `request_id` 关联消息**，7 天保留，用户可查自己的 | 接 Prometheus/Grafana（部署更重，留 P2 可选） |
| D7 | 计费 | **不做**（P3） | 做虚拟额度与成本面板（范围膨胀） |
| D8 | 公网/HTTPS | 保持局域网；HTTPS 作为可选运维项 | P2 引入 Caddy + 域名（需要用户提供域名） |

> **已确认（2026-11-21）**：D1/D2 采用 Workspace + `X-Workspace-Id`；D5 采用 Workspace + Key 双层配额；D6 采用 traces 表 + 7 天保留；D8 保持局域网 HTTP。D3/D4/D7 按建议执行。

## 4. 切片与顺序

原则：先数据模型，再目录/路由，再配额，再可观测，最后前端与收口；每片可独立演示。

### P2-S1 多租户数据模型与隔离 — **已完成（2026-11-21）**（约 1.5 周）

- `workspaces(id, name, plan, created_at)`、`workspace_members(workspace_id, user_id, role)`。
- 现有资源加 `workspace_id`：`knowledge_bases`、`conversations`、`documents`、`ingestion_jobs`、`usage_events`、`api_keys`。
- 迁移：为每个已有用户建个人 workspace，回填全部资源；`workspace_id` 非空。
- 认证：`X-Workspace-Id` 校验成员身份；缺省用个人 workspace；所有查询按 workspace 过滤，跨租户 404。
- 成员管理：owner 按邮箱邀请已注册用户、移除成员；member 只读成员列表。
- API Key 归属 workspace，scope 增加 `workspace:read`（可选）。

验收：两用户同 workspace 可见共享 KB/会话；第三方 workspace 404；成员移除后立即失去访问；迁移可重复执行。

> **完成证据**：`docs/tdd/p2-s1-workspaces.md`。Postgres 实库 17 用户 → 17 个人 workspace，回填无 NULL；真实 API 验证共享/隔离/成员移除/Key 绑定。

### P2-S2 模型目录、广场与路由降级 — **已完成（2026-11-21）**（约 1.5 周）

- `model_catalog(provider_id, model_id, display_name, context_window, input_price, output_price, tags, priority, enabled)`；种子脚本合并 `/providers` 实时结果。
- `GET /models`：目录 + 健康状态（Redis 熔断：连续失败 N 次冷却 60s）。
- `GET /models/compare?ids=...`：返回并排元数据（价格、上下文、可用性）。
- 会话支持 `model = auto`：按 priority 选择健康 provider；首 token 前失败自动尝试下一个。
- 流中失败不可重试：发 `error` 事件（code=`provider_failed_after_start`），保留已生成内容。
- trace 记录每次尝试（provider、耗时、结果）。

验收：禁用首选 provider 后 `auto` 会话仍成功；全部不可用时返回 503 `no_provider_available`；对比接口返回 2–3 个模型差异。

> **完成证据**：`docs/tdd/p2-s2-routing.md`。真实环境验证目录/对比/单 provider `auto`；双 provider 降级与 503 由单测覆盖。

### P2-S3 配额与限流 — **已完成（2026-11-21）**（约 1 周）

- 计划配置：`free` / `pro`（请求/分钟、token/天、最大 Key 数）；workspace.plan 决定默认值。
- Redis 计数器：`quota:req:{workspace}:{minute}`、`quota:tokens:{workspace}:{day}`、`quota:key:{key_id}:{minute}`。
- 请求前检查；token 配额在消息 finalize 后按实际 usage 累加；NULL usage 按 0 计。
- 超限：429 + `code=quota_exceeded` + `Retry-After` + `X-Quota-Limit/Remaining/Reset`。
- 前端：`/settings/usage` 显示配额余量；429 显示明确提示。
- API Key 增加可选 `expires_at` 与 `rate_limit_per_minute`。

验收：连续请求触发 429；窗口过后恢复；不同 workspace/Key 互不影响；配额头准确。

> **完成证据**：`docs/tdd/p2-s3-quotas.md`。真实环境验证 Key 级 429、Key 数量上限与过期 401；workspace/token 配额由单测覆盖。

### P2-S4 Trace 可观测 — **已完成（2026-11-21）**（约 1 周）

- `traces(id, request_id, workspace_id, user_id, conversation_id, message_id, provider_id, model, retrieval_ms, ttft_ms, total_ms, status, error_code, attempts, created_at)`；`messages.request_id`。
- 对话链路写入：检索耗时、首 token、总耗时、provider 尝试次数、错误码。
- `GET /traces/{request_id}`（本人/本 workspace）；worker 每日清理 7 天前记录。
- 前端：助手消息“详情”抽屉展示阶段耗时与错误；不展示 prompt 原文。
- 可选：`/metrics` Prometheus 文本（不作为 P2 阻塞项）。

验收：一次 RAG 回答可看到检索与生成分段耗时；失败请求带 error_code；跨用户 404。

> **完成证据**：`docs/tdd/p2-s4-traces.md`。真实环境验证 completed trace（TTFT 6.7s / 总 8.1s）与跨租户 404；失败/auto/清理由单测覆盖。

### P2-S5 前端平台化（约 1 周）

- Workspace 切换器与成员管理页。
- 模型广场：卡片、筛选标签、对比表；会话页支持 `auto`。
- 配额页：余量、重置时间、计划说明。
- Trace 抽屉：阶段耗时、provider 尝试。
- 全部新增文案中英对齐；关键组件 Vitest；1 条 Playwright（workspace 隔离 + auto 降级）。

### P2-S6 收口与欠账（约 0.5–1 周，可与 S5 并行）

- 分页：conversations/documents/usage/traces（`limit/cursor`）。
- 用量聚合改 SQL（数据量增长前）。
- API Key 过期与轮换提示。
- Playwright 接入 CI（mock provider，避免真实模型依赖）。
- 文档：ADR-0009（租户）、0010（路由/配额）、0011（trace）；README 更新。

## 5. 排期（4–6 周）

| 顺序 | 切片 | 预估 |
|---|---|---|
| 1 | P2-S1 多租户 | 1.5 周 |
| 2 | P2-S2 目录与路由 | 1.5 周 |
| 3 | P2-S3 配额 | 1 周 |
| 4 | P2-S4 Trace | 1 周 |
| 5 | P2-S5 前端 | 1 周 |
| 6 | P2-S6 收口 | 0.5–1 周 |

## 6. P2 明确不做

- 计费、支付、发票、成本结算（P3）。
- 组织层级（org → team → project）、复杂 RBAC、SCIM。
- Agent/工具调用、Prompt 模板、工作流（P3）。
- 管理后台、Prometheus/Grafana 全套、日志平台。
- 公网、HTTPS、CDN（除非 D8 改为需要）。

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| workspace_id 迁移触及全部表 | 先建表回填、再切查询；迁移脚本幂等；部署前 `pg_dump` |
| 多租户过滤遗漏导致越权 | 统一 `workspace_scope` 依赖；每个资源补跨租户测试 |
| 配额误伤演示 | 演示账号使用 `pro`；前端显示余量；限流可配置 |
| 降级语义复杂（流中失败） | 只在首 token 前降级；流中失败明确报错，不重试 |
| Trace 数据增长 | 7 天保留 + 每日清理；只存元数据不存正文 |
| 范围膨胀 | 每片独立演示；未列入本计划的 P3 功能不提前做 |

## 8. P2 完成定义（DoD）

1. 两用户同 workspace 共享资源；第三用户跨 workspace 全部 404。
2. 模型广场可对比 ≥2 个模型；`auto` 在首选 provider 故障时成功降级。
3. 配额触发 429 并可恢复；响应头准确；Key 级限流生效。
4. 任一对话可按 `request_id` 查看检索/首 token/总耗时与错误码。
5. 前后端测试通过；覆盖率 ≥ 80%；至少 1 条 Playwright；CI 绿灯。
6. 文档：ADR-0009/0010/0011、P2 TDD 证据、README 更新。

## 9. 已确认事项（2026-11-21）

1. **D1/D2**：Workspace + 成员角色，`X-Workspace-Id` 切换；注册自动创建个人 workspace。
2. **D5**：配额按 workspace + API Key 双层；free/pro 静态计划。
3. **D6**：Trace 入库 7 天，用户按 `request_id` 查询；不接 Prometheus。
4. **D8**：保持局域网 HTTP，不做公网/HTTPS。

**门禁**：每片编码前需用户明确批准（与 P1 相同）。