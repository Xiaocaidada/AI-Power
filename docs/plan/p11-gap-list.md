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
- 2026-11-24：P11-S4 完成，A-P0-1（模型参数）、A-P0-3（工具/MCP 浏览、测试与绑定）、A-P1-1（封面/发布者/官方筛选）与 A-P1-2（Agent 模板）已落地，见 [p11-s4-agent-tools.md](../tdd/p11-s4-agent-tools.md)。
- 2026-11-24：P11-S5 完成，K-P0-1（自定义/父子/语义切片与元数据保留）、K-P0-2（过滤/元数据/关键词/摘要/去重节点）已落地；K-P1-1 完成文本过滤与新节点库，OCR/格式专用解析/独立索引模式仍为边界。见 [p11-s5-knowledge-nodes.md](../tdd/p11-s5-knowledge-nodes.md)。另修复知识处理/检索画布空白页（hooks 顺序）并新增回归 E2E。
- 2026-11-24：P11-S6 完成，K-P0-3（元数据过滤、结果过滤/去重、多 KB 检索）、K-P0-4（处理运行分析）已落地；K-P1-2 完成多查询与空结果回退，意图/分类/同义词扩展仍为边界。见 [p11-s6-retrieval-analytics.md](../tdd/p11-s6-retrieval-analytics.md)。同时修复自定义检索工作流的父块展开边界。
- 2026-11-24：P11-S7 完成，M-P0-1（完整度/使用聚合）、M-P0-2（保留策略执行/blocked topic 统一拦截）、M-P0-3（版本 diff/风险提示）已落地。见 [p11-s7-memory-lifecycle.md](../tdd/p11-s7-memory-lifecycle.md)。
- 2026-11-24：P11-S8 完成，M-P0-4（孤儿/关系异常/项目缺口/规则提示）、M-P1-1（模型/Agent 读取白名单）、M-P1-3（最近变化分析）已落地；M-P0-5 完成项目活动来源。见 [p11-s8-memory-sources-quality.md](../tdd/p11-s8-memory-sources-quality.md)。
- 2026-11-24：P11-S8b 完成，M-P0-5 补齐工作流运行与上传者授权文档来源，默认双重关闭并保持幂等。见 [p11-s8b-memory-sources.md](../tdd/p11-s8b-memory-sources.md)。
- 2026-11-24：P11-S9 完成 P2 评估，并按需实现 P2-4 LLM 语义矛盾检测（显式触发、只生成建议）。其余 P2 项保持后续/不做。见 [p11-s9-p2-assessment.md](../plan/p11-s9-p2-assessment.md) 与 [p11-s9-semantic-conflicts.md](../tdd/p11-s9-semantic-conflicts.md)。
- 2026-11-24：P11-S10 完成剩余 P0：A-P0-2 模板链路验证、A-P0-4 项目 Agent/文件关联与工具、K-P0-5 处理版本对比、M-P0-6 记忆过滤维度。见 [p11-s10-p0-closure.md](../tdd/p11-s10-p0-closure.md)。
- 2026-11-24：P11-S11 完成三项 P1：A-P1-5 Agent 运行分析、K-P1-3 解析原文预览、M-P1-5 记忆反馈闭环。见 [p11-s11-p1.md](../tdd/p11-s11-p1.md)。
- 2026-11-24：P11-S12 完成 A-P1-4 附件能力、K-P1-4 引用/忠实度指标、M-P1-4 记忆 A/B 回答评测。见 [p11-s12-p1-followups.md](../tdd/p11-s12-p1-followups.md)。

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
| A-P0-1 ✅ | 基础 Agent 模型参数 UI（temperature/max_tokens/top_p） | P11-S4 已暴露参数表单、保存校验与会话/工作流生效 | `web/src/pages/studio/StudioConfigPanel.tsx`、`AgentStudioPage` 保存逻辑、`app/schemas.py` | 配置表单、保存校验、与运行参数合并 | 无 | S |
| A-P0-2 ✅ | Agent 工作流模板与模板市场 | P11-S4/S10 已提供三个模板、目录接口与 Studio 创建入口 | `app/services/workflow/catalog.py`、`app/routers/workflows.py`、`web/src/pages/studio` | 模板定义、模板列表/复制、初始画布 | X-P0-1 | M |
| A-P0-3 ✅ | Agent 工具浏览/测试与 MCP 工具绑定 | P11-S4 已提供工具目录、MCP 发现/绑定与单工具测试 | `app/services/custom_agents.py`（`AGENT_TOOL_NAMES`）、`app/services/agent.py`、`app/tools/*`、`app/routers/mcp_servers.py` | MCP 工具适配为 Agent 工具、工具测试接口/UI、权限校验 | MCP 服务可用 | L |
| A-P0-4 ✅ | 项目文件与多项目 Agent 关联 | P11-S10 已新增项目 Agent/文件关联、会话约束与 `project_files` 工具 | `app/services/projects.py`、`app/routers/projects.py`、`app/services/custom_agents.py` | 项目 Agent 列表、项目文件工具、项目作用域权限 | 项目文件中心 | M |

