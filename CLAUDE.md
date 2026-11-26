# CLAUDE.md

本文件说明 Claude Code 在本仓库中开发时需要了解的项目状态、文档入口、常用命令、架构与既有约束。以下内容仅整理原文，不新增项目要求。

## 1. 项目状态

项目名称：**AI Power**。P0–P12 的主要功能已按阶段完成；各阶段的设计、测试证据和已知边界见下方文档索引。这里按能力归纳，避免重复罗列每个切片。检索评测的 50 题结果：Vector Recall@1 = 0.960、MRR = 0.9767；Hybrid + Rerank Recall@1 = 0.980、MRR = 0.9900。P1 局域网部署的 20 并发测试为 20/20 成功，本地 Qwen 的 TTFT P95 为 46.9s。

### P0–P5：核心平台与工程化

- **P0 基础能力**：认证与用户数据隔离；Provider 抽象和 SSE 对话；PDF/MD/TXT 上传、异步解析分块、bge-m3 向量化及 pgvector 存储；HNSW 检索、RAG 引用和引用 SSE；20 文档/50 中文问题评测集及真实 bge-m3 Recall@5 基线。
- **P1 工程化与基础产品闭环**：Alembic 迁移、Refresh Token 轮换/吊销、登录限流、健康检查、Docker/CI；Arq 持久化入库队列、租约/重试/死信、文档重试和文件清理；追加式用量账本、历史引用回放；API Key 及 scope；完整前端、局域网 Docker 部署、nginx、结构化日志、每日备份和 20 并发测试。P1 已完成。
- **P2 多租户与平台管理**：Workspace、模型目录、自动路由/故障降级、Workspace/Key 配额、Trace、平台前端、游标分页、SQL 用量聚合和 Playwright CI 冒烟。P2 已完成。
- **P3 Agent 与管理能力**：Supervisor/检索/数学 Agent、多 Agent 工具协议和 SSE/Trace；`kb_search`、AST 白名单计算器；Prompt 模板及不可变版本；价格快照和成本面板；平台管理员、模型启停和审计；OpenAPI、API 文档、分页、429 倒计时、暗色模式等收尾。P3 已完成。
- **P4 工作流与可观测性**：版本化 DAG 工作流，支持 LLM、检索、工具、Agent、条件、并行、Join；Planner–Worker–Critic 协作；Prometheus 指标、Workspace 每日成本预算和告警；套餐管理、运行失败率、发布审计；可选 Prometheus/HTTPS 部署配置及工作流文档、压测和 E2E。P4 已完成。
- **P5 检索、评测与异步运行**：按 KB 配置分块/检索；pg_trgm + pgvector 混合检索、RRF、可选 bge-reranker；检索调试界面；评测数据集、Arq 评测任务、Recall/Precision/MRR/NDCG/延迟、运行对比及可选答案生成/LLM Judge；Python 同步/异步 SDK、签名 Webhook；统一 chat/workflow/collaboration 用量账本；异步工作流/协作运行、事件持久化回放、重连和取消；批量上传队列、会话 Markdown/JSON 导出。P5 功能完成，重型 S6 测试/演示/覆盖率工作按要求跳过。

### P6–P8：Provider、门户、创作工具与 Agent Studio

- **P6 Provider Hub 与产品门户**：用户/Workspace Provider 配置（密钥 Fernet 加密、脱敏、测试/同步模型、能力标签、只读共享），动态 Provider Registry；公共模型目录和个人模型广场，模型能力校验、模型体验页及 KB Embedding/Reranker 选择；门户首页、公告、运营位、通知和管理员内容管理；Projects、项目指令快照、会话搜索/置顶/归档/移动/批量操作、模型切换、生成参数、重新生成、消息反馈；自定义 Agent、插件定义/配置/调用及敏感操作确认；个人 Dashboard、Prompt Library、跨 KB 文件中心和 Workspace 全局搜索。
- **P6 Chat UI 与补充闭环**：Chat 使用独立 ChatLayout 和会话侧栏；新建对话采用输入优先布局，提供模型/项目/Agent/KB 选择；消息标题编辑、消息操作、时间、运行详情折叠和智能滚动；补充消息编辑/回复、会话永久及批量删除、聊天附件、多 KB 会话、KB 重命名/描述、文档标签/搜索、近期用量、模型/插件全局搜索和公开 Help。内置模型目录来自智谱、阿里云、OpenAI、DeepSeek 四组 JSON，共 229 个支持 Chat 的模型；提供商摘要、模型分页/筛选、每家模型首页轮播，以及用户填写 Base URL 和 Key 后激活模型的流程。P6 功能完成。
- **P7 创作与模型评测工作台**：Model Arena（2–4 模型并行、独立 SSE/停止/重试、盲测揭晓、投票、反馈和历史）；Prompt Lab（平台/私有模板、变量、不可变版本、行级 diff、多模型实验、效果评分和快照）；Model Evaluation Center（数据集、并发批测、取消/重试、规则/人工/AI Judge、质量与性能指标）。三者共用 ModelStream/ModelCompletion 和 usage_events 来源归因。P7 已完成。
- **P8 Agent Studio MVP**：Agent 应用实体及 autonomous/workflow/hybrid 模式；全屏配置、React Flow 画布、AI Workflow Builder、测试运行；Workflow 节点清单、起止/输出节点、节点级 KB 与 Agent 绑定；公开 Agent 市场、复制/收藏/发布快照；多轮 Builder 会话、差异预览和确认后应用；Agent 体验页、统一运行历史、模板、评分/举报与管理员审核；人工 Review、循环、HTTP、MCP、长期记忆、受限代码表达式和只读数据库节点；MCP resources/prompts、记忆向量召回、Review 崩溃恢复。P8 v1 MVP 完成，完整 Agent 需求仍见 P11 缺口清单。

