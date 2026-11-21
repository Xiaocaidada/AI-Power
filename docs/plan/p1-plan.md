# P1 规划：从“可演示闭环”到“可公开使用”

- **Status:** Confirmed（关键决策已锁定，2026-11-21）
- **Date:** 2026-11-21
- **Scope source:** [`PRODUCT-BRIEF.md`](../../PRODUCT-BRIEF.md) §3 P1、[`docs/product/CAPABILITY.md`](../product/CAPABILITY.md) §4/§5/§6
- **No code:** 本文只做规划；任何实现需先确认范围与顺序。

## 1. P1 目标（来自 brief）

| 能力 | 完成标志 |
|---|---|
| 会话历史 | 刷新/重登后能看到历史消息与引用 |
| 文件管理 | 上传、状态、失败重试、删除清理 |
| API Key | 创建/吊销，可用 Key 调用对话接口 |
| 用量统计 | 按时间/provider/model 查看 token 用量 |
| Docker 部署 | `docker compose up -d` 在 VM 上启动全部服务 |
| 基础评测脚本 | **已完成**（S4：50 题 Recall@k，见 `docs/eval/retrieval-baseline.md`） |
| 阶段验收 | **局域网可访问**（`192.168.29.100`）+ 3 分钟 demo + CI 绿灯 |

P1 不追求“平台化”：模型广场、路由降级、配额计费、多租户、Agent 全部留给 P2/P3。

## 2. 现状盘点

已具备（P0）：

- JWT 认证、按用户隔离（跨用户 404）、知识库/会话/文档 CRUD。
- OpenAI 兼容 provider 抽象 + SSE（`meta/citation/delta/usage/done/error`）。
- 文档上传 → 解析 → 分块 → bge-m3 → pgvector；幂等、失败码、软删。
- 检索 + 引用 + RAG 回答；HNSW；Recall@5 基线 1.000 / Recall@1 0.960。
- 139 个后端测试，96% 覆盖率；ruff 全绿。

P1 必须补的现有缺口：

| 缺口 | 现状 | 影响 |
|---|---|---|
| 无迁移工具 | `init_db()` 建表 | P1 要加表/列，必须先上 Alembic |
| 入库任务不持久 | `BackgroundTasks` | 重启丢任务；失败无法重试 |
| 原始文件不清理 | 软删后文件残留 | 磁盘泄漏 |
| 用量只有 messages 字段 | 无聚合 API | 控制台无数据 |
| 无 API Key | 仅 JWT | 无法程序化调用 |
| 无前端 | 仅 API | 无法公网演示 |
| 无容器化 API/worker | 仅 compose 依赖 | 无法一键部署 |
| 无 CI | 本地跑测试 | 无法保证绿灯 |

## 3. 需要先锁定的决策

| # | 决策 | 建议 | 备选 |
|---|---|---|---|
| D1 | 队列 | **已确认：Arq**（async 原生，复用现有 Redis） | Celery（生态大但同步阻塞模型更重） |
| D2 | 部署位置（Q3） | **已确认：本地 VM Docker Compose（`192.168.29.100`），局域网 IP + 端口访问；暂不做公网/HTTPS** | 公网 + Caddy/隧道（后续需要时再加） |
| D3 | 用量存储 | **新增 `usage_events` 只追加表**，消息完成时写入 | 直接聚合 `messages`（简单但无法承载未来 API Key 用量） |
| D4 | 引用持久化 | **新增 `message_citations` 表**，与助手消息一起写入 | `messages.citations` JSON 列（简单但难查询） |
| D5 | API Key 认证头 | **`X-API-Key`**，与 JWT 的 `Authorization` 区分 | 复用 `Authorization: Bearer` |
| D6 | Key 存储 | 展示一次 `ap_<prefix>_<secret>`；存 `sha256(secret)` + `prefix` | argon2（更慢，Key 已是高熵随机串） |
| D7 | refresh token | **已确认：P1 做**。access 30 分钟 + refresh 7 天；refresh 一次性轮换、可吊销、拒重复使用 | 继续 24h JWT（不满足需求） |
| D8 | 登录限流 | **P1 做**（Redis 固定窗口，10 次/分钟/IP） | 留到 P2（公网暴露风险） |
| D9 | token_count | **可选**：用 `tiktoken` 近似并标注“近似”，或继续 NULL | 引入 Qwen tokenizer（依赖重） |
| D10 | 前端范围 | 登录、对话、知识库、API Key、用量；不做广场/管理后台 | 只做对话（演示不足） |

