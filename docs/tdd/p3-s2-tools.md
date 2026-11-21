# TDD Evidence — P3-S2: 内置工具与安全

- **Date:** 2026-11-21
- **Scope:** `kb_search`、`calculator`、工具错误契约、Agent 检索引用回传、工具安全边界
- **Source:** [`docs/plan/p3-plan.md`](../plan/p3-plan.md) P3-S2（D3 工具集、D10 脚本化 provider）

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 新增工具测试 | `pytest tests/test_agent_tools.py` | **15 passed** |
| Agent 相关 | `pytest tests/test_agents.py tests/test_agent_tools.py` | **23 passed** |
| 后端全量 | `pytest -q` | **251 passed, 3 skipped** |
| Lint/Format | `ruff check` / `ruff format --check` | 通过 |

## 交付

- **`kb_search`**（`app/tools/kb_search.py`）：
  - 复用 `retrieve_chunks`，强制 `workspace_id` + 会话 `kb_id` 双重过滤（跨 workspace 返回空）。
  - 输出按 `AGENT_TOOL_OUTPUT_MAX_CHARS` 预算裁剪，单条正文最多 800 字符。
  - 返回带编号的引用条目；真正进入输出的 chunk 才写入 `ToolContext.citations`（按 chunk 去重、保持编号一致）。
  - 无知识库 → `no_knowledge_base`；embedding 不可用 → `retrieval_failed`。
- **`calculator`**（`app/tools/calculator.py`）：
  - AST 白名单：数字常量、`+ - * / // % **`、一元正负；拒绝调用、属性访问、名称、下标等。
  - 限制：表达式 ≤200 字符、AST ≤50 节点、指数绝对值 ≤12、结果绝对值 ≤1e12。
  - 除零 → `calculation_error`；其余非法 → `invalid_expression`；整数结果不带 `.0`。
- **工具错误契约**：新增 `ToolError(code, message)`，`ToolRegistry` 原样映射错误码，其余异常仍为 `tool_error`。
- **Agent 引用链路**：Agent 会话不再做发送前预检索；`kb_search` 收集的引用在流结束前以 `citation` SSE 发出，并随助手消息持久化（历史回放可见）。
- **工具挂载**：`retrieval` → `kb_search` / `current_time`；`math` → `calculator`；supervisor 只持委派工具。

## Test Specification（新增 15）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | retrieval 子 Agent 调 `kb_search`，工具结果、citation 事件与持久化引用一致 | `test_retrieval_agent_searches_kb_and_persists_citations` | PASS |
| 2 | 无知识库时返回 `no_knowledge_base` 且整轮仍完成 | `test_kb_search_without_knowledge_base_returns_typed_error` | PASS |
| 3 | `kb_search` 受 workspace 约束，读不到其他租户的 chunk | `test_kb_search_is_scoped_to_the_active_workspace` | PASS |
| 4–7 | 四则、幂、括号、一元负号结果正确 | `test_calculator_evaluates_safe_expressions`（4 参数） | PASS |
| 8–13 | 导入、属性、调用、名称、超大指数、超长表达式被拒绝 | `test_calculator_rejects_unsafe_expressions`（6 参数） | PASS |
| 14 | 除零返回 `calculation_error` | `test_calculator_reports_division_by_zero` | PASS |
| 15 | math 子 Agent 通过 `calculator` 计算并汇总 | `test_math_agent_uses_calculator` | PASS |

## Known Gaps

- **`http_fetch` 未实现**：按 D3 只在 allowlist 下启用；本片未注册该工具（默认关闭即不存在）。
- **kb_search 结果去重有限**：同一 chunk 重复检索复用引用编号，但没有多查询融合/重排。
- **引用在流末尾统一发出**：不是工具执行瞬间推送；前端在 `done` 前即可收到。
- **工具输出预算**：按字符估算，非 token；超长 chunk 截断可能丢失尾部信息。
- **真实模型行为未验证**：仍以脚本化 provider 为主（D10），本地模型遵循 JSON 协议与工具选择为 best-effort。
- **calculator 仅支持算术**：无函数、变量、单位换算。