### P9–P11：知识工程、个人记忆与能力补齐

- **P9 Knowledge Studio MVP**：工作流类型区分 Agent、知识处理和知识检索；知识处理画布支持解析/清洗/分块/Embedding/暂存索引，节点预览、SSE 运行和原子应用；上传/重处理自动执行 KB 绑定的处理流程；知识检索画布支持 Query 改写、向量/词法/混合召回、重排、Top-K、上下文等节点，检索失败回退内置流程；知识 Builder 多轮生成、修复、资源校验和差异应用；检索评测增加 Precision、文档 Recall、NDCG、节点耗时分析及优化建议应用/回滚；支持 URL/HTML/站点导入、文件夹/元数据、XLSX/PPTX/HTML 解析、可选视觉 OCR、元数据过滤、项目多 KB 关联和知识配额。P9 MVP 完成。
- **P10 Memory Hub MVP**：记忆支持用户/项目/Agent/全局等作用域、分类、状态、来源、标签、版本、敏感度、有效期、使用统计和关系；异步提取、去重、更新建议、候选审核及显式“记住”直存；统一记忆检索排序并注入 Chat/Agent/Workflow，记录使用来源和消息快照；项目/Agent 记忆权限矩阵；自动关系、图谱、质量分析、重复/冲突/过期/孤立等建议、应用/回滚、记忆评测和配额；夜间重建关系/生成建议及过期处理。P10 MVP 完成。
- **P11 剩余能力补齐**：画布撤销/重做、草稿自动保存、导入导出和版本恢复；单节点调试、从节点运行；Builder 澄清、取消和部分采纳；Agent 参数、工具/MCP 浏览测试、市场筛选/模板；知识父子块、语义分组、元数据增强、过滤/多查询/回退/运行分析；记忆生命周期、保留策略、版本 diff、来源授权、语义矛盾扫描、反馈和记忆 A/B 评测；Agent 分析、解析预览、附件开关、引用 Precision/Recall；检索意图分类/同义词扩展、OCR 节点、格式校验、独立索引模式；项目 Agent/文件关联、处理版本对比及更丰富记忆过滤。P11 既定切片完成，但各项局部边界见 `docs/plan/p11-gap-list.md` 和对应 TDD。

### P12：网页对话模式与外部能力

- **统一对话模式**：chat、web_search、deep_research、study、agent；会话/消息保存模式元数据，按模型能力展示模式和思考等级，支持 fast/standard/deep 到真实 `reasoning_effort` 的映射，不支持时明确报错而不静默降级。
- **网页搜索**：Tavily/Brave/Serper/SearXNG 配置，密钥加密、默认/共享/测试；多 Query 搜索、去重、阶段和来源 SSE、来源持久化回放；未配置时不发起外部请求。
- **长任务与研究**：通用 `chat_tasks` 状态机支持排队/运行/暂停/恢复/取消/检查点重试和事件回放；Deep Research 先生成并确认计划，再分阶段收集网页/知识来源、交叉验证并生成结构化报告，支持追问、分节重生成、保存到 KB/Project；Agent Task 支持确认计划、工具调用时间线、高风险操作审批、暂停/恢复/检查点重试和产物保存。
- **BYOK 集成**：图片生成/编辑/变体、视觉分析、STT/TTS 的 OpenAI 兼容代理；媒体资产存储及管理；Skills 使用内置工具白名单和逐次运行记录；GitHub 只读仓库/Issue 连接器。
- **UI 改版**：品牌 AI Power；门户导航调整、首页单轮内联对话、Provider 展示；控制台按概览/对话/知识/构建/扩展/账户分组；Arena/Prompt Lab/模型评测使用独立 ToolLayout；Chat 收拢模式、思考、搜索、Agent Task、知识/记忆/Skills/连接器/插件入口；暗色主题和尊重 reduced-motion 的动效。

### 已知未实现项与重要边界

- P8 Agent、P9 Knowledge、P10 Memory 的完整需求仍以 P11 缺口清单为准；P11 多项为部分完成，具体边界见阶段说明和 TDD。
- 当前 `auto` 路由只支持 standard，直到路由解析出具体模型；Agent 与 Web Search/Deep Research 仍互斥，真实 Agent 联网需要把 web search 注册为工具；Agent 审批入口仍指向 `/tasks`。
- Research 来源目前为 KB 级，不支持固定到单文档；网页研究使用单一 Provider，不绕过付费墙/登录；MCP 工具尚未做风险分类；审批策略记忆/成本上限仍属后续工作。
- 实时语音未实现（需要 WebRTC/临时令牌/音频代理）；Google Drive/Gmail/Calendar OAuth 未实现；非 OpenAI 兼容语音供应商未适配；媒体配额和自动内容审核未实现；GitHub 写操作刻意不开放。
- 知识处理仍受已有解析器限制；OCR 节点覆盖 PDF/图片，DOCX/PPTX 内嵌图像仍走解析器逻辑；索引模式按文档设置；多 KB 检索使用首个 KB 的 Embedding/Reranker 参数；处理版本比较不重新执行 Pipeline；项目文件工具只读取已索引分块。
- 记忆完整度和变化分析含启发式逻辑；关系过滤只支持一跳；保留策略仅标记过期、不硬删除且暂无通知；反馈不会自动归档记忆。
- Webhook、数据库、HTTP、MCP 等外部调用均有各自安全边界，具体见架构章节和 ADR/TDD；不要将上述“已完成”理解为超出本文描述的能力。

