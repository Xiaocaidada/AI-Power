# TDD Evidence — P3-S1: 多 Agent 工具框架

- **Date:** 2026-11-21
- **Scope:** supervisor + 子 Agent、工具注册表、JSON 工具协议、SSE Agent 事件、trace 工具元数据、前端 Agent 流程展示
- **Source:** [`docs/plan/p3-plan.md`](../plan/p3-plan.md) P3-S1（D1 多 Agent、D10 脚本化 provider）

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 新增 Agent 测试 | `pytest tests/test_agents.py` | **8 passed** |
| 后端全量 | `pytest --cov=app` | **236 passed, 3 skipped，覆盖率 93%** |
| Lint/Format | `ruff check` / `ruff format --check` | 通过 |
| 前端单测 | `npm test` | 18 passed（已排除 `e2e/**`） |
| 类型/构建 | `npm run typecheck` / `npm run build` | 通过 |
| E2E | `npm run test:e2e` | 1 passed（8.0s） |

## 交付

- **工具层**（`app/tools/`）：`ToolSpec`（Pydantic 参数模型 + Pydantic JSON Schema）、`ToolRegistry`（参数校验、超时、输出截断、错误码 `tool_not_found` / `invalid_arguments` / `tool_timeout` / `tool_error`）、`current_time` 工具。
- **Agent 层**（`app/agents/`）：`AgentSpec` / `AgentRegistry`；内置 `supervisor`、`retrieval`、`math`。
- **执行器**（`app/services/agent.py`）：
  - provider 无关 JSON 协议：`{"action":"tool",...}` / `{"action":"final",...}`；无法解析时按纯文本回答（兼容不会遵循协议的本地方案）。
  - supervisor 通过内置工具 `delegate_to_agent` 委派；子 Agent 禁止再委派；深度上限 2、总步数上限 8（`AGENT_MAX_STEPS`）。
  - 每个 LLM 步前检查配额；全部步数 token 累加到同一条消息。
  - 工具结果以 `<tool_output>` / `<tool_error>` / `<sub_agent_result>` 包裹回填，视为不可信数据。
- **SSE 扩展**：`agent_start`、`agent_end`、`tool_call`、`tool_result`（原有事件顺序不变；非 Agent 会话不受影响）。
- **持久化/可观测**：`conversations.agent`；`traces.agents` 记录 agent、tool、target、耗时、成功/失败、深度（不存正文）。
- **前端**：新建会话“多 Agent 模式”开关；对话内折叠展示 Agent 流程与工具耗时；trace 抽屉展示 Agent/工具步骤；中英文案对齐。

## Test Specification（新增 8）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | supervisor 委派 retrieval、retrieval 调工具、supervisor 汇总；SSE 顺序与聚合 usage 正确 | `test_multi_agent_delegates_and_runs_tool` | PASS |
| 2 | 工具异常回填给模型且整轮仍可完成 | `test_agent_tool_error_is_reported_and_run_completes` | PASS |
| 3 | 子 Agent 委派被拒绝（`delegation_not_allowed`） | `test_subagent_cannot_delegate` | PASS |
| 4 | 总步数超限发出 `agent_step_limit` 且消息 failed | `test_agent_step_limit_emits_error` | PASS |
| 5 | 非 JSON 输出按最终回答处理 | `test_plain_text_output_falls_back_to_final_answer` | PASS |
| 6 | `agent` 标记持久化，默认关闭 | `test_conversation_persists_agent_flag` | PASS |
| 7 | 工具参数非法返回 `invalid_arguments` | `test_tool_registry_rejects_invalid_arguments` | PASS |
| 8 | 工具超时返回 `tool_timeout` | `test_tool_registry_times_out` | PASS |

## Known Gaps

- **工具集不完整**：`kb_search` 与 `calculator` 在 P3-S2 实现；当前 `retrieval` / `math` 仅 `current_time` 可用。
- **Agent + 知识库仍走预检索**：带 `kb_id` 的 Agent 会话先按旧逻辑把检索结果放进 system prompt；S2 增加 `kb_search` 后改为由 retrieval 子 Agent 主动检索。
- **Agent 回答非逐 token 流式**：每步缓冲完整 JSON 后再决定下一步，最终回答一次性发 `delta`（`meta/usage/done` 契约不变）。
- **auto 路由不做流中降级**：Agent 会话选首个健康 provider；单步失败不会切换 provider。
- **前端仅有基础展示**：Agent 流程折叠列表，无独立时间线/取消单步。
- **真实模型遵循 JSON 协议的能力未知**：测试使用脚本化 provider（D10），真机演示为 best-effort。
- **trace 不存工具参数与输出正文**，只存元数据。