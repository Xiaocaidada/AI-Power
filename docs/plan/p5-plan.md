# P5 规划：检索质量、评测平台与开放平台

- **Status:** In progress（D1–D10 已确认；S1–S5 已完成 2026-11-23）
- **Date:** 2026-11-22
- **Scope source:** [`PRODUCT-BRIEF.md`](../../PRODUCT-BRIEF.md) §2 Q2/Q7、§3、[`docs/eval/retrieval-baseline.md`](../eval/retrieval-baseline.md)、[`docs/plan/p4-plan.md`](./p4-plan.md)
- **前置:** P4 已完成（2026-11-22），见 [`p4-plan.md`](./p4-plan.md)、[`p4-s6-final.md`](../tdd/p4-s6-final.md)

## 1. P5 目标

P5 不再横向堆功能，而是把平台从“能演示”推进到“**质量可度量、能力可集成、成本可对账、长任务可靠**”。主题是三条主线加一条底座：

| 能力 | 完成标志 |
|---|---|
| 检索质量闭环 | 向量 + 词法混合检索（RRF 融合）+ 可选重排；检索调试接口/页可见各阶段分数；在 ≥100 题、含近似干扰的评测集上给出基线 vs 混合 vs 重排的对比数据 |
| 评测平台 | 数据集、题目、评测运行持久化；Recall@1/3/5、MRR、证据命中率、延迟 P50/P95；两次运行可对比，失败题目可定位 |
| 开放平台 SDK | 仓库内可 `pip install -e sdk/python` 的类型化客户端：登录/API Key、聊天 SSE、知识库上传、工作流/协作 SSE、用量查询；含错误、重试与流式解析 |
| Webhook | workspace 级事件订阅；HMAC 签名、退避重试、投递日志与重放；至少覆盖消息完成、文档就绪/失败、工作流/协作完成、预算超限 |
| 统一用量账本 | `usage_events` 覆盖聊天/工作流/协作；可按来源、API Key、run 对账；预算、`/metrics`、用量页口径一致 |
| 长任务可靠性 | 工作流/协作 run 由 Arq 后台执行，写入事件日志；SSE 可断线重连并回放；支持显式取消排队中/运行中的 run |
| 阶段验收 | 3 分钟 demo：上传近似文档 → 检索调试对比 vector/hybrid/rerank → 评测页跑分并对比 → SDK 流式调用 → Webhook 收到签名事件 → 用量按来源/Key 对账 → 断开工作流页面后重连并取消 |

P5 仍**不做真实支付/计费、复杂 RBAC、移动端与拖拽画布**。目标是把已有能力做深、做可验证，而不是扩大功能面。

## 2. 现状与差距

已完成（P4）：工作流 DAG、planner/worker/critic 协作、Prometheus 指标与预算告警、管理员 plan 管理与审计、可选 Prometheus/HTTPS profile、工作流 API 文档/示例/压测。

| 差距 | 现状 | 影响 |
|---|---|---|
| 检索只有向量 | `retrieve_chunks` 只做 L2 KNN；无词法、融合、重排 | 短问句、专有名词、数字类问题易被词面干扰；Top-1 已有失败样例 |
| 评测停留在脚本 | 20 文档 / 50 题，Recall@5 饱和；无持久化、无对比、无失败明细 | 无法回答“这次改动是否真的变好”，也无法在 UI 演示评测 |
| 无 SDK 包 | 只有 curl 示例与 `scripts/workflow_example.py` | 外部接入成本高，无法展示“开放平台”的工程完整度 |
| Webhook 仅预算 | 单个 `BUDGET_WEBHOOK_URL`，无签名/重试/日志 | 集成方无法可靠消费事件，失败不可见 |
| 账本不统一 | `usage_events.message_id NOT NULL`，只记聊天；run 成本留在 run 表 | 用量页、预算、指标三套口径；无法按 API Key 或来源对账 |
| 长任务绑连接 | `POST /workflows/{id}/runs` 同步 SSE；断开即取消 | 刷新页面/网络抖动会丢 run；无法取消；长任务占连接 |
| 无运行事件回放 | node/step 状态只存最终结果 | 断线后无法恢复时间线，排障只能看数据库 |

