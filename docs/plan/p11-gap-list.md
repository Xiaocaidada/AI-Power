# P11 功能缺口清单（Agent / 知识库 / 记忆）

## 1. 判定口径

- **P0**：影响核心闭环、数据安全或需求文档明确要求的“主流程”，应优先补齐。
- **P1**：明显影响体验、生态或高级用户效率，P0 之后安排。
- **P2**：高级/差异化能力，依赖外部系统或较大架构投入，按需推进。
- **MVP+**：端到端可运行、可演示、可日常使用，但不是需求文档的完整实现。

现有成熟度：

| 模块 | 当前定位 | 已覆盖 | 主要缺口 |
|---|---|---|---|
| Agent | 四层 MVP+ | 广场/创建/画布/AI Builder/发布/体验/运行记录 | 画布工程化、版本恢复、单节点调试、工具生态、AI Builder 控制 |
| 知识库 | P1–P4 核心 MVP+ | 处理画布/检索画布/AI Builder/评估优化/URL 导入 | 节点库、多 KB 检索、运行分析、数据源、高级能力 |
| 记忆 | 7 模块 MVP+ | 管理/提取/注入/权限/图谱/质量优化/评测/配额 | 仪表盘深度、提取来源、生命周期策略、版本 diff、质量建议广度 |

## 进展

- 2026-11-24：P11-S1 完成，X-P0-1（撤销/重做、自动保存、导入/导出）与 X-P0-2（版本列表/恢复）已落地，见 [p11-s1-canvas.md](../tdd/p11-s1-canvas.md)。
- 2026-11-24：P11-S2 完成，X-P0-3（单节点调试、从节点运行、节点输入输出）已落地，见 [p11-s2-node-debug.md](../tdd/p11-s2-node-debug.md)。
- 2026-11-24：P11-S3 完成，X-P0-4（AI Builder 取消、部分采纳、澄清提问）与多轮上下文已落地，见 [p11-s3-builder-control.md](../tdd/p11-s3-builder-control.md)。

## 2. P0：下一阶段必须补齐

### 2.1 平台级（三类画布共用）

| ID | 缺口 | 现状 | 代码入口 | 改动范围 | 依赖 | 规模 |
|---|---|---|---|---|---|---|
| X-P0-1 | 画布撤销/重做、自动保存草稿、导入/导出 | Agent/知识画布只有保存，无撤销/重做/自动保存/导入导出 | `web/src/pages/studio/StudioCanvas.tsx`、`StudioConfigPanel.tsx`、`app/routers/workflows.py`、`app/models.py` | 画布本地历史栈；Workflow 草稿字段/自动保存 API；定义 JSON 导入导出 | 无 | L |
| X-P0-2 | 工作流版本历史与恢复 | 版本表存在，前端只读最新版；缺历史列表/恢复 | `app/routers/workflows.py`、`web/src/pages/studio/AgentStudioPage.tsx`、`web/src/pages/workflows/*` | 版本列表 API、恢复 API、版本选择/对比 UI | X-P0-1 | M |
| X-P0-3 | 单节点测试/从指定节点运行/节点输入输出检查 | 只有整条运行时间线 | `app/services/workflow/runner.py`、`app/routers/workflows.py`、`StudioRunPanel.tsx` | 局部执行模式、节点输入快照、从节点开始 | X-P0-2 | L |
| X-P0-4 | AI Builder 取消、部分采纳、澄清提问 | 生成后整体应用；无取消/澄清/部分应用 | `web/src/pages/studio/StudioBuilderPanel.tsx`、`app/routers/agent_builder.py`、`app/services/agent_builder.py` | 生成任务取消、diff 选择应用、澄清问题协议 | X-P0-1 | M |

### 2.2 Agent

