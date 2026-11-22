# P6 规划：用户 Provider Hub、模型广场与平台门户

- **Status:** In progress（P6-S1、S2 已完成，2026-11-23）
- **Scope source:** `拓展增强.txt`（用户需求）+ P5 已完成能力
- **前置:** P0–P5 已完成；P5 测试范围按用户要求缩小

## 1. P6 目标

P5 解决“质量、开放平台、成本、长任务”，P6 解决“**用户自带模型、模型发现、首页门户、项目化工作区**”。判断标准不是页面数量，而是形成闭环：

> 用户配置 Provider → 系统/个人模型广场发现模型 → 首页直接体验 → 在项目/会话/知识库/Agent 中持续使用

## 2. 已确认决策

| # | 决策 |
|---|---|
| D1 | 首页允许未登录访问；需要登录的功能跳转登录页 |
| D2 | **公共模型广场**展示系统支持的模型提供商与模型，不要求用户先配置 API Key |
| D3 | **个人/团队模型广场**只展示用户/团队自己配置的 Provider 所提供的模型（两个广场，数据源不同） |
| D4 | Provider 配置默认个人私有，可显式共享给 workspace；Key 加密存储、只写不读 |
| D5 | 第一期 Provider 协议：OpenAI-compatible + 自定义 Endpoint/本地部署；原生 Anthropic/Gemini 等通过 Adapter 后补 |
| D6 | 聊天附件/图片理解等多模态能力放 P6-B，不在 P6-A 硬塞 |
| D7 | 项目与知识库支持多对多关联 |
| D8 | 保留现有 workspace 租户/配额/用量/审计模型，不做企业级 RBAC/SSO |

## 3. 目标数据模型（新增）

| 表 | 作用 |
|---|---|
| `provider_configs` | 用户/workspace Provider：类型、Endpoint、加密 Key、状态、共享标记 |
| `provider_models` | 某个 Provider 下同步/手填的模型与能力标签 |
| `market_models` | 公共模型广场展示目录（介绍、分类、能力、输入/输出、推荐/新发布、排序） |
| `announcements` / `notifications` | 公告与用户通知、已读状态 |
| `home_placements` | 首页 Banner/推荐/广告/活动卡片与排序 |
| `projects` + 关联表 | 项目、项目会话、项目知识库、项目文件 |
| `agents` | 自定义 Agent 配置（角色、模型、KB、工具） |
| `prompt_favorites` | 个人提示词收藏/分类（辅助） |

> 不复用 `model_catalog` 硬塞展示字段：`model_catalog` 继续承担平台路由与价格；`market_models` 承担公共展示元数据；用户 Provider 模型放 `provider_models`。

## 4. 切片

### P6-S1 用户 Provider Hub — **已完成（2026-11-23）**

- 表：`provider_configs`、`provider_models`。
- 加密：Fernet（独立 `PROVIDER_SECRET_KEY`，dev 回退 JWT）；API 只返回掩码提示。
- API：CRUD、测试连接、同步模型、手动加模型、启停模型。
- 动态 Registry：平台 Provider + 当前用户/共享 Provider 合并；chat/agent/workflow/协作按请求解析配置。
- 前端 `/settings/providers`：新增/编辑/删除、测试、同步、模型列表与能力标签。
- 验收：用户配置的 OpenAI-compatible Provider 可在对话中选择并流式调用；Key 不回显；跨用户不可见。

> **完成证据**：[`docs/tdd/p6-s1-provider-hub.md`](../tdd/p6-s1-provider-hub.md)、[`docs/api/provider-configs.md`](../api/provider-configs.md)。真实本机 Endpoint 测试/同步/对话通过。

### P6-S2 模型广场与能力 — **已完成（2026-11-23）**

- `market_models` + 公共目录 API（无需登录）；搜索、筛选、排序、详情。
- 个人/团队模型广场：聚合 `provider_models`，展示可用状态与配置引导。
- 能力校验：`chat/stream/tools/vision/embedding/rerank/structured`；不支持的功能禁用。
- 模型详情 → 立即体验（已配置则直连；未配置则引导 Provider 配置）。
- KB 的 Embedding/Reranker 可选择用户 Provider 与模型。

> **完成证据**：[`docs/tdd/p6-s2-model-marketplace.md`](../tdd/p6-s2-model-marketplace.md)、[`docs/api/model-marketplace.md`](../api/model-marketplace.md)。

### P6-S3 首页门户与运营内容

- 公开首页：顶部导航、中央大输入框、模型/Provider 选择、推荐区、底部入口。
- `announcements`/`notifications`/`home_placements` 与管理员 CRUD、发布/下线/排序/定时。
- 未登录可浏览；点击对话/收藏等功能跳登录。
- 管理员概览补充内容/公告/Provider 统计。

### P6-S4 项目与聊天工作区

- `projects` + 会话/KB/文件关联；项目指令、默认模型、默认 Provider。
- 会话：搜索、置顶、重命名、归档/取消归档、移动项目、批量操作。
- 聊天：模型/Provider 切换、参数配置、重新生成、消息反馈、附件入口（附件能力 P6-B）。
- 项目内新会话继承项目配置。

### P6-S5 Agent 与插件

- Agent 广场与自定义 Agent：角色指令、默认模型、KB、工具、范围、执行记录。
- 插件 v1：注册表、配置、权限、敏感操作确认、外部 HTTP 工具（SSRF/超时/白名单）。
- 复用现有 AgentRunner、工具协议、SSE、trace、usage。

### P6-S6 辅助与收口

- 个人控制台聚合、提示词收藏/分类、文件中心、全局搜索。
- 外部 Key 用量说明：平台统计与第三方实际计费分离。
- 文档、演示、部署复核；按用户要求控制测试规模，但保留 Provider 加密/隔离/能力校验测试。

## 5. P6-A / P6-B

**P6-A（先做）:** S1 → S2 → S3 → S4  
**P6-B（后做）:** S5 Agent/插件 → S6 辅助；聊天附件/多模态与插件外部工具再单独评估安全面。

## 6. 明确不做

- 企业级 RBAC/SSO/组织层级、真实支付/计费。
- 原生 Anthropic/Gemini 等全部协议（Adapter 后补）。
- 拖拽画布、移动端 App、跨集群部署。
- 通过猜测第三方账单金额冒充“精确成本”。

## 7. 门禁

- 每个切片 coding 前需用户批准。
- Provider Key 加密/不回显/跨用户隔离、能力禁用、项目/KB 隔离属于安全底线，不因“测试跳过”而省略。
- 新功能不得破坏现有 workspace 404/配额/用量/审计语义。