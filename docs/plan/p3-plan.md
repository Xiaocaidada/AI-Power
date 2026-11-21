# P3 规划：从平台化到 Agent 与应用层

- **Status:** Draft（S1–S6 待用户确认后开工）
- **Date:** 2026-11-21
- **Scope source:** [`PRODUCT-BRIEF.md`](../../PRODUCT-BRIEF.md) §3 P3、[`docs/product/CAPABILITY.md`](../product/CAPABILITY.md)
- **前置:** P2 已完成（2026-11-21），见 [`p2-plan.md`](./p2-plan.md)、[`p2-s6-hardening.md`](../tdd/p2-s6-hardening.md)

## 1. P3 目标

| 能力 | 完成标志 |
|---|---|
| Agent / 工具调用 | 至少 1 个可演示 Agent 场景：模型自行调用 `kb_search` 检索知识库、`calculator` 计算，多步循环在 SSE 中可见，回答带真实引用 |
| Prompt 管理 | workspace 级模板：创建、不可变版本、变量渲染预览；会话可绑定某个版本并复现 |
| 成本面板 | usage_events 写入价格快照；按天/模型/Provider 汇总成本，与 token 用量一致 |
| 管理后台 | 平台管理员可查看用户/workspace/用量、启用/禁用模型；管理员操作写审计日志 |
| 开放 API | OpenAPI 文档补齐示例与错误契约；`curl`/Python quickstart 用 API Key 可跑通流式与非流式调用 |
| 阶段验收 | 3 分钟 demo：Agent 调工具回答并引用 → 切换 Prompt 模板 → 成本面板对账 → 管理员禁用模型后广场消失 → 脚本调通开放 API |

P3 的目标是**可演示的产品纵深**，不是运营级计费系统。

## 2. 现状与差距

已完成（P2）：workspace 多租户、模型目录与 `auto` 路由/降级、workspace/Key 配额、traces、平台前端、分页、SQL 用量聚合、Playwright CI。

P3 必须补的差距：

| 差距 | 现状 | 影响 |
|---|---|---|
| 无工具调用 | 会话只做 `provider.stream_chat(history, model)` | 无法回答"先查资料再计算"的多步问题，面试卖点缺失 |
| Prompt 写死 | RAG system prompt 在 `app/services/rag.py` 中硬编码 | 无法管理、版本化、按场景复用，改了无法回溯 |
| 无成本 | 只有 token 计数，`model_catalog` 的价格未参与结算 | 无法回答"这个月花了多少钱、哪个模型最贵" |
| 无管理端 | 无平台管理员角色与后台 | 模型启停只能改数据库/种子脚本，无法演示运营能力 |
| 开放 API 不完整 | 有 `X-API-Key` 与自动 OpenAPI | 缺错误码契约、示例与稳定说明，外部接入成本高 |

## 3. 关键决策（待确认）

| # | 决策 | 建议 | 备选 |
|---|---|---|---|
| D1 | Agent 形态 | **单 Agent + 工具循环**（最多 5 步），SSE 增加 `tool_call` / `tool_result`；不做多 Agent、不做 DAG | 工作流编排引擎（范围过大，留 P4） |
| D2 | 工具协议 | **provider 无关的 JSON 工具协议**（提示词声明工具 + 解析模型输出）；检测到 provider 支持原生 `tool_calls` 时走原生，内部统一 `ToolCall` 结构 | 只支持原生 function calling（本地 llama.cpp 模型可能不支持，演示会挂） |
| D3 | 内置工具 | `kb_search`（复用检索、workspace 隔离）、`calculator`（AST 白名单，禁止 `eval`）、`current_time`；`http_fetch` 仅在配置 allowlist 且默认关闭时提供 | 全开放 HTTP 工具（SSRF 风险，不建议） |
| D4 | Prompt 管理 | **workspace 级模板 + 不可变版本**；会话绑定 `prompt_version_id`，历史可复现 | 全局模板（无法按团队定制） |
| D5 | 成本口径 | **写入时快照价格**：`usage_events` 增加 `input_price` / `output_price` / `cost`，来自当时 catalog；缺价记 0 并标记 `unpriced` | 查询时 join 现价（历史会漂移，不能对账） |
| D6 | 管理员 | 复用 `users.role = "admin"` 作为**平台管理员**，与 workspace `owner` 区分；非管理员访问 `/admin/*` 返回 404；管理员操作写 `audit_logs` | 仅结构化日志（不可查询、不可演示审计） |
| D7 | 开放 API 版本 | **不引入 `/v1` 前缀**（避免全局破坏性改动），冻结现有契约、补齐错误码文档与示例 | 迁移到 `/api/v1`（收益低、成本高） |
| D8 | Agent 配额 | 工具循环的**每次 LLM 调用都累积 token 到同一条 message 用量**，每步前检查配额，步数上限 5，防止绕过 | 只按最终回答计量（会低估成本、可被滥用） |
| D9 | P2 欠账 | P3-S6 顺带补：前端"加载更多"分页、429 倒计时、API Key 轮换提示；暗色主题仍为可选 | 全部推迟（欠账继续滚） |