| ID | 缺口 | 现状 | 代码入口 | 改动范围 | 依赖 | 规模 |
|---|---|---|---|---|---|---|
| A-P0-1 | 基础 Agent 模型参数 UI（temperature/max_tokens/top_p） | `generation_settings` 已存储，配置页未暴露 | `web/src/pages/studio/StudioConfigPanel.tsx`、`AgentStudioPage` 保存逻辑、`app/schemas.py` | 配置表单、保存校验、与运行参数合并 | 无 | S |
| A-P0-2 | Agent 工作流模板与模板市场 | 只有知识处理模板；Agent 无模板 | `app/services/workflow/catalog.py`、`app/routers/workflows.py`、`web/src/pages/studio` | 模板定义、模板列表/复制、初始画布 | X-P0-1 | M |
| A-P0-3 | Agent 工具浏览/测试与 MCP 工具绑定 | 工具白名单固定；MCP 只在工作流节点 | `app/services/custom_agents.py`（`AGENT_TOOL_NAMES`）、`app/services/agent.py`、`app/tools/*`、`app/routers/mcp_servers.py` | MCP 工具适配为 Agent 工具、工具测试接口/UI、权限校验 | MCP 服务可用 | L |
| A-P0-4 | 项目文件与多项目 Agent 关联 | 项目仅默认 Agent + KB | `app/services/projects.py`、`app/routers/projects.py`、`app/services/custom_agents.py` | 项目 Agent 列表、项目文件工具、项目作用域权限 | 项目文件中心 | M |

### 2.3 知识库

| ID | 缺口 | 现状 | 代码入口 | 改动范围 | 依赖 | 规模 |
|---|---|---|---|---|---|---|
| K-P0-1 | 处理节点补齐：语义/父子/自定义切片、元数据保留 | 固定/Markdown/递归切片 | `app/services/knowledge/chunkers.py`、`catalog.py`、`pipeline.py` | 新切片器、节点配置、预览、暂存写入 | 无 | L |
| K-P0-2 | 文档增强节点：标题/结构/元数据/关键词/摘要/去重 | 只有 parse/clean/chunk/embed/index | `app/services/knowledge/catalog.py`、`pipeline.py`、`app/services/parsing.py` | 节点实现、LLM/规则增强、错误处理、预览 | 模型调用 | L |
| K-P0-3 | 检索节点补齐：元数据过滤、相似度阈值/去重、多 KB 联合检索 | 单 KB 线性检索，节点较少 | `app/services/knowledge/retrieval_catalog.py`、`retrieval_pipeline.py`、`app/services/retrieval.py` | 新节点、跨 KB 合并、KB 选择配置 | 检索画布 | L |
| K-P0-4 | 知识库运行分析面板 | 有节点耗时/评测分析，无处理成功率/无结果/平均耗时面板 | `app/services/knowledge/metrics.py`、`app/metrics.py`、`app/routers/knowledge_bases.py`、`web/src/pages/knowledge/KnowledgeDetailPage.tsx` | 运行统计 API、失败原因聚合、前端面板 | 无 | M |
| K-P0-5 | 处理配置对比评测 | 评测只绑定检索工作流 | `app/services/evaluation_runner.py`、`app/routers/evaluations.py`、`KnowledgeEvaluationPage.tsx` | 处理版本/配置维度、对比报告 | K-P0-1/K-P0-2 | M |

### 2.4 记忆

