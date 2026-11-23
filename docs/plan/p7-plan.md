# P7 特色功能规划

## 1. 目标

在现有 P6 能力上新增三个独立工作台，复用 Provider 适配、模型访问控制、SSE、用量账本、Markdown 渲染与设计体系：

1. 多模型并行对话（Model Arena）
2. AI 模型评测中心（Model Evaluation Center）
3. AI Prompt 实验室（Prompt Lab）

不在本次范围内做无关重构；现有检索评测平台继续保留。

## 2. 现状与可复用能力

| 能力 | 现有实现 | P7 复用方式 |
| --- | --- | --- |
| Provider / 用户模型 | `get_scoped_registry`、`ensure_model_capability`、Provider Hub | 所有新功能按当前用户/工作区解析模型 |
| 流式输出 | `LLMProvider.stream_chat`、`ChatMessage`、SSE 解析 | 抽象共享的多模型流式执行器 |
| 用量/成本 | `usage_events`、价格快照、预算、指标 | 新增来源 `arena/prompt_lab/model_eval` |
| 异步任务 | Arq、workflow run 取消/重试模式 | 模型评测批量执行 |
| Prompt 版本 | `prompt_templates` + 不可变 `prompt_versions` | 扩展 User Prompt、变量定义与测试快照 |
| 检索评测 | `eval_datasets/questions/runs/items` | 保留，不混入模型评测 |

关键差异：现有 `usage_events` 只能按 `message_id` / 节点 / 步骤做幂等，新功能需要通用 `source_ref_id`；现有 Provider 只有流式接口，非流式模型需要显式处理策略。

## 3. 共享基础改造（P7-S0）

### 3.1 用量账本

- `usage_events` 新增 `source_ref_id UUID NULL UNIQUE`，用于 Arena 回答、Prompt 测试输出、模型评测条目的幂等写入。
- 新增来源常量：`arena`、`prompt_lab`、`model_eval`。
- `GET /usage/summary|cost|recent`、预算、指标、前端来源筛选同步支持新来源。
- 所有新功能写入一条账本对应一次真实模型调用；AI 评审调用单独一条。

### 3.2 共享多模型执行器

- 后端 `app/services/model_stream.py`：
  - 输入：provider、model、messages、generation opts、`source`、`source_ref_id`。
  - 输出：SSE 事件 `meta → delta* → usage → done/error`，记录首 token 时间、总耗时、token、成本。
  - 客户端断开时取消上游请求；失败只影响当前模型。
- 前端 `useModelStreams` hook：管理 N 路 AbortController、每路状态（waiting/streaming/success/failed/cancelled）、单路停止、全部停止、重试。
- 共享模型选择器：支持平台模型 + 个人模型、2–4 个、能力校验、Provider 展示。

### 3.3 能力与计费规则

- 统一标注：Provider 返回的 token/费用为实际值；按价格快照计算的费用标“估算”；无法获取时显示“暂不可用”。
- 当前 Provider 适配器是流式接口；对标记为非流式的模型，服务端消费完整流后只向 UI 推送最终内容（或后续补 `complete()` 适配），不虚构流式能力。
- 并发上限：Arena/Prompt Lab 每次最多 4 路；评测任务默认并发 3、可配 1–5；每路调用均受配额与预算约束。

## 4. 01 Model Arena

### 4.1 数据模型

- `arena_rounds`
  - `id, workspace_id, user_id, prompt, generation_settings, blind, revealed_at, vote_response_id, vote_reason, created_at, deleted_at`
- `arena_responses`
  - `id, round_id, position, provider_id, model, status, content, prompt_tokens, completion_tokens, cost, ttft_ms, total_ms, error_code, attempt, created_at`
  - 唯一约束 `(round_id, position)`
- 盲测身份只存于 `arena_responses`；未揭示前 API 不返回真实 `provider_id/model`，只返回 A/B/C/D。

### 4.2 API / SSE

- `POST /arena/rounds`：校验 2–4 个可访问模型、去重、能力 `chat`，创建 round + 响应占位。
- `GET /arena/rounds`、`GET /arena/rounds/{id}`、`DELETE /arena/rounds/{id}`。
- `POST /arena/rounds/{id}/responses/{response_id}/stream`：单路 SSE；前端并行打开 2–4 路。
- `POST /arena/rounds/{id}/responses/{response_id}/cancel`：标记取消，生成器在 chunk 边界退出。
- `POST /arena/rounds/{id}/responses/{response_id}/retry`：重置该回答并重新流式生成，`attempt += 1`。
- `POST /arena/rounds/{id}/vote`：选择最满意回答 + 可选理由；投票后可揭示。
- `POST /arena/rounds/{id}/reveal`：返回真实模型映射。
- SSE：`meta`（response_id、盲测标签、是否揭示）、`delta`、`usage`、`done`（ttft/total/tokens/cost/estimated）、`error`。