## 3. 关键决策（待确认）

| # | 决策 | 建议 | 备选 |
|---|---|---|---|
| D1 | P5 主线 | **RAG 质量 + 评测平台 + 开放平台（SDK/Webhook）+ 统一账本 + 异步运行**；不做计费/RBAC/移动端 | 只做 RAG（集成能力仍缺）；只做开放平台（质量不可度量） |
| D2 | 混合检索 | **pgvector 向量召回 + `pg_trgm` 词法召回 + RRF 融合**；Postgres 用 GIN 索引，SQLite 用字符 bigram 词法回退 | 引入 Elasticsearch/Qdrant（多一个组件）；jieba + tsvector（中文分词依赖与维护成本） |
| D3 | 重排 | **可插拔 `Reranker`**：OpenAI 兼容 `/rerank`（TEI / bge-reranker），默认关闭；未配置或失败时自动回退 RRF，不影响主链路 | 强制部署 bge-reranker（硬件/运维风险）；LLM listwise 重排（慢且贵） |
| D4 | 评测范围 | **检索指标 + 可选 LLM-as-judge**：文档级 Recall@1/3/5、MRR、证据命中率、延迟；另提供可选的答案生成 + LLM 评审（groundedness/relevance，1–5 分、是否忠实、理由），默认关闭以控制耗时与成本；数据集沿用现有 **50 题 / 20 文档**，不扩充 | 只评检索（无法展示答案质量）；RAGAS 全量（成本高）；强制每题都跑 answer+judge（本地模型太慢） |
| D5 | SDK 形态 | 仓库内 `sdk/python` 可安装包（`pyproject.toml` + `httpx`），同步与异步客户端、类型标注、SSE 迭代器、错误映射与重试；**不发布 PyPI** | 发布 PyPI（账号/版本负担）；只保留 curl 示例（无工程展示） |
| D6 | Webhook | workspace 级订阅；**HMAC-SHA256 + 时间戳**签名；最多 5 次指数退避；投递日志与重放；密钥加密存储、创建时展示一次；SSRF 校验（默认禁止私网，演示可配置放行） | 仅保留预算 webhook（不可靠）；不重试（集成方无法依赖） |
| D7 | 统一账本 | `usage_events` 增加 `source`、`api_key_id`、`workflow_node_run_id`、`collaboration_step_id`；`message_id` 改为可空；**每次 LLM 调用写一条事件**（费用发生在调用点），预算/指标/用量页统一聚合；历史行回填 `source='chat'` | 只按 run 写一条（丢失模型维度）；新表 union（预算与指标复杂） |
| D8 | 长任务执行 | **Arq 后台执行 + DB 事件日志 + SSE 回放**：`POST /runs` 返回 202 + `run_id`；`GET /runs/{id}/events` 从头回放并 tail；取消写 `cancel_requested_at`，在节点/步骤边界生效 | Redis pub/sub（多一个实时通道）；保持同步 SSE（P4 已知缺口） |
| D9 | 前端范围 | 新增 `/evaluation`、知识库“检索调试”页签、`/settings/webhooks`、用量来源/Key 维度、工作流断线重连与取消 | 拖拽画布、移动端、组织/RBAC（超出 P5） |
| D10 | 测试策略 | 全部使用确定性 provider、假 Reranker、假 webhook 接收器；pg_trgm 路径用可选 Postgres 集成测试，默认 SQLite 测试覆盖融合与回退逻辑；真实模型验证为 best-effort | 依赖真实模型/真实网络（硬件与网络不稳定导致红灯） |

> **已确认（2026-11-22）**：D1–D10 按建议执行。进入编码仍需逐片批准。
>
> **P5-S2 调整（2026-11-22，用户确认）**：数据集沿用 50 题 / 20 文档；增加可选 LLM-as-judge（答案质量评审）。

## 4. 切片与顺序

原则：先检索质量与评测，让改动有数据支撑；再做 SDK/Webhook 与统一账本；最后把长任务迁到后台队列并收口。每片可独立演示。