| ID | 缺口 | 现状 | 代码入口 | 改动范围 | 依赖 | 规模 |
|---|---|---|---|---|---|---|
| M-P0-1 | 记忆完整度与使用聚合 | 总览有计数；缺完整度分析、按模型/Agent/项目/会话聚合 | `app/services/memories.py::memory_stats`、`app/routers/memories.py`、`MemoryPage.tsx` | 聚合查询、完整度维度、前端图表 | 无 | M |
| M-P0-2 | 生命周期策略执行 | `retention_days` 未执行；无按记忆更新策略；`blocked_topics` 只在提取链路 | `app/services/memories.py`、`memory_extraction.py`、`app/worker.py` | 创建/更新统一拦截、过期清理任务、策略字段 | 无 | M |
| M-P0-3 | 记忆版本 diff/变化分析 | 只有版本列表与恢复 | `app/services/memories.py`、`app/routers/memories.py`、`MemoryDetailDialog.tsx` | 快照 diff、变化摘要、风险提示 | 无 | S |
| M-P0-4 | 质量建议广度 | 只覆盖重复/冲突/过期/未用/分类 | `app/services/memory_quality.py`、`MemoryQualityPanel.tsx` | 图谱优化、项目补充、规则调整、关系异常 | M-P0-1 | M |
| M-P0-5 | 更多提取来源 | 主要来自聊天消息 | `app/services/memory_extraction.py`、`app/worker.py`、工作流/项目完成钩子 | 项目活动、工作流执行、文档授权提取 | 用户授权与去重 | L |
| M-P0-6 | 检索过滤维度 | 无时间范围、关系关联检索、按使用场景筛选 | `app/services/memories.py::select_memories/list_memories`、`app/routers/memories.py` | 时间/关系/场景过滤、查询参数与 UI | 图谱关系 | M |

## 3. P1：体验与生态

### 3.1 Agent

| ID | 缺口 | 现状 | 代码入口 | 改动范围 | 依赖 |
|---|---|---|---|---|---|
| A-P1-1 | 广场封面、发布者筛选、官方精选组合 | 有图标/分类/featured，无封面/作者筛选 | `app/models.py`（CustomAgent）、`app/routers/agent_market.py`、`web/src/pages/market` | 封面字段、筛选/排序、审核展示 | 无 |
| A-P1-2 | Agent 模板创建（从模板起步） | 只能从零或复制公开 Agent | `app/services/custom_agents.py`、`web/src/pages/studio` | 模板定义、创建流程 | A-P0-2 |
| A-P1-3 | AI Builder 流式状态与多轮上下文增强 | 无生成阶段流、澄清、取消已列 P0 | `app/routers/agent_builder.py`、`StudioBuilderPanel.tsx` | SSE/阶段事件、上下文摘要 | X-P0-4 |
| A-P1-4 | Agent 附件能力声明与限制 | 附件复用聊天，未按 Agent 能力声明 | `app/services/custom_agents.py`、`app/routers/conversations.py`、`StudioConfigPanel.tsx` | 能力字段、上传/解析开关 | 无 |
| A-P1-5 | Agent 级运行分析与工作流优化建议 | 有运行记录，无成功率/成本/节点瓶颈分析 | `app/services/custom_agents.py::list_agent_runs`、`app/metrics.py`、`AgentExperiencePage.tsx` | 聚合指标、失败原因、建议 | X-P0-3 |

### 3.2 知识库

| ID | 缺口 | 现状 | 代码入口 | 改动范围 | 依赖 |
|---|---|---|---|---|---|
| K-P1-1 | 完整处理节点库 | 只有 parse/clean/chunk/embed/index | `app/services/knowledge/catalog.py`、`pipeline.py` | OCR 节点、格式专用解析、文本处理、全文/混合索引 | K-P0-1/2 |
| K-P1-2 | 完整检索节点库 | 无查询扩展/多查询/意图/分类/回退 | `app/services/knowledge/retrieval_catalog.py`、`retrieval_pipeline.py` | 新节点、条件分支或回退语义 | K-P0-3 |
| K-P1-3 | 文档处理结果与解析原文预览 | 有 chunk/preview，无专门解析结果页 | `web/src/pages/knowledge/KnowledgeChunksTab.tsx`、`app/services/parsing.py` | 解析文本/结构预览、失败定位 | 无 |
| K-P1-4 | 评估指标补齐：引用准确性、答案忠实度 | 有 Recall/Precision/NDCG、LLM judge | `app/services/knowledge/metrics.py`、`app/services/evaluation_runner.py` | 引用校验、答案指标 | 评测平台 |

### 3.3 记忆