### 2.3 知识库

| ID | 缺口 | 现状 | 代码入口 | 改动范围 | 依赖 | 规模 |
|---|---|---|---|---|---|---|
| K-P0-1 ✅ | 处理节点补齐：语义/父子/自定义切片、元数据保留 | P11-S5 已实现三种切片与 `chunk_meta` 入库/检索父块展开 | `app/services/knowledge/chunkers.py`、`catalog.py`、`pipeline.py` | 新切片器、节点配置、预览、暂存写入 | 无 | L |
| K-P0-2 ✅ | 文档增强节点：标题/结构/元数据/关键词/摘要/去重 | P11-S5 已新增过滤/元数据/关键词/摘要/去重节点 | `app/services/knowledge/catalog.py`、`pipeline.py`、`app/services/parsing.py` | 节点实现、LLM/规则增强、错误处理、预览 | 模型调用 | L |
| K-P0-3 ✅ | 检索节点补齐：元数据过滤、相似度阈值/去重、多 KB 联合检索 | P11-S6 已新增节点级元数据过滤、结果过滤/去重与多 KB 选择 | `app/services/knowledge/retrieval_catalog.py`、`retrieval_pipeline.py`、`app/services/retrieval.py` | 新节点、跨 KB 合并、KB 选择配置 | 检索画布 | L |
| K-P0-4 ✅ | 知识库运行分析面板 | P11-S6 已新增运行统计 API 与“运行分析”页签 | `app/services/knowledge/metrics.py`、`app/metrics.py`、`app/routers/knowledge_bases.py`、`web/src/pages/knowledge/KnowledgeDetailPage.tsx` | 运行统计 API、失败原因聚合、前端面板 | 无 | M |
| K-P0-5 ✅ | 处理配置对比评测 | P11-S10 已新增已应用处理版本对比报告（不重跑配置） | `app/services/evaluation_runner.py`、`app/routers/evaluations.py`、`KnowledgeEvaluationPage.tsx` | 处理版本/配置维度、对比报告 | K-P0-1/K-P0-2 | M |

### 2.4 记忆