### P5-S1 检索质量与调试 — **已完成（2026-11-22）**（约 1.5–2 周）

- **迁移**：启用 `pg_trgm`；`chunks.text` 建 GIN trigram 索引；`knowledge_bases.retrieval_settings` JSON（`top_k`、`candidate_k`、`hybrid_enabled`、`rerank_enabled`），缺省继承 settings。
- **检索层重构**（`app/services/retrieval.py`）：拆出 `vector_search`、`lexical_search`、`fuse_rrf`、`rerank`；返回 `RetrievedChunk` 增加 `vector_rank` / `lexical_rank` / `fused_score` / `rerank_score` / `source`。
- **融合**：RRF `score = Σ 1/(60 + rank_i)`，向量与词法各取 `candidate_k`（默认 20），融合后取 `top_k`；去重以 `chunk_id` 为准。
- **重排**：`Reranker` 接口 + OpenAI 兼容 HTTP 实现；超时/非 2xx/格式错误回退融合结果并打点；最多重排 `candidate_k` 条。
- **调试 API**：`POST /knowledge-bases/{kb_id}/retrieval/search`（JWT-only，避免 API Key 反复触发 embedding/rerank 成本），支持 `query`、`top_k`、`hybrid_enabled`、`rerank_enabled` 覆盖；响应含各阶段排名、分数、耗时。
- **接入点**：RAG 聊天与 `kb_search` 工具统一走新检索层，按 KB 设置生效。
- **前端**：知识库详情新增“检索调试”页签：查询、开关、分数表、耗时。
- **测试**：RRF 计算、去重与排序、KB 设置覆盖、workspace 隔离、SQLite 词法回退、Reranker 失败回退、空查询。
- **文档**：ADR-0019；更新 [ADR-0003](../adr/0003-retrieval.md) 的现状说明。

> 验收：同一查询在 vector / hybrid / hybrid+rerank 三种模式下返回可解释的排名差异；调试页可见分数。
>
> **完成证据**：[`docs/tdd/p5-s1-retrieval.md`](../tdd/p5-s1-retrieval.md)、[`ADR-0019`](../adr/0019-hybrid-retrieval.md)。

### P5-S2 评测平台与 LLM-as-judge — **已完成（2026-11-22）**（约 1.5–2 周）

- **表**：
  - `eval_datasets(id, workspace_id, name, description, created_by, created_at, deleted_at)`
  - `eval_questions(id, dataset_id, question, relevant_document_ids JSON, evidence JSON, created_at)`
  - `eval_runs(id, dataset_id, kb_id, workspace_id, user_id, status, config JSON, metrics JSON, error_code, started_at, finished_at)`
  - `eval_run_items(id, run_id, question_id, hit_rank, reciprocal_rank, evidence_hit, latency_ms, top_document_ids JSON)`
- **执行**：Arq job 逐题检索；每 10 题更新进度；记录每题 top-k 文档与耗时；失败题保留错误码。
- **指标**：Recall@1/3/5、MRR、证据命中率（题目提供 `evidence` 时，检索 chunk 包含任一证据片段即命中）、延迟 P50/P95；配置快照写入 `eval_runs.config`，保证可复现。
- **LLM-as-judge（可选）**：运行时可开启答案生成 + 评审；评审输入为问题、检索到的参考段落、生成答案，输出 JSON `{score:1-5, faithful:bool, reason}`；聚合平均分、及格率（≥4）、忠实率。默认关闭；模型可单独指定 judge provider/model。
- **API**：数据集 CRUD 与 JSON 导入、题目列表、`POST /evaluations/runs`、`GET /evaluations/runs/{id}`、运行列表、`GET /evaluations/compare?ids=`。
- **前端 `/evaluation`**：数据集与题目管理（支持导入现有 `eval/dataset.json` bundle）、发起评测（top_k/hybrid/rerank/answer/judge）、进度、指标卡、失败题目表、两次运行对比。
- **数据集**：沿用现有 50 题 / 20 文档，不扩充；保留 `document_id_for` 确定性 ID；支持把 bundle 里的 filename 映射到所选 KB 的文档。
- **测试**：指标计算（含无命中/空集）、命中排名、证据命中、运行状态机、workspace 隔离、导入校验、对比接口、judge 解析与失败降级。
- **文档**：ADR-0020；更新 [`docs/eval/retrieval-baseline.md`](../eval/retrieval-baseline.md)。