| ID | 缺口 | 现状 | 代码入口 | 改动范围 | 依赖 |
|---|---|---|---|---|---|
| M-P1-1 | 按模型/Agent 的细粒度读取白名单 | 只有 `allow_cross_model` | `app/services/memory_permissions.py`、`MemorySettingsPanel.tsx` | 模型/Agent 白名单、选择器 | 无 |
| M-P1-2 | 记忆关系编辑增强 | 只能创建/删除，不能改类型/依据 | `app/routers/memories.py`、`MemoryDetailDialog.tsx` | PATCH 关系、依据编辑 | 无 |
| M-P1-3 | 记忆完整度/变化分析 | 无偏好变化、项目技术栈变化追踪 | `app/services/memory_quality.py`、`MemoryPage.tsx` | 版本对比、变化摘要 | M-P0-3 |
| M-P1-4 | 记忆评测与回答效果联动 | 只有检索 Recall/Precision/MRR | `app/services/memory_eval.py`、`app/services/rag.py` | A/B 注入对比、回答质量指标 | 评测平台 |
| M-P1-5 | 记忆反馈闭环 | 使用记录有，但无“有用/无用”反馈 | `app/models.py`、`app/services/memories.py`、`MemoryPage.tsx` | 反馈表、排序权重、质量建议 | 无 |

## 4. P2：高级与依赖外部

| ID | 缺口 | 说明 |
|---|---|---|
| P2-1 | API/云盘/第三方知识数据源 | 需要连接器、凭证管理与网络策略 |
| P2-2 | 多模态知识处理 | 图像/表格/音视频深度理解，依赖模型能力 |
| P2-3 | 知识图谱与实体消歧 | 需要实体识别、关系抽取、图谱存储 |
| P2-4 | LLM 语义矛盾检测 | 当前为极性/取值/同标题启发式 |
| P2-5 | 实时协同画布 | 需要 CRDT/WebSocket 与冲突合并 |
| P2-6 | 工作流市场与商业化 | 涉及发布审核、计费、版权，非纯技术 |

## 5. 建议 P11 切片

| 切片 | 范围 | 主要产出 | 依赖 |
|---|---|---|---|
| P11-S1 | 画布基础工程化 + 版本恢复 | X-P0-1、X-P0-2 | 无 |
| P11-S2 | 单节点调试/从节点运行 | X-P0-3 | S1 |
| P11-S3 | AI Builder 控制 | X-P0-4、A-P1-3 | S1 |
| P11-S4 | Agent 配置与工具生态 | A-P0-1、A-P0-3、A-P1-1/P1-2 | S1 |
| P11-S5 | 知识处理节点扩展 | K-P0-1、K-P0-2、K-P1-1 | S1 |
| P11-S6 | 知识检索/多 KB/运行分析 | K-P0-3、K-P0-4、K-P1-2 | S5 |
| P11-S7 | 记忆仪表盘/生命周期/diff | M-P0-1、M-P0-2、M-P0-3 | 无 |
| P11-S8 | 记忆提取来源与质量广度 | M-P0-4、M-P0-5、M-P1-1/P1-3 | S7 |
| P11-S9 | 高级能力评估 | P2 项按需 | S5/S6/S8 |

## 6. 验收基线

每个切片至少满足：

- 后端：新增/修改 API 有权限与跨租户 404 测试。
- 前端：关键路径 E2E 或组件测试；空态/错误态/加载态完整。
- 画布：撤销/重做/自动保存/版本恢复不丢配置。
- 知识：新增节点有单节点预览与失败码；评测指标可复现。
- 记忆：应用/回滚幂等；生命周期任务可观测；不自动删除用户数据。
- 全量 `ruff`、`pytest -n auto`、`npm run typecheck`、`npm test`、`npm run build` 通过。

## 7. 明确暂不做

- 真实支付、短信、邮件、KYC、物流等外部业务集成。
- 未授权的外部数据源抓取。
- 未确认的自动删除/覆盖重要记忆。
- 未经用户确认发布 AI 生成的线上工作流。