| ID | 缺口 | 现状 | 代码入口 | 改动范围 | 依赖 | 规模 |
|---|---|---|---|---|---|---|
| M-P0-1 ✅ | 记忆完整度与使用聚合 | P11-S7 已新增完整度评分与按模型/Agent/项目/会话聚合 | `app/services/memories.py::memory_stats`、`app/routers/memories.py`、`MemoryPage.tsx` | 聚合查询、完整度维度、前端图表 | 无 | M |
| M-P0-2 ✅ | 生命周期策略执行 | P11-S7 已新增单条保留覆盖、每日过期任务与 blocked topic 统一拦截 | `app/services/memories.py`、`memory_extraction.py`、`app/worker.py` | 创建/更新统一拦截、过期清理任务、策略字段 | 无 | M |
| M-P0-3 ✅ | 记忆版本 diff/变化分析 | P11-S7 已新增字段/内容 diff 与风险标记 | `app/services/memories.py`、`app/routers/memories.py`、`MemoryDetailDialog.tsx` | 快照 diff、变化摘要、风险提示 | 无 | S |
| M-P0-4 ✅ | 质量建议广度 | P11-S8 已新增孤儿/关系异常/项目缺口/规则提示 | `app/services/memory_quality.py`、`MemoryQualityPanel.tsx` | 图谱优化、项目补充、规则调整、关系异常 | M-P0-1 | M |
| M-P0-5 ✅ | 更多提取来源 | P11-S8/S8b 已新增项目活动、工作流运行与授权文档来源 | `app/services/memory_extraction.py`、`app/worker.py`、工作流/项目完成钩子 | 项目活动、工作流执行、文档授权提取 | 用户授权与去重 | L |
| M-P0-6 ✅ | 检索过滤维度 | P11-S10 已新增时间/来源/使用场景/关系过滤（列表与选择器） | `app/services/memories.py::select_memories/list_memories`、`app/routers/memories.py` | 时间/关系/场景过滤、查询参数与 UI | 图谱关系 | M |

## 3. P1：体验与生态

### 3.1 Agent

| ID | 缺口 | 现状 | 代码入口 | 改动范围 | 依赖 |
|---|---|---|---|---|---|
| A-P1-1 ✅ | 广场封面、发布者筛选、官方精选组合 | P11-S4 已新增封面、发布者/分类/官方筛选与 facets | `app/models.py`（CustomAgent）、`app/routers/agent_market.py`、`web/src/pages/market` | 封面字段、筛选/排序、审核展示 | 无 |
| A-P1-2 ✅ | Agent 模板创建（从模板起步） | P11-S4 已提供三个模板与原子创建流程 | `app/services/custom_agents.py`、`web/src/pages/studio` | 模板定义、创建流程 | A-P0-2 |
| A-P1-3 | AI Builder 流式状态与多轮上下文增强 | 无生成阶段流、澄清、取消已列 P0 | `app/routers/agent_builder.py`、`StudioBuilderPanel.tsx` | SSE/阶段事件、上下文摘要 | X-P0-4 |
| A-P1-4 ✅ | Agent 附件能力声明与限制 | P11-S12 已新增 `attachments_enabled` 声明、上传/消息校验与 Studio 开关 | `app/services/custom_agents.py`、`app/routers/conversations.py`、`StudioConfigPanel.tsx` | 能力字段、上传/解析开关 | 无 |
| A-P1-5 ✅ | Agent 级运行分析与工作流优化建议 | P11-S11 已新增成功率/耗时/成本/失败码/慢节点与规则建议 | `app/services/custom_agents.py::list_agent_runs`、`app/metrics.py`、`AgentExperiencePage.tsx` | 聚合指标、失败原因、建议 | X-P0-3 |

### 3.2 知识库

| ID | 缺口 | 现状 | 代码入口 | 改动范围 | 依赖 |
|---|---|---|---|---|---|
| K-P1-1 ◐ | 完整处理节点库 | P11-S5 已补文本过滤/增强节点；OCR 节点、格式专用解析、独立全文/混合索引模式仍缺 | `app/services/knowledge/catalog.py`、`pipeline.py` | OCR 节点、格式专用解析、文本处理、全文/混合索引 | K-P0-1/2 |
| K-P1-2 ◐ | 完整检索节点库 | P11-S6 已补多查询与空结果回退；意图识别/分类路由/同义词扩展仍缺 | `app/services/knowledge/retrieval_catalog.py`、`retrieval_pipeline.py` | 新节点、条件分支或回退语义 | K-P0-3 |
| K-P1-3 ✅ | 文档处理结果与解析原文预览 | P11-S11 已新增按页解析原文预览与截断/错误提示 | `web/src/pages/knowledge/KnowledgeChunksTab.tsx`、`app/services/parsing.py` | 解析文本/结构预览、失败定位 | 无 |
| K-P1-4 ✅ | 评估指标补齐：引用准确性、答案忠实度 | P11-S12 已新增引用准确率/召回/F1，并展示忠实度与判分 | `app/services/knowledge/metrics.py`、`app/services/evaluation_runner.py` | 引用校验、答案指标 | 评测平台 |