### 4.3 页面

- `/arena`：模型选择、公共参数（temperature/max_tokens）、问题输入、盲测开关、历史列表。
- `/arena/:id`：2–4 列动态布局，每列独立滚动；列内状态、停止、重试、复制；底部投票与揭示。
- 历史记录：问题、参与模型、时间、胜负、查看/删除/重新发起。
- 导航：Work 组新增“模型擂台”。

### 4.4 规则

- 单模型失败不影响其他列；停止单路不停止其他路。
- 一轮至少 2 个、最多 4 个模型；相同 Provider+Model 不可重复。
- 盲测投票前不得在 API/前端状态中泄露真实模型。
- 失败可单独重试；重试是新一次真实调用，写新账本。

## 5. 02 Prompt Lab

### 5.1 模板与版本扩展

- `prompt_templates` 新增：
  - `scope`（`workspace|platform`），`workspace_id` 对平台模板可为 NULL，`created_by` 保留。
- `prompt_versions` 新增：
  - `user_prompt`（默认空）
  - `variable_definitions` JSON：`[{name, description, required, default}]`
  - `parameters` JSON（默认生成参数）
- 变量识别覆盖 System + User Prompt；变量只做纯文本替换，禁止表达式/脚本执行。
- 版本不可变；“恢复”创建新版本，不修改历史；支持版本 diff 与复制版本为新模板。
- 平台模板由管理员维护（`/admin/prompt-templates`），用户只读；用户模板按 workspace 隔离。
- 初始平台模板：代码分析、代码生成、文档总结、文本润色、数据分析、结构化提取、学习辅导、内容创作。

### 5.2 测试实验

- `prompt_experiments`
  - `id, workspace_id, user_id, template_id, version_id, system_prompt_snapshot, user_prompt_snapshot, variables, parameters, rating, note, created_at, deleted_at`
- `prompt_experiment_outputs`
  - `id, experiment_id, provider_id, model, status, content, prompt_tokens, completion_tokens, cost, ttft_ms, total_ms, error_code, created_at`
- `POST /prompt-lab/preview`：渲染并返回最终 System/User Prompt、缺失变量。
- `POST /prompt-lab/experiments`：快照模板与变量，创建 1–4 个模型输出。
- `POST /prompt-lab/experiments/{id}/outputs/{output_id}/stream`：复用共享多流执行器。
- `GET /prompt-lab/experiments`、详情、删除、重新执行（基于快照创建新实验）。
- `PATCH /prompt-lab/experiments/{id}`：记录效果评价与备注。
- 历史记录展示当时的 Prompt 全文、变量值、参数、模型与指标，不随模板修改变化。

### 5.3 页面

- `/prompt-lab`：模板库、搜索/分类/收藏、创建/复制/删除。
- 编辑器：System/User Prompt、变量定义、默认参数、版本历史与 diff。
- 测试区：模型多选、参数、变量填写、预览、运行；结果 1–4 列并排，独立停止/重试。
- 历史区：查看/对比/重新执行/删除。
- `/settings/prompts` 保留为入口或跳转到 Prompt Lab，避免两套模板管理。

## 6. 03 Model Evaluation Center

### 6.1 数据模型（与检索评测分开）

- `model_eval_datasets`：`workspace_id, created_by, name, description, created_at, updated_at, deleted_at`
- `model_eval_questions`：`dataset_id, question, reference_answer, scoring_criteria, expected_keywords JSON, regex, order`
- `model_eval_runs`：`workspace_id, user_id, dataset_id, name, status, config JSON, progress_total/done/failed/running, current_model, started_at, finished_at, error_code`
- `model_eval_items`：`run_id, question_id, provider_id, model, question_snapshot, reference_snapshot, answer, status, error_code, prompt/completion tokens, cost, ttft_ms, latency_ms`
- `model_eval_scores`：`item_id, method(manual|rule|ai), score, passed, reason, scorer_user_id, judge_provider_id, judge_model, created_at`
- 唯一约束：`(run_id, question_id, provider_id, model)`；评分唯一 `(item_id, method, scorer_user_id)`。

### 6.2 执行

- `POST /model-eval/runs` → Arq `run_model_eval_job`，按 `question × model` 生成条目，默认并发 3（1–5）。
- 每个条目独立调用、独立失败；任务级取消在条目边界检查；单条失败重试；整体重新执行创建新 run。
- 每条回答写一条 `usage_events`（`source='model_eval'`, `source_ref_id=item.id`）。
- AI 评审调用写独立账本（`source_ref_id=score.id`），并记录评审模型。