## 2. 文档索引

### 产品与规划

- `PRODUCT-BRIEF.md`：产品诊断、P0–P3 路线图、反目标和成功指标。
- `docs/product/CAPABILITY.md`：P0 能力契约（API、状态机、数据模型、安全约束、开放问题）。
- 规划：`docs/plan/p1-plan.md`、`p2-plan.md`、`p3-plan.md`、`p4-plan.md`、`p5-plan.md`、`p6-plan.md`、`p6-s4-plan.md`、`p6-s5-plan.md`、`p6-s6-plan.md`、`p6-chat-ui-plan.md`、`p6-b-plan.md`、`p7-plan.md`、`p8-plan.md`、`p9-plan.md`、`p10-plan.md`、`p11-gap-list.md`、`p11-s9-p2-assessment.md`、`p12-plan.md`，均位于 `docs/plan/`。
- 演示：`docs/demo/p6-walkthrough.md`。

### ADR

位于 `docs/adr/`：`0001-p0-stack.md`（技术栈/模型接入）、`0002-ingestion.md`（入库、pgvector、分块、幂等、失败码）、`0003-retrieval.md`（检索、引用真实性、注入防护）、`0004-auth-sessions.md`、`0005-ingestion-queue.md`、`0006-usage-metering.md`、`0007-api-keys.md`、`0008-deployment.md`、`0009-multi-tenancy.md`、`0010-routing-and-quotas.md`、`0011-traces.md`、`0012-agent-tools.md`、`0013-prompt-templates.md`、`0014-cost-snapshot.md`、`0015-admin-audit.md`、`0016-workflow-engine.md`、`0017-collaboration.md`、`0018-metrics-budget.md`、`0019-hybrid-retrieval.md`、`0020-evaluation-platform.md`、`0021-sdk-webhooks.md`、`0022-unified-usage-ledger.md`、`0023-async-runs.md`。

### API 文档

位于 `docs/api/`：`quickstart.md`、`errors.md`、`workflows.md`、`webhooks.md`、`provider-configs.md`、`model-marketplace.md`、`content.md`、`projects.md`、`agents-plugins.md`、`assist.md`。

### TDD / 实现与验证证据

- P0：`p0-s1-auth.md`、`p0-s2-provider-sse.md`、`p0-s3-ingestion.md`、`p0-s4-retrieval.md`；评测基线：`docs/eval/retrieval-baseline.md`。
- P1：`p1-s1-infra.md`、`p1-s2-queue.md`、`p1-s3-usage.md`、`p1-s4-api-keys.md`、`p1-s5-pre-frontend-contract.md`、`p1-s5a-frontend.md`、`p1-s5b-knowledge.md`、`p1-s5c-console.md`、`p1-s6-deploy.md`。
- P2：`p2-s1-workspaces.md`、`p2-s2-routing.md`、`p2-s3-quotas.md`、`p2-s4-traces.md`、`p2-s5-frontend-platform.md`、`p2-s6-hardening.md`。
- P3：`p3-s1-agents.md`、`p3-s2-tools.md`、`p3-s3-prompts.md`、`p3-s4-cost.md`、`p3-s5-admin.md`、`p3-s6-polish.md`。
- P4：`p4-s1-workflows.md`、`p4-s2-workflow-nodes.md`、`p4-s3-collaboration.md`、`p4-s4-metrics.md`、`p4-s5-ops.md`、`p4-s6-final.md`。
- P5：`p5-s1-retrieval.md`、`p5-s2-evaluation.md`、`p5-s3-sdk-webhooks.md`、`p5-s4-usage-ledger.md`、`p5-s5-async-runs.md`、`p5-s6-polish.md`。
- P6：`p6-s1-provider-hub.md`、`p6-s2-model-marketplace.md`、`p6-s3-portal.md`、`p6-s3c-content.md`、`p6-s4-projects.md`、`p6-s5-agents-plugins.md`、`p6-s6-assist.md`、`p6-chat-ui.md`、`p6-b.md`。
- P7/P8/P9：`p7.md`、`p8.md`、`p9-s0-s1.md`、`p9-s2-retrieval.md`、`p9-s3-builder.md`、`p9-s4-eval.md`、`p9-s5-sources.md`、`p9-s6-hardening.md`。
- P10：`p10-s0-s1.md`、`p10-s2-extraction.md`、`p10-s3-injection.md`、`p10-s4-permissions.md`、`p10-s5-graph.md`、`p10-s6-quality.md`。
- P11：`p11-s1-canvas.md`、`p11-s2-node-debug.md`、`p11-s3-builder-control.md`、`p11-s4-agent-tools.md`、`p11-s5-knowledge-nodes.md`、`p11-s6-retrieval-analytics.md`、`p11-s7-memory-lifecycle.md`、`p11-s8-memory-sources-quality.md`、`p11-s8b-memory-sources.md`、`p11-s9-semantic-conflicts.md`、`p11-s10-p0-closure.md`、`p11-s11-p1.md`、`p11-s12-p1-followups.md`、`p11-s13-p1-remainder.md`、`p11-s14-knowledge-complete.md`。
- P12 及模型/UI 补充：`p12-s1-chat-modes.md`、`p12-s2-web-search.md`、`p12-s3-study.md`、`p12-s4-reuse.md`、`p12-s5-chat-tasks.md`、`p12-s6-research.md`、`p12-s7-agent-tasks.md`、`p12-s8-thinking.md`、`p12-s9-integrations.md`、`p12-s10-skills-connectors.md`、`p12-ui-overhaul.md`、`provider-model-capabilities.md`、`provider-model-context-config.md`、`inner-model-marketplace.md`，均位于 `docs/tdd/`。