> **待用户确认（2026-11-21）**：D1–D9 按建议执行，或指出要改的项。确认前不写代码。

## 4. 切片与顺序

原则：先工具框架与安全，再 Prompt 与成本，再管理端，最后开放 API 与收口；每片可独立演示。

### P3-S1 Agent 工具框架（约 1–1.5 周）

- `app/tools/`：`ToolSpec(name, description, parameters_schema, handler)`、`ToolRegistry`、`ToolContext(workspace, user, session, redis)`。
- Agent 循环（放在 `app/services/agent.py`，不塞进 router）：
  1. 组装带工具声明的消息；
  2. 模型输出解析为 `ToolCall` 或最终回答；
  3. 校验参数 → 执行工具 → 观察结果以不可信数据包裹回填；
  4. 最多 `AGENT_MAX_STEPS=5`，每步检查配额与超时。
- SSE 契约扩展（向后兼容）：新增 `tool_call`、`tool_result`，出现在 `meta` 之后、`delta` 之前或之间；现有前端忽略未知事件不报错。
- `traces` 增加工具摘要（JSON：工具名、耗时、成功/失败），失败带 `tool_error` 错误码。
- 会话创建支持 `agent: bool` 与可选 `tools: [..]`，默认关闭；消息 finalize 时累加全部步数 token。
- 验收：`agent=true` 的会话问"知识库里 X 是什么？帮我算一下 Y"，SSE 可见工具调用，回答带引用，trace 记录工具耗时。

### P3-S2 内置工具与安全（约 1 周）

- `kb_search`：调用现有 `retrieve_chunks`，强制当前 workspace + 会话 `kb_id`，返回 chunk 摘要（截断），引用随最终回答持久化。
- `calculator`：AST 白名单（数字、四则、括号、幂、有限函数），拒绝属性访问/导入/超长表达式。
- `current_time`：UTC + 指定时区（白名单）。
- 工具参数用 Pydantic 校验；单工具超时（默认 10s）、输出上限（默认 4k 字符）；异常转成 `tool_result(error=...)` 回给模型，不中断整个流。
- 可选 `http_fetch`：仅当 `TOOL_HTTP_ALLOWLIST` 非空时注册，校验 scheme/域名/IP（拒绝私网与重定向到私网）。
- 测试：跨 workspace 的 `kb_search` 不可见；`calculator` 拒绝 `__import__`、`().__class__`、超长表达式；超时/步数上限；工具失败仍产出回答。

### P3-S3 Prompt 模板（约 1 周）

- 表：`prompt_templates(id, workspace_id, name, description, created_by, created_at)`、`prompt_versions(id, template_id, version, system_prompt, variables, created_at)`；版本只增不改。
- API：模板 CRUD、版本列表/创建、`POST /prompt-templates/{id}/render`（变量校验 + 预览）。
- 会话绑定 `prompt_version_id`；非 Agent 与 Agent 都使用模板（无模板时回退现有默认 prompt）。
- 前端：模板列表/编辑器/变量预览；新建会话时选择模板。
- 验收：模板含 `{{tone}}`，渲染替换正确；会话历史回放显示所用版本；删除模板不影响已绑定会话。

### P3-S4 成本面板（约 1 周）

- 迁移：`usage_events` 增加 `input_price`, `output_price`, `cost`, `unpriced`。
- 写入：finalize 时按 `(provider_id, model)` 查 `model_catalog` 快照价格；`cost = prompt_tokens/1e6*input_price + completion_tokens/1e6*output_price`；查不到记 0 + `unpriced=true`。
- API：`GET /usage/cost?from&to&group_by=day|model|provider`，返回 buckets + `total_cost` + `unpriced_requests`。
- 前端：成本卡片与趋势图（复用 Recharts），标注未定价模型。
- 测试：成本算式、改价后历史不变、workspace 隔离、NULL token 记 0。