> 验收：同一数据集跑 vector 与 hybrid 两次，页面显示 Recall@1/MRR 变化与失败题明细；开启 judge 后能看到每题评分/理由与聚合指标；报告中有可复现命令。
>
> **完成证据**：[`docs/tdd/p5-s2-evaluation.md`](../tdd/p5-s2-evaluation.md)、[`ADR-0020`](../adr/0020-evaluation-platform.md)。50 题实测：vector Recall@1=0.960 / MRR=0.9767，hybrid 相同，hybrid+rerank 0.980 / 0.9900；单题真机 judge 5/5、faithful=true。

### P5-S3 开放平台 SDK 与 Webhook — **已完成（2026-11-22）**（约 2 周）

- **SDK**（`sdk/python/`）：
  - `ai_power_sdk/client.py`：`AIPowerClient`（同步）与 `AsyncAIPowerClient`（异步），共享请求/流解析层。
  - 认证：邮箱密码登录 + 刷新；`api_key=` 模式；401 自动刷新一次。
  - 能力：`chat.stream()`、`knowledge_bases.upload()`、`retrieval.search()`、`workflows.run()`、`collaborations.run()`、`usage.summary()`、`models.list()`。
  - 错误：`AIPowerError(status, code, message, request_id)`；429 读取 `Retry-After`；GET 幂等重试。
  - 测试：`httpx.MockTransport` 覆盖 SSE 解析、错误映射、刷新与重试；示例脚本。
- **Webhook**：
  - 表：`webhooks(id, workspace_id, url, secret_encrypted, events, active, created_by, created_at, deleted_at)`、`webhook_deliveries(id, webhook_id, event, payload, status, attempts, response_status, error, next_attempt_at, created_at, delivered_at)`。
  - API：workspace owner 管理订阅（JWT-only）；创建时返回一次明文 secret；投递日志列表与重放。
  - 事件：`message.completed`、`document.ready`、`document.failed`、`workflow.completed`、`collaboration.completed`、`budget.exceeded`。
  - 签名：`X-AI-Power-Signature: t=<unix>,v1=<hex(hmac_sha256(secret, f"{t}.{body}"))>`；附带 `X-AI-Power-Event`、`X-AI-Power-Delivery`。
  - 投递：worker 每分钟扫描到期任务；1m/5m/30m/2h/6h 退避，5 次后 dead；超时 10s；不跟随重定向。
  - 安全：URL 仅 http/https；解析主机并拒绝 loopback/私网/链路本地（`WEBHOOK_ALLOW_PRIVATE_HOSTS` 可在局域网演示时放行）；secret 用 `WEBHOOK_SECRET_KEY` 派生密钥加密，dev 回退 JWT secret，非 dev 未配置则启动失败。
  - 兼容：`BUDGET_WEBHOOK_URL` 保留为 legacy，新订阅优先。
- **API Key scope**：新增 `workflow:run`，允许 API Key 触发工作流；Webhook 管理仍 JWT-only。
- **前端**：`/settings/webhooks` 订阅管理、事件勾选、secret 一次性展示、投递日志与重放。
- **文档**：ADR-0021、SDK README、Webhook 签名与验证示例。

> 验收：SDK 脚本完成“登录 → 上传 → 检索 → 工作流流式运行 → 用量查询”；本地接收器收到带正确签名的 webhook，并可看到重试/重放。
>
> **完成证据**：[`docs/tdd/p5-s3-sdk-webhooks.md`](../tdd/p5-s3-sdk-webhooks.md)、[`ADR-0021`](../adr/0021-sdk-webhooks.md)。SDK 已安装并通过真实 API 冒烟；Webhook 用 fake receiver 验证签名/重试，管理页已验证。

### P5-S4 统一用量账本 — **已完成（2026-11-22）**（约 1 周）