## 3. 常用命令

所有 Python 命令使用项目虚拟环境。Windows 下解释器为 `.venv/Scripts/python.exe`。

### 环境、测试和代码质量

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
.venv/Scripts/python.exe -m pytest
.venv/Scripts/python.exe -m pytest tests/test_documents.py::test_upload_ingests_and_marks_ready
.venv/Scripts/python.exe -m pytest --cov=app --cov-report=term-missing
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format .
.venv/Scripts/python.exe -m pytest -n auto
```

### 本地运行、迁移和 Docker

```bash
.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
.venv/Scripts/python.exe -m alembic upgrade head
# 新迁移：先确保数据库结构与 models 一致
.venv/Scripts/python.exe -m alembic revision --autogenerate -m "..."
docker compose up -d api worker
docker compose up -d --build
docker compose logs -f api worker web
```

API 容器启动时先执行 `alembic upgrade head`，再启动 uvicorn。Docker 主机端口：API `8002`、Web `8080`；VM 中的 `8000/8001` 已被 vLLM 占用。Web 容器通过 nginx 服务 SPA，并将 `/api` 代理到 `api:8000`。

### 部署、监控和备份

```bash
curl http://192.168.29.100:8002/metrics
docker compose --profile observability up -d prometheus
# 设置 .env 中的 CADDY_DOMAIN 后启用 HTTPS
docker compose --profile https up -d caddy
docker compose exec -e RUN_ONCE=1 backup /bin/sh /usr/local/bin/backup_postgres.sh
```

可选 Prometheus UI 为 `9090`；Caddy 使用 `80/443`。备份为每日 `pg_dump -Fc`，保留 7 天。

### 压测与工作流示例

```bash
.venv/Scripts/python.exe scripts/loadtest.py --base-url http://192.168.29.100:8080/api --concurrency 20
.venv/Scripts/python.exe scripts/loadtest_knowledge.py --base-url http://192.168.29.100:8002 --concurrency 10 --requests 50
.venv/Scripts/python.exe scripts/loadtest_memories.py --base-url http://192.168.29.100:8002 --concurrency 10 --requests 30 --memories 60
AI_POWER_BASE_URL=... AI_POWER_EMAIL=... AI_POWER_PASSWORD=... .venv/Scripts/python.exe scripts/workflow_example.py --provider local-qwen --model <model>
.venv/Scripts/python.exe scripts/loadtest_workflow.py --base-url http://192.168.29.100:8002 --provider local-qwen --model <model> --concurrency 3
```

### API / 数据准备 / SDK

```bash
# 运行本地 Arq Worker（需要 Redis）
.venv/Scripts/python.exe -m arq app.worker.WorkerSettings
# Postgres + Redis；Docker 在 WSL 中运行，Windows 访问宿主机用 192.168.29.100
docker compose up -d postgres redis

curl -s http://192.168.29.100:8001/v1/models  # 预期模型：bge-reranker-v2-m3
curl -s http://192.168.29.100:8002/provider-configs -H "Authorization: Bearer $TOKEN"
curl -s http://192.168.29.100:8002/market/models
curl -OJ "http://192.168.29.100:8002/conversations/<id>/export?format=markdown" -H "Authorization: Bearer $TOKEN"
curl -N "http://192.168.29.100:8002/workflows/runs/<run_id>/events?after=0" -H "Authorization: Bearer $TOKEN"
curl -X POST "http://192.168.29.100:8002/workflows/runs/<run_id>/cancel" -H "Authorization: Bearer $TOKEN"

# 初始化公共模型目录 / 评测数据
docker compose cp scripts/seed_market_models.py api:/tmp/seed_market_models.py && docker compose exec -T api python /tmp/seed_market_models.py
docker compose cp scripts/seed_models.py api:/tmp/seed_models.py && docker compose exec -T api python /tmp/seed_models.py
docker compose cp scripts/seed_platform_prompts.py api:/tmp/seed_platform_prompts.py && docker compose exec -T api python /tmp/seed_platform_prompts.py
.venv/Scripts/python.exe scripts/seed_eval.py
.venv/Scripts/python.exe scripts/eval_retrieval.py --dataset eval/questions.jsonl --workspace-id <uuid> --kb-id <uuid> --top-k 5
AI_POWER_BASE_URL=http://192.168.29.100:8002 AI_POWER_EMAIL=... AI_POWER_PASSWORD=... .venv/Scripts/python.exe scripts/seed_eval_platform.py --kb-name "检索评测集"