### 6.3 评分

- 规则：关键字/包含/正则/格式，产出 `passed` 与理由。
- 人工：逐条打分 + 理由 + 优缺点。
- AI 评审：使用用户可访问模型，输入参考答案/评分标准/回答，输出结构化分数与理由；评审失败只标记该评分失败。
- 不同评分方式分开统计，不把未评分数据计入正确率。

### 6.4 指标与报告

- 质量：规则通过率、AI 均分、人工均分、完成/失败数、逐题得分。
- 性能：平均/首 token 延迟、输入/输出 token、平均 token、估算成本、成功率。
- 报告：任务信息、数据集快照、模型列表、逐题对比、表格 + 图表、导出 JSON/CSV。
- 历史：列表/详情/复制配置/删除/重跑。

### 6.5 页面

- `/evaluation` 改为评测中心入口，保留现有“检索评测”，新增“模型评测”页签。
- 数据集管理、创建评测、任务详情（实时进度）、报告、单题多模型对比。
- 不做静态 mock；所有指标来自实际执行记录。

## 7. 切片顺序

| 切片 | 内容 | 依赖 |
| --- | --- | --- |
| P7-S0 | 账本 `source_ref_id`、新来源、共享多流执行器、模型多选组件、用量 UI | 无 |
| P7-S1 | Model Arena 数据/API/SSE/页面/盲测/历史 | S0 |
| P7-S2 | Prompt Lab 模板/版本/变量/实验/多模型/历史 | S0、复用 S1 多流 |
| P7-S3 | 模型评测数据集、任务执行、进度、取消、失败重试 | S0 |
| P7-S4 | 规则/人工/AI 评分、指标、报告、导入导出 | S3 |
| P7-S5 | 导航/文档/E2E/真实模型冒烟/收口 | S1–S4 |

每个切片完成后执行测试与构建；不合并未经用户确认的功能范围。

## 8. 安全与数据规则

- 所有资源 workspace/user 隔离，跨用户/跨工作区 404。
- 模型选择必须经过 scoped registry 与能力校验；禁止仅凭 provider/model 字符串越权。
- 盲测未揭示前服务端不返回真实模型。
- 平台 Prompt 模板只读；管理员 CRUD 需要 admin。
- 历史快照不可被模板编辑覆盖。
- 不日志输出完整 Prompt/回答/文档；用量只记录 token、成本与来源。
- 取消请求后不继续计费；已产生的 usage 事件保留。
- 费用估算明确标注，不冒充 Provider 实付。

## 9. 测试与验收

- 后端：fake provider 覆盖并行隔离、单路失败/取消/重试、SSE 指标、账本来源与幂等、盲测泄露、用户隔离、变量缺失、版本快照、评测评分分离、任务取消、报告聚合。
- 前端：Vitest 覆盖多流状态、盲测揭示、变量校验、评分表单；Playwright 覆盖 Arena 对比、Prompt 多模型测试、评测任务进度。
- 真实冒烟：本地 Qwen + DeepSeek（或两个本地模型）各跑一轮 Arena；Prompt Lab 多模型；评测小数据集 2 模型。
- 构建/类型检查/全量后端测试。

## 10. 待确认决策

1. **Arena 入口命名**：建议 `/arena`，导航名“模型擂台”。
2. **评测中心入口**：建议在 `/evaluation` 内增加“检索评测 / 模型评测”页签，而不是新增独立顶级路由。
3. **Prompt Lab 与现有 Prompt 页面**：建议 `/prompt-lab` 作为完整工作台，`/settings/prompts` 仅保留跳转入口。
4. **非流式模型**：当前适配器只有流式接口；v1 建议服务端聚合后一次性推送，UI 标注“非流式”，后续再补 `complete()`。
5. **Arena 重试语义**：建议覆盖该回答的最新结果并 `attempt+1`，不保留每次失败草稿；账本保留每次真实调用。
6. **投票语义**：建议每轮一个“最满意回答” + 每个回答可选有帮助/无帮助。

## 11. 风险

- 4 路并发 SSE 受浏览器连接数与 Provider 限流影响；需服务端并发上限与前端串行降级策略。
- 现有 Provider 抽象是流式接口，非流式能力需要明确适配策略。
- 模型评测批量调用成本与限流风险最高，必须默认低并发并显示预算影响。
- Prompt 平台模板涉及 `workspace_id` 可空与权限查询改造，需迁移兼容现有模板。
- 盲测泄露、AI 评审与生成结果混淆是主要业务风险，需在 API 与 UI 双层隔离。