- **迁移**：
  - `usage_events.message_id` 改可空；新增 `source`（`chat|workflow|collaboration`，默认 `chat`）、`api_key_id`、`workflow_node_run_id`、`collaboration_step_id`。
  - `workflow_node_run_id` / `collaboration_step_id` 唯一（可空），保证重试幂等；补索引 `(workspace_id, source, created_at)`、`(workspace_id, api_key_id, created_at)`。
  - 历史行回填 `source='chat'`。
- **写入**：
  - 聊天 finalize 带 `auth.api_key_id`（若用 Key 调用）。
  - 工作流每个 LLM/agent 节点完成后写一条事件，价格快照在调用时取；失败/取消但已产生 token 的节点也写。
  - 协作每个 planner/worker/critic 步骤写一条事件。
- **查询**：`GET /usage/summary` 与 `/usage/cost` 支持 `group_by=source`、`api_key_id` 过滤；新增 `GET /usage/by-key`；预算天然汇总全部来源。
- **指标**：token/成本计数器增加 `source` 标签（保持低基数）。
- **前端**：用量页新增来源拆分与按 Key 表；成本图例支持 source。
- **测试**：幂等（重复 finalize 不重复写）、来源汇总、Key 归属、预算覆盖 run、迁移回填、跨 workspace 隔离。
- **文档**：ADR-0022；修订 ADR-0018 的“仅消息用量”限制。

> 验收：同一工作流 run 的成本同时出现在 run 详情、用量页、预算与 `/metrics`，金额一致。
>
> **完成证据**：[`docs/tdd/p5-s4-usage-ledger.md`](../tdd/p5-s4-usage-ledger.md)、[`ADR-0022`](../adr/0022-unified-usage-ledger.md)。361 收集 / 357 通过 / 4 跳过；前端 22 通过、构建通过。

### P5-S5 异步运行与取消 — **已完成（2026-11-23）**（约 1.5–2 周）

- **事件日志**：`workflow_run_events(run_id, seq, event, payload, created_at)`、`collaboration_run_events(run_id, seq, event, payload, created_at)`；`seq` 单调递增。
- **执行**：`POST /workflows/{id}/runs` 与 `POST /collaborations/runs` 创建 run（`queued`）并入 Arq；worker 执行 runner，逐个事件写日志；终态写 run 汇总与用量账本。
- **SSE 回放**：`GET /workflows/runs/{run_id}/events?after=seq`、协作同理；先回放已落库事件，再轮询 tail（300ms），终态关闭；支持 `Last-Event-ID`。
- **取消**：`POST /workflows/runs/{run_id}/cancel`、协作同理；queued 直接 `cancelled`；running 写 `cancel_requested_at`，runner 在节点/步骤边界检查并停；SSE 发送 `cancelled` 终态。
- **前端**：工作流/协作页改为“提交 → 跳转 run 详情 → 订阅事件”；刷新后自动重连；运行中显示取消按钮；列表展示 queued/running/completed/failed/cancelled。
- **兼容**：API 文档标注 breaking change（同步 SSE → 202 + 事件流）；SDK 的 `workflows.run()`、`scripts/workflow_example.py` 与 Playwright 同步更新。
- **测试**：入队与 worker 执行、事件顺序与回放、断线重连、取消 queued/running、重复取消幂等、workspace 隔离、run 超时。
- **文档**：ADR-0023；更新 [`docs/api/workflows.md`](../api/workflows.md)。

> 验收：提交 run 后关闭页面，重新打开仍能看到完整时间线；取消运行中的 run 在下一个节点边界停止且状态/用量正确。
>
> **完成证据**：[`docs/tdd/p5-s5-async-runs.md`](../tdd/p5-s5-async-runs.md)、[`ADR-0023`](../adr/0023-async-runs.md)。真实 API 验证 202/queued、事件 seq 回放、运行中取消终态 `cancelled`；Playwright 新增刷新重连用例。

### P5-S6 收口 — 待开始（约 0.5–1 周）