# 管理员 / SDK / Webhook 测试
.venv/Scripts/python.exe scripts/grant_admin.py user@example.com
uv pip install --python .venv/Scripts/python.exe -e sdk/python
.venv/Scripts/python.exe -m pytest tests/test_webhooks.py tests/test_sdk.py
```

### 前端

```bash
cd web && npm install
cd web && npm run dev
cd web && npm test
cd web && npm run test:e2e
cd web && npm run build
cd web && npm run typecheck
```

开发服务器端口 `5173`，`/api` 默认代理到 `http://192.168.29.100:8002`（可用 `VITE_PROXY_TARGET` 覆盖）。若 `/api/*` 返回 SPA HTML，通常是旧 Vite 进程占用了 5173，需要结束旧进程并重启。首次 Playwright E2E 需执行 `npx playwright install chromium`。

### 其他操作提示

- Docker 构建默认使用清华 PyPI 镜像；可用 `docker compose build --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ api` 覆盖。
- pgvector/trigram 集成测试需设置 `TEST_POSTGRES_URL=postgresql+asyncpg://ai_power:<password>@192.168.29.100:5432/ai_power_test`，再运行 `tests/test_postgres_vector.py` 和 `tests/test_retrieval_postgres.py`。
- Windows 下在容器执行 SQL 时，建议通过 stdin 传给 `psql`：`printf 'SELECT 1;\n' | docker exec -i <postgres-container> psql -U ai_power -d postgres`；Windows 的 `docker exec ... -c "带空格 SQL"` 参数可能被拆分。
- Reranker 服务预期在 `http://192.168.29.100:8001/v1/models` 返回 `bge-reranker-v2-m3`；可用 `RERANK_ENABLED=false` 关闭。

## 4. 架构与关键行为

### 4.1 技术栈与代码分层

- 后端调用链：`app/routers/*`（HTTP）→ `app/deps.py`（认证、Provider Registry）→ `app/services/*`（访问控制、解析、分块、存储、入库、检索、RAG、评测等）→ `app/models.py` / `app/schemas.py` / `app/security.py`。
- `app/providers/` 是 LLM/Embedding Provider 边界；`app/vector.py` 管理 pgvector/JSON 向量类型。
- 前端 `web/`：Vite、React 18、TypeScript、React Router、TanStack Query（服务端状态）、Zustand（认证/UI 状态）、Tailwind tokens。
- 开发/测试使用 SQLite（aiosqlite、NullPool）；生产使用 PostgreSQL + pgvector。Schema 变更通过 Alembic；`init_db()` 仍用于测试和本地开发建表。

### 4.2 认证、租户和权限

- 密码使用 Argon2id。`POST /auth/login` 返回 30 分钟 HS256 access JWT（`sub` 为用户 UUID，含 `jti`）和 7 天 refresh token；refresh 单次轮换，旧 token 吊销，重用会被拒绝；logout 吊销 refresh token。Refresh Token 仅以 SHA-256 哈希存储。
- 登录按客户端 IP 经 Redis 限流（10 次/分钟）；Redis 故障 fail-open 并记录 warning。受保护路由通过 HTTPBearer 解析用户；跨用户/跨 Workspace 资源通常返回 404。
- 注册时为用户创建个人 Workspace。资源按 `workspace_id` 隔离；JWT 通过 `X-Workspace-Id` 选择 Workspace（默认个人 Workspace）。API Key 固定绑定 Workspace，冲突的 Workspace Header 会被拒绝。`AuthContext` 包含 user、workspace、role、scopes。
- Workspace Owner 可按邮箱邀请/移除成员；成员可见 Workspace 资源。Projects 可由成员读取/使用，只有创建者或 Workspace Owner 可编辑/归档。
- 管理员为 `users.role == "admin"`；非管理员访问 `/admin/*` 返回 404，匿名请求为 401。管理员能力包括用户、Workspace/成员、全局用量/成本、模型目录、模型启停、套餐调整、内容和插件/MCP/数据库管理等，操作写入审计日志；审计记录按 90 天清理。Trace 按 7 天清理。

### 4.3 会话、消息和 SSE

- `POST /conversations/{id}/messages` 持久化用户消息和流式助手消息，SSE 顺序为 `meta → delta* → usage → done`，或以终止 `error` 结束。启用 RAG 时在 delta 前发送 `citation*`；引用只来自实际放入 Prompt 的检索块。
- 流生成器使用新的 `SessionLocal` 会话完成助手消息，并写一条追加式 `usage_events` 及 `message_citations`。历史会话回放已持久化引用。
- Chat 通过 `fetch + ReadableStream` 解析 SSE（不是 EventSource）；流式阶段显示纯文本，完成后渲染 Markdown。
- 会话支持搜索、置顶、归档/恢复、移动、批量归档/删除、标题修改、模型/Provider 切换、生成参数、消息编辑/回复/重新生成、消息反馈及 Markdown/JSON 导出。重新生成会创建新助手消息和新的计费用量记录。
- Provider/模型切换只影响后续消息；历史消息保留各自的 Provider/模型归属。生成参数白名单：temperature `0–2`、max_tokens `1–32768`、top_p `0–1`，服务端会 clamp。
- Chat 支持 PDF/DOCX/CSV/MD/TXT 附件解析；图片仅在显式选择视觉模型且非 Agent 模式下作为 image_url 发送。附件文本注入当前用户轮次及历史上下文。文件下载必须限制在 `UPLOAD_DIR` 内。
- 一个会话最多关联 10 个 KB；兼容字段 `kb_id` 仍代表第一个 KB。当前多 KB 检索使用第一个 KB 的 Embedding/Reranker 配置。