> 已确认 D1/D2/D7 与前端范围（D10）；D3/D4/D5/D6/D8/D9 按建议执行，如需调整在对应切片开工前说明。

## 4. 切片与顺序

原则：先补基础设施，再做新功能，最后前端与部署；每片独立可演示、可停止。

### P1-S1 基础设施：Alembic + CI + 容器化 API — **已完成（2026-11-21）**

**为什么先做**：P1 新增 `api_keys`、`usage_events`、`message_citations` 与 `ingestion_jobs` 字段，没有迁移会不断手改 schema。

范围：

- Alembic 接入：初始迁移对应当前 schema；`init_db()` 退化为测试/迁移后的校验。
- 认证升级（**refresh token**）：access token TTL 30 分钟；新增 `refresh_tokens` 表（`token_hash`、`expires_at`、`revoked_at`、`replaced_by`）；`POST /auth/refresh` 一次性轮换、`POST /auth/logout` 吊销；重复使用旧 refresh token 直接拒绝。
- 生产 Dockerfile（多阶段）+ compose 增加 `api` 服务；保留 `postgres`/`redis`。
- GitHub Actions：ruff check/format、pytest、覆盖率阈值、docker build。
- `.env.example` 增加部署项（CORS origin、API 端口、日志级别）。
- 登录限流（Redis，10 次/分钟/IP）与 `/readyz` 检查 DB + Redis。

验收：

- 空库执行 `alembic upgrade head` 得到与当前一致的表。
- refresh 轮换：旧 token 二次使用被拒绝；logout 后 refresh 失败；access 过期后可用 refresh 换新。
- CI 在 PR 上绿；覆盖率 ≥ 80%（当前 96%，不得回退）。
- `docker compose up -d api` 可启动并通过 `/healthz`、`/readyz`。

### P1-S2 持久化入库队列 + 文件生命周期 — **已完成（2026-11-21）**

范围：

- Arq worker（compose 增加 `worker`），替换 `BackgroundTasks`。
- `ingestion_jobs` 增加 `started_at`、`finished_at`、`lease_expires_at`、`attempts` 语义；`queued → running → succeeded | failed | dead`。
- 重试：最多 3 次，指数退避；失败后 `dead`；启动时回收租约过期的 `running` 任务。
- `POST /documents/{id}/retry`（仅所有者、仅 `failed`）。
- 删除文档：同步删除 chunks/embeddings + 磁盘文件；启动时清理 24h 以上的孤儿文件。
- token_count（若采用 D9）：入库时计算。

验收：

- 进程重启后未完成任务被重新执行（测试模拟租约过期）。
- 失败文档可重试成功；超过上限进入 `dead` 且不再自动重试。
- 删除后磁盘文件不存在；孤儿清理可测试。

### P1-S3 用量事件 + 引用持久化 — **已完成（2026-11-21）**

范围：

- `usage_events`：`id, user_id, conversation_id, message_id UNIQUE, provider_id, model, prompt_tokens, completion_tokens, created_at`；只插入，不更新（I7）。
- 助手消息 finalize 时与 usage 同事务写入；usage 缺失也记录事件（token 为 NULL），用于请求计数。
- 迁移回填历史 `messages`（有 token 的记录）。
- `GET /usage/summary?from&to&group_by=day|provider|model`：只返回本人数据；含请求数、prompt/completion/total tokens。
- `message_citations` 表：`message_id, index, document_id, chunk_id, page_no, snippet`；与助手消息一起写入；`GET /conversations/{id}` 返回引用。

