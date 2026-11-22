# AI Power

一个可演示的 AI 应用平台：多模型对话、知识库检索增强（RAG）、引用回溯、用量统计与 API Key。

- 后端：FastAPI + async SQLAlchemy + PostgreSQL/pgvector + Redis + Arq
- 前端：React 18 + TypeScript + Vite + TanStack Query + Tailwind
- 模型：OpenAI 兼容 provider（本地 vLLM / llama.cpp、DeepSeek）

## 功能

| 能力 | 说明 |
|---|---|
| 认证 | 注册/登录、30 分钟 access + 7 天 refresh（一次性轮换、可吊销）、登录限流 |
| 对话 | SSE 流式输出、停止生成、历史回放、模型/token 元信息 |
| 知识库 | PDF/MD/TXT 上传、持久化入库队列、失败重试、状态轮询、删除清理 |
| 知识库管理 | 每库分块/检索参数、分块浏览与统计、重新分块、检索调试页 |
| RAG | bge-m3 + pgvector + pg_trgm 混合检索（RRF），可选 bge-reranker 重排；回答只引用真正进入 prompt 的 chunk |
| 评测 | 20 文档 / 50 题数据集、Recall@1/3/5 + MRR + 延迟、运行对比、可选答案生成 + LLM-as-judge |
| 开放平台 | `sdk/python` 同步/异步客户端（SSE、上传、检索、工作流）；Webhook 订阅 + HMAC 签名 + 重试/投递日志 |
| 用量 | 聊天/工作流/协作统一账本；按日/Provider/模型/来源聚合 token、请求数与成本（价格快照），支持按 API Key 对账 |
| API Key | `X-API-Key`，`chat:write` / `kb:read` / `workflow:run` scope，一次性展示、可吊销、过期与限流 |
| 多租户 | Workspace/成员、`X-Workspace-Id`、跨租户 404 |
| 模型平台 | 模型目录/广场对比、`auto` 路由与首 token 前降级、熔断 |
| Agent | supervisor + `retrieval`/`math` 子 Agent、`kb_search` / `calculator`、JSON 工具协议、SSE 工具事件、trace 记录 |
| Prompt 模板 | workspace 级模板与不可变版本、`{{变量}}` 渲染、会话 Prompt 快照 |
| 界面 | 中英文切换、明暗主题（跟随系统/本地记忆） |
| 配额 | workspace 请求/token 与 Key 限流，429 + 配额响应头 |
| 可观测 | `traces` 记录检索/TTFT/总耗时/尝试次数，7 天保留；`/metrics` 输出 HTTP/SSE/token/成本/队列/熔断指标 |
| 预算 | workspace 每日成本阈值，超限写审计并可选 webhook |
| 工作流 | 版本化 DAG、LLM/检索/工具/Agent/条件/并行节点、SSE 时间线与前端管理页 |
| 多 Agent 协作 | planner 拆解 → worker 并行 → critic 复核（≤2 轮），全局步数预算与协作时间线 |
| 管理后台 | 用户/Workspace/全局用量、启停模型、切换 plan、run 失败率，操作写审计日志 |
| 运维 | `/healthz`、`/readyz`、请求 ID、结构化日志、每日备份、压测脚本 |

## 快速开始（本地开发）

要求：Python 3.13、Node 22、Docker（用于 Postgres/Redis）。

```bash
cp .env.example .env          # 填写 POSTGRES_PASSWORD、模型地址等
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"

docker compose up -d postgres redis
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
.venv/Scripts/python.exe -m arq app.worker.WorkerSettings   # 另开一个终端

cd web && npm install && npm run dev                         # http://localhost:5173
```

Windows 上 Docker 运行在 WSL：数据库/Redis 请用 `192.168.29.100`，不要用 `localhost`。

前端开发服务器把 `/api` 代理到 `VITE_PROXY_TARGET`（默认 `http://192.168.29.100:8002`）。

## 部署（本地虚拟机 Docker）

```bash
cp .env.example .env
# 必改：POSTGRES_PASSWORD、JWT_SECRET；按需改模型与 embedding 地址
docker compose up -d --build
```

| 服务 | 地址 | 说明 |
|---|---|---|
| Web | `http://192.168.29.100:8080` | nginx 静态前端 + `/api` 反代 |
| API | `http://192.168.29.100:8002` | 直接访问后端（容器 8000） |
| Postgres | `192.168.29.100:5432` | pgvector/pg16 |
| Redis | `192.168.29.100:6379` | 队列 + 限流 |