### 4.4 Provider、模型目录与路由

- `LLMProvider` 定义 `list_models`、`stream_chat`；`EmbeddingProvider` 定义 `embed`。`OpenAICompatProvider` / `OpenAICompatEmbeddingProvider` 对接 DeepSeek、llama.cpp、vLLM 等兼容接口。
- Provider 配置按 Workspace 管理，默认私有，可选择只读共享；API Key 使用 Fernet 加密并仅返回脱敏提示。用户可测试连接、同步/手动添加模型并维护能力标签。Provider 密钥不从 API 返回。
- `get_scoped_registry` 合并平台 Provider 与当前用户可访问的私有/共享 Provider；异步任务按任务所有者构建同一 Registry。
- 模型能力包括工具调用、上下文窗口、最大输出、多模态和思考等级。已知模型族可推断 tools 能力；用户手动能力设置优先。上下文窗口和输出长度支持用户配置，历史/RAG 预算使用配置值；0 保留旧的 12 条消息策略。
- `model_catalog` 保存路由/价格等平台信息；`market_models` 独立保存公共展示元数据。公共模型目录无需登录，管理员维护；用户激活模型时自行提供 Base URL 和 Key，密钥不会随目录分发。
- `provider_id="auto"` 按优先级选候选，跳过 60 秒内 Redis 失败次数达到 3 次的 Provider；仅首个 Token 之前允许回退，流中失败不重试。消息记录实际使用的 Provider/模型。
- 用户 Provider 模型在会话创建时进行能力校验：普通 Chat 需要 chat 能力，Agent 需要 tools 能力。

### 4.5 知识库、文档入库和检索

- 上传接口校验用户/KB 权限和扩展名，将 UUID 文件写入 `UPLOAD_DIR`，创建 `Document(uploaded)` 与 `IngestionJob(queued)` 并投递 Arq。Worker 状态流转：uploaded → parsing → embedding → ready；失败记录类型化 `error_code`，按指数退避重试，超过上限进入 dead。租约过期任务会被定时重新入队。
- 入库按 `(user_id, kb_id, content_hash)` 幂等；重复文件返回既有文档并标记 `duplicate=true`。手动 retry 可重试失败文档；删除文档时删除文件，定时任务清理超过 24 小时的孤儿文件。
- 支持 PDF/DOCX/CSV/MD/TXT，以及 HTML/XLSX/PPTX；支持 URL/HTML/有限同源站点导入。路径、URL、重定向、字节数和站点抓取范围均受限；可选视觉模型 OCR 用于图片或空白 PDF 页面。
- `EmbeddingVector` 在 PostgreSQL 使用 `vector(1024)`，SQLite 使用 JSON。PostgreSQL 启用 pgvector、L2/HNSW（`vector_l2_ops`）索引；查询使用 L2/cosine 距离运算符。
- 检索先按 KB 配置嵌入 Query，再执行向量召回；混合模式同时执行 pg_trgm 词法召回，使用 RRF（`1/(60+rank)`）融合，可选 bge-reranker-v2-m3 重排。重排失败回退融合排序并计指标。
- 检索过滤 Workspace/KB、文档 ready、未删除等条件；上下文按字符预算贪心截断。引用由实际进入 Prompt 的 `RetrievedChunk` 构造，绝不解析模型文本生成引用。RAG Prompt 将 `<reference_material>` 声明为不可信数据。
- KB 有独立分块、检索、Embedding、Reranker 和索引设置；分块配置变化只影响新入库或重新处理的文档。检索调试 API/UI 可查看向量/词法/融合/重排排名和耗时。
- 知识处理工作流将结果暂存于 `knowledge_chunk_drafts`，只有 apply 才原子替换文档 chunks/embeddings；上传和重处理会执行 KB 绑定的不可变处理版本。检索工作流同步执行，失败自动回退内置检索。

### 4.6 Agent、工具、插件与协作

- 内置 Agent 包含 supervisor、retrieval、math；Agent Runner 采用 JSON 工具协议，每轮输出一个 JSON 对象（工具调用或最终答案），最多 8 步、深度 2。无法解析的输出按最终答案处理。工具定义位于 `app/tools/`，Agent 定义位于 `app/agents/`，执行循环位于 `app/services/agent.py`。
- 内置工具有 Workspace/会话 KB 范围内的 `kb_search`、`current_time` 和 AST 白名单计算器。检索工具回传引用 SSE 和持久化引用。Trace 仅保存 Agent 元信息，不保存工具参数或输出正文。
- 自定义 Agent 可设置指令、Provider/模型、KB、多工具白名单、插件、模式、生成参数、附件开关、Workflow 绑定、记忆权限等；运行复用 AgentRunner、SSE、Trace 和用量账本。
- 插件由管理员定义 GET/POST HTTP 工具，Workspace Owner 配置加密凭证；会话显式启用。敏感插件需先确认。执行时检查 HTTPS、DNS、私网/回环/保留地址和可选 Host 白名单，禁用重定向，限制超时和响应大小；调用记录不含凭证。
- Planner–Worker–Critic 协作包含计划、并行 Worker 和 Critic，最多两轮修订，并受全局步骤预算和每步配额限制。运行、步骤和事件持久化，可回放/取消。
- Agent Builder 注入节点清单、可访问模型/KB/Agent/插件及当前定义；验证失败时有限次数修复，并报告缺失资源。生成只更新草稿，不自动运行或发布；多轮会话支持 generate/modify/explain/fix、节点差异、失败运行上下文和确认后应用。
- Agent 市场公开已发布的脱敏快照；复制后清除原 KB/插件/Agent 绑定，需重新绑定。Agent 体验页支持自主对话或 Workflow 运行；统一运行接口合并 Chat/Workflow 记录。评分、举报、管理员审核均有独立记录。