验收：

- 两用户用量互不可见；聚合与逐条求和一致。
- 重放会话历史能看到当时的引用（不重新检索）。
- 迁移回填幂等（重复执行不重复插入）。

### P1-S4 API Key — **已完成（2026-11-21）**

范围：

- `api_keys`：`id, user_id, name, prefix, key_hash, scopes, created_at, last_used_at, revoked_at`。
- 生成 `ap_<8位prefix>_<32字节随机>`；响应仅此一次返回完整 Key。
- `POST /api-keys`、`GET /api-keys`（只返回 prefix/元数据）、`DELETE /api-keys/{id}`（吊销）。
- 认证依赖：`X-API-Key` → 查 prefix → 校验 SHA-256 → 用户；更新 `last_used_at`（节流写入）。
- 对话接口接受 Key 认证；scope 最小集：`chat:write`、`kb:read`。
- 日志与错误信息永不输出完整 Key。

验收：

- 错误/吊销/过期 Key 返回 401；Key 只能访问本人资源。
- `last_used_at` 更新；Key 明文不落库、不落日志。
- 吊销后立即失效。

### P1-S5 前端（React + TS）

> **门禁：前端开工前必须再次征求用户确认；未确认前不写前端代码。**
>
> 详细 UI 规划见 [`p1-s5-frontend-ui.md`](./p1-s5-frontend-ui.md)（视觉令牌、页面规格、SSE 客户端、i18n、测试与切片）。已确认视觉方向为 **Soft 产品化**，界面支持中/英双语。
>
> 编码前的 **S5-pre** 后端前置片已 **完成（2026-11-21）**：CORS 中间件与 `GET /knowledge-bases/{kb_id}/documents`，证据见 [`docs/tdd/p1-s5-pre-frontend-contract.md`](../tdd/p1-s5-pre-frontend-contract.md)。
>
> **S5a 已完成（2026-11-21）**：`web/` 脚手架、设计令牌、中英双语、登录/静默刷新、对话 SSE/引用/历史/取消；证据见 [`docs/tdd/p1-s5a-frontend.md`](../tdd/p1-s5a-frontend.md)。
>
> **S5b 已完成（2026-11-21）**：知识库列表/详情、上传进度、状态轮询、失败原因、重试与删除；证据见 [`docs/tdd/p1-s5b-knowledge.md`](../tdd/p1-s5b-knowledge.md)。
>
> **S5c 已完成（2026-11-21）**：用量图表、API Key 一次性展示与吊销、个人资料与中英切换；证据见 [`docs/tdd/p1-s5c-console.md`](../tdd/p1-s5c-console.md)。前端 S5 全部完成，下一步 S6 部署。

分三个可独立演示的子片：

- **S5a 登录 + 对话**：登录/注册；会话列表；发送消息；解析 SSE（fetch + ReadableStream，非 EventSource）；`citation` 侧栏；`usage` 展示；断开取消。
- **S5b 知识库**：创建/列出/删除 KB；上传（进度、大小限制提示）；文档状态轮询；失败原因；重试；删除。
- **S5c 控制台**：API Key 管理（创建一次展示、吊销）；用量图表（按日/provider/model）；个人资料。

技术约束：

- Vite + React 18 + TS + TanStack Query + Tailwind + shadcn/ui。
- 前端只消费既有 API，不为 UI 快捷方式破坏后端契约。
- SSE 解析需覆盖 `meta/citation/delta/usage/done/error` 与断线重连提示。

验收：

- 无刷新完成：注册 → 上传 → 提问 → 看到引用 → 查看用量 → 创建 Key。
- 前端 `npm run build` 通过；关键组件有 Vitest 测试；至少 1 条 Playwright 冒烟（登录 + 发消息）。

### P1-S6 部署与可观测

范围：