- API 启动时自动执行 `alembic upgrade head`。
- `web` 使用 nginx，SSE 已关闭代理缓冲。
- `backup` 服务每天 `pg_dump -Fc` 到 `backups` 卷，保留 7 天。
- 默认局域网 HTTP；可选 HTTPS：设置 `CADDY_DOMAIN` 后 `docker compose --profile https up -d caddy`。
- 检索默认启用混合检索与重排，`RERANK_BASE_URL` 默认指向 `http://192.168.29.100:8001/v1`；没有 reranker 时在 `.env` 设 `RERANK_ENABLED=false`。
- CORS 白名单由 `CORS_ORIGINS` 控制。
- 首次部署后运行 `scripts/seed_models.py` 填充模型目录（见 CLAUDE.md 命令）。

## 测试

```bash
.venv/Scripts/python.exe -m pytest --cov=app
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
cd web && npm test && npm run build
cd web && npx playwright install chromium && npm run test:e2e
```

## 运维

```bash
docker compose logs -f api worker web

# 指标（Prometheus 文本）与可选 Prometheus（9090）
curl -s http://192.168.29.100:8002/metrics | head
docker compose --profile observability up -d prometheus

# 可选 HTTPS（需先设置 CADDY_DOMAIN）
docker compose --profile https up -d caddy
docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/readyz').status)"

# 立即备份一次
docker compose exec -e RUN_ONCE=1 backup /bin/sh /usr/local/bin/backup_postgres.sh

# 恢复（示例）
docker compose exec -T postgres pg_restore -U ai_power -d ai_power --clean < backup.dump

# 20 并发流式压测（TTFT / 总耗时 P50/P95）
.venv/Scripts/python.exe scripts/loadtest.py --base-url http://192.168.29.100:8002 --concurrency 20

# 工作流并发压测
.venv/Scripts/python.exe scripts/loadtest_workflow.py --base-url http://192.168.29.100:8002 \
  --provider local-qwen --model <model> --concurrency 3

# 准备 20 文档 / 50 题评测集（需要 AI_POWER_EMAIL / AI_POWER_PASSWORD）
AI_POWER_BASE_URL=http://192.168.29.100:8002 \
  .venv/Scripts/python.exe scripts/seed_eval_platform.py --kb-name "检索评测集"

# Python SDK（仓库内安装，不发布 PyPI）
uv pip install --python .venv/Scripts/python.exe -e sdk/python
```

日志默认文本格式；compose 中 API/worker 使用 `LOG_FORMAT=json`，每行包含
`request_id, method, path, status, duration_ms, user_id`。

## 目录

```
app/            FastAPI 应用（routers / services / providers）
alembic/        数据库迁移
tests/          后端测试
web/            React 前端（含 Dockerfile 与 nginx.conf）
eval/           50 题中文检索评测集
scripts/        种子数据、评测、备份、压测
sdk/python/     Python SDK（同步/异步）
docs/           产品契约、ADR、TDD 证据与规划
```

## 文档

- [PRODUCT-BRIEF.md](./PRODUCT-BRIEF.md)
- [docs/product/CAPABILITY.md](./docs/product/CAPABILITY.md)
- [docs/plan/p3-plan.md](./docs/plan/p3-plan.md)
- [docs/plan/p4-plan.md](./docs/plan/p4-plan.md)
- [docs/plan/p5-plan.md](./docs/plan/p5-plan.md)
- [docs/tdd/p5-s1-retrieval.md](./docs/tdd/p5-s1-retrieval.md)
- [docs/tdd/p5-s2-evaluation.md](./docs/tdd/p5-s2-evaluation.md)
- [docs/tdd/p5-s3-sdk-webhooks.md](./docs/tdd/p5-s3-sdk-webhooks.md)
- [docs/adr/0019-hybrid-retrieval.md](./docs/adr/0019-hybrid-retrieval.md)
- [docs/adr/0020-evaluation-platform.md](./docs/adr/0020-evaluation-platform.md)
- [docs/adr/0021-sdk-webhooks.md](./docs/adr/0021-sdk-webhooks.md)
- [docs/api/webhooks.md](./docs/api/webhooks.md)
- [sdk/python/README.md](./sdk/python/README.md)
- [docs/api/quickstart.md](./docs/api/quickstart.md)
- [docs/api/errors.md](./docs/api/errors.md)
- [docs/api/workflows.md](./docs/api/workflows.md)
- [docs/adr/](./docs/adr/)
- [docs/tdd/](./docs/tdd/)

## 安全说明

- `.env` 不入库；不记录 `Authorization`、API Key、完整文档内容。
- API Key 只存 SHA-256 与 prefix，明文仅创建时展示一次。
- 跨用户资源统一返回 404。