### 4.7 Workflow、Review、MCP 和数据库节点

- Workflow 使用 `workflows` 与不可变 `workflow_versions` 保存定义；节点包括 start/output、llm、kb_search、tool、agent、condition、parallel、join、review、loop、http、mcp、mcp_resource、mcp_prompt、memory_read、memory_write、code、database。
- 校验包含唯一 ID、配置白名单、入口、可达性、无环、条件分支边、并行 fan-out 和 Join fan-in。执行器处理未选分支跳过、Join 前驱等待、并行上限、节点重试、配额和运行取消。
- Workflow/Collaboration 可通过 Arq 排队；run/event/节点状态持久化。事件具有单调递增 seq，SSE 支持 `after` / `Last-Event-ID` 回放和 tail；排队任务可立即取消，运行中在节点/步骤边界响应取消。
- Review 节点创建 Workspace 范围的待审核项并暂停运行；Checkpoint 保存输出、节点/边状态及待审信息。Worker 崩溃/重启可恢复，不重复执行已完成节点；Workspace 成员可批准/拒绝。
- Loop 是节点内循环，不是图环；支持 foreach/repeat、可选每轮 LLM、until 条件和最大迭代数。
- HTTP 节点使用 SSRF 防护、HTTPS/Host 白名单、DNS/私网限制、禁重定向及超时/响应大小上限。
- MCP Server 由管理员配置，凭证加密；支持 Streamable HTTP JSON-RPC 的 initialize、tools、resources、prompts 等操作及 SSE/JSON 响应。
- Code 节点使用 AST 白名单表达式执行器，不允许导入、属性遍历、推导式、lambda 或多语句。Database 节点仅连接管理员配置的 PostgreSQL，只读事务，只允许单条 SELECT/WITH，参数绑定并限制行数/超时。

### 4.8 个人记忆

- 记忆数据包含作用域、类别、状态、来源、标签、版本、敏感度、启用/置顶/收藏、有效期、使用次数和关系；有候选、版本、关系、使用事件及设置表。
- 助手回答完成后排队异步记忆提取；提取具备幂等、Hash/Embedding 去重和更新建议。显式“记住”可直存；默认策略要求确认，候选进入 Inbox 审核。缺少项目/Agent 上下文或检测到敏感内容时不会静默自动保存。
- `select_memories` 统一作用域/排除/模型过滤，结合向量、词法、重要性、时效、使用情况排序并受字符预算限制。Chat/Agent/Workflow 可注入或读写记忆，记录 `memory_usage_events`，消息保存 `memory_refs`。
- 项目和 Agent 有独立读写权限矩阵；全局记忆读取受 Provider/模型/Agent 白名单限制。Workflow/文档来源提取必须同时开启来源开关和 Memory Settings 授权。
- 关系图支持自动/手动关系、过滤和一跳局部图；质量分析覆盖重复、矛盾、过期、未使用、缺失来源、不完整、孤立关系等，并支持建议应用/忽略/回滚。夜间任务重建关系和生成建议；保留策略只标记过期，不硬删除。

### 4.9 用量、Trace、配额和监控

- 每次计费 LLM 调用写入 append-only `usage_events`；来源包含 chat、workflow、collaboration、arena、prompt_lab、model_eval、agent_builder、memory_extraction、image_analysis、skill 等。账本记录 Provider/模型、Token、成本快照、source、API Key、节点/步骤等归因；`source_ref_id` 用作通用幂等引用，运行类记录可不关联 message。
- 价格在写入时从模型目录快照保存，后续价格变化不改写历史。成本计算为 `prompt_tokens / 1e6 * input_price + completion_tokens / 1e6 * output_price`，保存 6 位小数。汇总接口按日期/Provider/模型/来源及 API Key 统计；JWT 调用进入未归属 Key 桶。账本记录不可更新或删除，业务侧只能追加、查询聚合。
- 每条 Chat 请求有 Trace（request_id、检索耗时、TTFT、总耗时、状态/错误码、路由尝试等）；Trace 按 Workspace 隔离，保留 7 天。
- Redis 计数器实施请求/Token/Key/上传配额，429 带 `Retry-After` 和 `X-Quota-*`；Token 在流结束后累计，NULL usage 按 0 处理。Redis 故障按现有逻辑 fail-open。
- `/metrics` 输出 Prometheus 文本，包括 HTTP 请求耗时、活跃 SSE、Token/成本、入库任务和熔断状态；每日 Workspace 成本预算覆盖 Chat/Workflow/Collaboration，首次超限写审计，可选发送 Webhook。

### 4.10 API Key、SDK、Webhook 与外部集成