- compose 全栈：`postgres`、`redis`、`api`、`worker`、`web`（nginx 提供静态前端）。
- **局域网访问**：`http://192.168.29.100:8080`（web）与 `:8002`（api）；Docker 端口映射到 VM（8000/8001 已被 vLLM 占用）。
- 不做公网、不做 HTTPS（后续需要时再加 Caddy/隧道）。
- CORS 仅允许 `http://192.168.29.100:8080`；安全响应头。
- 结构化日志落地文件/容器日志；记录 `request_id, user_id, provider, model, latency_ms, ttft_ms, error_code`。
- 备份：`pg_dump` 每日 cron，保留 7 天。
- README quickstart：本地开发与 VM Compose 两套命令。

验收：

- VM 上 `docker compose up -d` 后局域网 `http://192.168.29.100:8080` 可访问。
- 20 并发对话无错误（脚本压测）；TTFT P95 记录（本地 Qwen 与 DeepSeek 分开）。
- 重启后数据与任务状态正确恢复。

## 5. 建议排期（按全职 3 周）

| 顺序 | 切片 | 预估 |
|---|---|---|
| 1 | P1-S1 基础设施 | 2–3 天 |
| 2 | P1-S2 队列与文件 | 3–4 天 |
| 3 | P1-S3 用量与引用 | 2–3 天 |
| 4 | P1-S4 API Key | 2 天 |
| 5 | P1-S5 前端（a/b/c） | 5–7 天 |
| 6 | P1-S6 部署与压测 | 2–3 天 |

前端可与 S3/S4 并行，但必须在 S1 的 API 契约稳定后开始。

## 6. P1 明确不做

- 模型广场、模型对比、路由/自动降级（P2）。
- 配额、计费、真实支付（P2/P3）。
- 多租户/组织/团队、复杂 RBAC（P2）。
- Agent、工具调用、工作流、Prompt 模板（P3）。
- 管理后台 UI、trace 平台、Prometheus/Grafana（P2/P3）。
- OCR/docx/html、移动端、多语言。

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| 前端吃掉大部分时间 | 只做 5 个页面；组件库优先；先跑通 SSE 与引用 |
| 公网暴露安全问题 | HTTPS、登录限流、CORS 白名单、Key 哈希、错误信息脱敏 |
| 队列引入后测试变慢 | 服务层测试直接调用任务函数；集成测试用真实 Redis（CI service） |
| 迁移破坏现有数据 | 初始迁移对齐当前 schema；回填脚本幂等；部署前 `pg_dump` |
| WSL/VM 网络问题 | 沿用 `192.168.29.100`；compose 网络内用服务名；文档记录 |
| 范围膨胀 | 每片完成即打 tag/演示；未列入本计划的 P2 功能不提前做 |

## 8. P1 完成定义（DoD）

1. 局域网 URL（`http://192.168.29.100:8080`）可访问；`docker compose up -d` 可重建环境。
2. 3 分钟 demo：注册 → 上传 → 带引用提问 → 历史回放引用 → 用量 → API Key → 用 Key 调用。
3. CI 绿灯；后端覆盖率 ≥ 80%；RAG 评测基线不下降。
4. 产出：`ADR-0005`（队列）、`ADR-0006`（用量/引用）、`ADR-0007`（API Key）、`ADR-0008`（部署）；`ADR-0004` 已用于会话认证；P1 TDD 证据；README quickstart。
5. 安全检查：仓库无密钥、Key 明文不落库/日志、登录限流生效、CORS 收紧。

## 9. 已确认事项（2026-11-21）

1. **部署**：本地虚拟机 Docker（`192.168.29.100`），局域网 IP + 端口访问，暂不做公网/HTTPS。
2. **队列**：接受 Arq。
3. **refresh token**：P1 实现（access 30 分钟 + refresh 7 天，轮换/吊销）。
4. **前端**：P1 全做（S5a/S5b/S5c）；**开工前必须再次征求用户确认**。
5. **访问方式**：本机 IP + 端口，不需要域名。

**门禁**：任何编码开始前需用户明确批准；S5 前端另设二次确认。