### P3-S5 管理后台（约 1–1.5 周）

- `require_admin` 依赖（`users.role == "admin"`），非管理员一律 404。
- 管理员脚本：`scripts/grant_admin.py <email>`（无默认管理员/密码）。
- API：用户列表（分页）、workspace 列表与成员、全局用量概览、模型启用/禁用（复用 `model_catalog.enabled`）。
- `audit_logs(id, actor_user_id, action, target_type, target_id, detail, created_at)`；管理员写操作落库；worker 清理 90 天前记录（可配置）。
- 前端：`/admin` 页面组（仅管理员导航可见）：用户、workspace、模型管理、全局用量。
- 验收：禁用模型后 `/models` 与 `auto` 路由立即排除，广场不可见；非管理员访问 404；审计记录可查。

### P3-S6 开放 API 与收口（约 1 周）

- OpenAPI 补齐：tags、summary/description、错误响应模型、示例；`/docs` 可用。
- `docs/api/quickstart.md`：注册/登录、上传文档、流式对话（curl + Python `httpx`）、错误码表、配额头说明。
- 错误契约文档：`unauthorized`、`not_found`、`quota_exceeded`、`no_provider_available`、`provider_failed_after_start`、`tool_*` 等。
- 前端欠账：会话/文档/trace "加载更多"、429 倒计时、API Key 轮换提示；暗色主题可选。
- ADR：0012（Agent 与工具协议）、0013（Prompt 版本化）、0014（成本快照）、0015（管理后台与审计）。
- README/CLAUDE 更新；P3 TDD 证据归档。

## 5. 排期（约 4–6 周）

| 顺序 | 切片 | 预估 |
|---|---|---|
| 1 | P3-S1 Agent 框架 | 1–1.5 周 |
| 2 | P3-S2 工具与安全 | 1 周 |
| 3 | P3-S3 Prompt 模板 | 1 周 |
| 4 | P3-S4 成本面板 | 1 周 |
| 5 | P3-S5 管理后台 | 1–1.5 周 |
| 6 | P3-S6 开放 API 与收口 | 1 周 |

## 6. P3 明确不做

- 真实支付/计费/发票、充值与退款。
- 工作流 DAG/可视化编排、多 Agent 协作（P4 候选）。
- 复杂 RBAC、SSO、SCIM、组织层级。
- 公网、HTTPS、CDN（保持局域网，除非用户另行要求）。
- 微调/训练、自建向量库或推理引擎。
- 移动端 App。

## 7. 风险与对策

| 风险 | 对策 |
|---|---|
| 工具循环拖慢响应、放大成本 | 步数上限 5、单工具超时 10s、每步配额检查、trace 记录 |
| 本地模型不会调工具 | provider 无关 JSON 协议 + 原生 tool_calls 双通道；模板给 few-shot 示例 |
| 工具结果注入（间接提示注入） | 工具输出视为不可信数据，包裹标签并声明"非指令"；工具只能由注册表执行 |
| `calculator` 代码执行 | AST 白名单，禁 `eval`/导入/属性访问；恶意输入测试 |
| 成本口径漂移 | 写入时快照价格；历史不可变；未定价显式标记 |
| 管理员越权 | `role=admin` 校验，非管理员 404；写操作审计；脚本授权不设默认账号 |
| 范围膨胀 | 每片独立演示；DAG/多 Agent 明确不进 P3 |

## 8. P3 完成定义（DoD）

1. 至少 1 个 Agent 场景可演示：多步工具调用、SSE 可见、回答带引用、trace 记录工具耗时。
2. Prompt 模板支持版本化、变量渲染，会话绑定版本且可回溯。
3. 成本面板数字与 token 用量 × 快照价格一致；改价不影响历史。
4. 管理员可启停模型并看到即时生效；审计日志可查；非管理员 404。
5. OpenAPI 文档 + quickstart 中被 API Key 调通（流式与非流式至少各一次）。
6. 前后端测试通过，覆盖率 ≥ 80%；至少 1 条 Agent 相关 Playwright；CI 绿灯。
7. 文档：ADR-0012/0013/0014/0015、P3 TDD 证据、README 更新。

## 9. 门禁

- 本计划需用户确认 D1–D9 后才进入编码。
- 与 P1/P2 相同：**每片编码前需用户明确批准**；每片完成产出 TDD 证据并合回 `main`。
- 未列入本计划的 P4 功能不得提前实现。