- API Key 格式 `ap_<8hex>_<secret>`，仅存 SHA-256 哈希，创建时明文只返回一次；支持 `chat:write`、`kb:read`、`workflow:run` scope、过期时间和每分钟限流。Key 管理、Provider 配置、上传/删除、归档、Webhook 和用量等接口仍要求 JWT。`last_used_at` 最多每 60 秒更新一次。
- Python SDK 位于 `sdk/python`，支持同步/异步、登录/刷新/API Key、类型化错误、GET 重试、SSE、Chat、KB 上传/检索、Workflow/Collaboration 运行、模型和用量。当前未发布到 PyPI。
- Webhook 由 Workspace Owner 管理，密钥加密；业务事件入队时不发网络请求。Worker 校验 URL/DNS/SSRF 后使用 `HMAC-SHA256` 签名，重试间隔为 1m/5m/30m/2h/6h（受最大次数配置限制），记录投递日志并支持重放。事件包括 `message.completed`、`document.ready`、`document.failed`、`workflow.completed`、`collaboration.completed`、`budget.exceeded`。
- BYOK 集成代理图片和音频能力；GitHub 连接器目前只读。实时语音和 Google OAuth 尚未实现。

### 4.11 前端路由与交互

- Access Token 保存在内存；Refresh Token 在 localStorage，通过 single-flight 轮换并在 401 时重试一次。主题存储在 `localStorage.ai_power_theme`，首次访问跟随系统主题。
- 公开路由：`/`、`/models`、`/models/:slug`、`/models/:slug/playground`、`/market/agents`、`/market/agents/:slug`、`/announcements`、`/announcements/:id`、`/help`、`/login`。
- 控制台/工作区路由：`/dashboard`、`/chat`、`/chat/:id`、`/studio`、`/studio/:id`、`/archive`、`/projects`、`/projects/:id`、`/agents`、`/agents/:id`、`/agents/:id/experience`、`/plugins`、`/memory`、`/files`、`/search`、`/knowledge`、`/knowledge/:id`、`/workflows`、`/collaborations`、`/evaluation`、`/usage`。
- 设置/管理路由：`/settings/providers`、`/settings/api-keys`、`/settings/workspace`、`/settings/prompts`、`/settings/profile`、`/settings/webhooks`、`/settings/integrations`、`/media`、`/notifications`、`/admin`、`/admin/content`、`/admin/plugins`、`/admin/mcp`、`/admin/databases`、`/admin/prompts`。
- 会话侧栏负责 Workspace 切换、搜索、项目过滤、置顶/时间分组历史和会话菜单；控制台侧栏按 Work/Build/Account 分组。上传通过 XHR 显示进度，文档处理期间每 2 秒轮询状态。

### 4.12 部署、日志与健康检查

- Compose 服务：PostgreSQL、Redis、API、Worker、Web、Backup；可选 Prometheus、Caddy。API/Worker 使用 `LOG_FORMAT=json`；请求包含 `X-Request-ID`，日志记录 method/path/status/duration/user_id。
- nginx 服务 `web/dist`、SPA 回退 `index.html`，将 `/api/` 代理到 `api:8000`，SSE 关闭代理缓冲。API/Worker 共用 uploads volume。
- `GET /healthz` 为存活检查；`GET /readyz` 检查 `SELECT 1` 和 Redis PING，依赖不可用时返回 503 和各项状态。
- CORS 允许 `CORS_ORIGINS`（默认 Vite 5173 和 LAN 8080），允许 Authorization、Content-Type、X-API-Key，并暴露 Retry-After。
- 外部模型服务：本地 Qwen `http://192.168.29.100:8083/v1`（llama.cpp）；bge-m3 `http://192.168.29.100:8000/v1`（vLLM，1024 维）；DeepSeek `https://api.deepseek.com`；Reranker 默认 `http://192.168.29.100:8001`。

## 5. 开发约定与不可破坏的既有约束

- 测试先行：先写失败测试并运行，再实现；RED/GREEN 证据写入 `docs/tdd/`。
- 新增用户资源必须按 `user_id` 过滤，并为两个用户编写隔离测试；跨用户资源访问返回 404。
- 入库必须保证 `(user_id, kb_id, content_hash)` 幂等；每次失败都设置类型化 `error_code`，并将 `IngestionJob.status` 设为 failed。
- 上传扩展名按允许列表校验（基础上传为 `.pdf/.md/.txt`）；不能信任客户端文件名或 Content-Type 作为路径，文件以 UUID + 后缀存放在 `UPLOAD_DIR`。
- SSE 基础事件契约：`meta`、`citation`、`delta`、`usage`、`done`、`error`；`error` 为终止事件。citation 只能表示实际用于 Prompt 的检索块。
- 不得通过解析模型输出构造引用；必须依据 `fit_context` 后的 `RetrievedChunk` ID 构造。
- `usage_events` 是 append-only：业务代码不得更新或删除，只能查询聚合。
- Provider/Embedding 厂商代码只能位于 `app/providers/`；不得在其他模块直接导入厂商 SDK。密钥只从 settings/env 读取。
- 不记录 Authorization、Provider API Key 或完整文档正文。
- Windows 使用 `.venv/Scripts/python.exe`；Docker 主机地址使用 `192.168.29.100`，不要在 Windows 侧误用 `localhost`；向 psql 传 SQL 时使用 stdin。