### 3.3 记忆

| ID | 缺口 | 现状 | 代码入口 | 改动范围 | 依赖 |
|---|---|---|---|---|---|
| M-P1-1 ✅ | 按模型/Agent 的细粒度读取白名单 | P11-S8 已新增 provider/model/agent 白名单 | `app/services/memory_permissions.py`、`MemorySettingsPanel.tsx` | 模型/Agent 白名单、选择器 | 无 |
| M-P1-2 | 记忆关系编辑增强 | 只能创建/删除，不能改类型/依据 | `app/routers/memories.py`、`MemoryDetailDialog.tsx` | PATCH 关系、依据编辑 | 无 |
| M-P1-3 ✅ | 记忆完整度/变化分析 | P11-S8 已新增最近变化与偏好/项目/技术维度统计 | `app/services/memory_quality.py`、`MemoryPage.tsx` | 版本对比、变化摘要 | M-P0-3 |
| M-P1-4 ✅ | 记忆评测与回答效果联动 | P11-S12 已新增有/无记忆 A/B 回答生成与判分 | `app/services/memory_eval.py`、`app/services/rag.py` | A/B 注入对比、回答质量指标 | 评测平台 |
| M-P1-5 ✅ | 记忆反馈闭环 | P11-S11 已新增反馈表/API、排序加成与质量建议 | `app/models.py`、`app/services/memories.py`、`MemoryPage.tsx` | 反馈表、排序权重、质量建议 | 无 |

## 4. P2：高级与依赖外部

| ID | 缺口 | 说明 |
|---|---|---|
| P2-1 | API/云盘/第三方知识数据源 | 需要连接器、凭证管理与网络策略 |
| P2-2 | 多模态知识处理 | 图像/表格/音视频深度理解，依赖模型能力 |
| P2-3 | 知识图谱与实体消歧 | 需要实体识别、关系抽取、图谱存储 |
| P2-4 ✅ | LLM 语义矛盾检测 | P11-S9 已新增显式触发的批量语义矛盾检测，只生成待确认建议；跨分类/自动应用仍不做 |
| P2-5 | 实时协同画布 | 需要 CRDT/WebSocket 与冲突合并 |
| P2-6 | 工作流市场与商业化 | 涉及发布审核、计费、版权，非纯技术 |

## 5. 建议 P11 切片

| 切片 | 范围 | 主要产出 | 依赖 |
|---|---|---|---|
| P11-S1 | 画布基础工程化 + 版本恢复 | X-P0-1、X-P0-2 | 无 |
| P11-S2 | 单节点调试/从节点运行 | X-P0-3 | S1 |
| P11-S3 | AI Builder 控制 | X-P0-4、A-P1-3 | S1 |
| P11-S4 ✅ | Agent 配置与工具生态 | A-P0-1、A-P0-3、A-P1-1/P1-2 | S1 |
| P11-S5 ✅ | 知识处理节点扩展 | K-P0-1、K-P0-2、K-P1-1（部分） | S1 |
| P11-S6 ✅ | 知识检索/多 KB/运行分析 | K-P0-3、K-P0-4、K-P1-2（部分） | S5 |
| P11-S7 ✅ | 记忆仪表盘/生命周期/diff | M-P0-1、M-P0-2、M-P0-3 | 无 |
| P11-S8 ✅ | 记忆提取来源与质量广度 | M-P0-4、M-P0-5（部分）、M-P1-1/P1-3 | S7 |
| P11-S9 ✅ | 高级能力评估 | P2-4 LLM 语义矛盾检测；其余 P2 评估后按需/不做 | S5/S6/S8 |
| P11-S10 ✅ | 剩余 P0 收尾 | A-P0-2/A-P0-4、K-P0-5、M-P0-6 | S9 |
| P11-S11 ✅ | P1 体验闭环 | A-P1-5、K-P1-3、M-P1-5 | S10 |
| P11-S12 ✅ | P1 能力与评测补齐 | A-P1-4、K-P1-4、M-P1-4 | S11 |

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