- 小体验项：批量上传（多选）、会话导出（Markdown/JSON）。
- 文档：README/CLAUDE、quickstart、errors、workflows、SDK、Webhook；ADR 索引。
- 测试：新增 ≥3 条 Playwright（评测页、Webhook 投递、异步 run 重连）；检索/评测压测脚本；覆盖率 ≥80%。
- 演示脚本：一条命令跑完“混合检索对比 → 评测 → SDK → Webhook”。
- 部署复核：compose 全栈、`/metrics`、预算告警、worker 新任务。

## 5. 排期（约 8–10 周）

| 顺序 | 切片 | 预估 |
|---|---|---|
| 1 | P5-S1 检索质量与调试 | 1.5–2 周 |
| 2 | P5-S2 评测平台与数据集 | 1.5–2 周 |
| 3 | P5-S3 SDK 与 Webhook | 2 周 |
| 4 | P5-S4 统一用量账本 | 1 周 |
| 5 | P5-S5 异步运行与取消 | 1.5–2 周 |
| 6 | P5-S6 收口 | 0.5–1 周 |

## 6. P5 明确不做

- 真实支付/计费/发票、充值退款。
- 复杂 RBAC、SSO、SCIM、组织层级。
- 发布 PyPI / npm 包、插件市场、任意代码节点。
- 移动端 App、拖拽式画布、实时多人协作。
- LLM-as-judge 的答案质量评测、微调/训练、自建推理引擎。
- 多区域部署、跨集群队列、Grafana/Alertmanager 全套运维。

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| 范围膨胀 | 每片独立验收；S1/S2 是硬主线，S3–S5 不得反向扩张；不做项写入 §6 |
| pg_trgm 对中文效果有限 | 用 ≥100 题含近似干扰的数据集实测；RRF 保留向量主路径；效果不佳时记录数据并改为字符 bigram 词法层，不改接口 |
| Reranker 服务不可用 | 默认关闭、可插拔、失败自动回退；测试用假实现；报告中注明真实服务条件 |
| 评测集标注成本 | 复用现有 50 题，新增题按模板批量构造；先保证文档级标签正确，证据短语可选 |
| Webhook 安全 | SSRF 校验、禁重定向、超时、签名、密钥加密；默认禁止私网，演示显式放行 |
| 异步执行改变 API | 明确 breaking change，同步更新 SDK/示例/E2E/文档；事件日志可回放，便于排障 |
| 事件日志膨胀 | 仅存节点/步骤级事件与截断 payload；按 run 终态后可配置 TTL 清理 |
| 成本口径改动影响历史 | 迁移回填 `source='chat'`；新增列可空；对账测试覆盖历史与新增 |

## 8. P5 完成定义（DoD）

1. 混合检索与可选重排可在聊天、`kb_search`、调试接口中生效；调试页可见向量/词法/融合/重排分数。
2. ≥100 题评测集上给出 vector vs hybrid vs hybrid+rerank 的 Recall@1/3/5、MRR、证据命中率与延迟对比，并有可复现命令/报告。
3. 评测数据集与运行持久化，UI 可发起、查看失败题、对比两次运行。
4. SDK 可安装并通过测试/示例完成流式聊天、上传、检索、工作流、用量查询。
5. Webhook 支持 ≥5 类事件，签名可验证、失败重试、投递日志与重放可用；SSRF 防护有测试。
6. `usage_events` 覆盖三类来源；用量页、预算、`/metrics` 对同一 run 的金额一致；可按 API Key 查询。
7. 工作流/协作 run 后台执行，SSE 断线重连回放，显式取消可用；状态机与隔离测试通过。
8. 后端测试通过、覆盖率 ≥80%、ruff 干净；前端单测/类型/构建通过；≥3 条新增 Playwright。
9. 文档：ADR-0019–0023、P5 TDD 证据、README/CLAUDE/quickstart/SDK/Webhook 更新。
10. CI 绿灯；compose 全栈重新部署并验证健康检查、指标、预算与 worker 新任务。

## 9. 门禁

- 本计划需用户确认 D1–D10 后才进入编码。
- 与 P1–P4 相同：**每片编码前需用户明确批准**；每片完成产出 TDD 证据并合回 `main`。
- 未列入本计划的 P6 功能不得提前实现。