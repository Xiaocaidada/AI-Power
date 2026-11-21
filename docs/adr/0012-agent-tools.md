# ADR-0012: 多 Agent 与工具调用

- **Status:** Accepted
- **Date:** 2026-11-21
- **Context:** P3 需要可演示的 Agent 场景，同时兼容不一定支持原生 function calling 的本地模型。

## Decision

- **一个 supervisor + 两个专业子 Agent**（`retrieval`、`math`）。supervisor 只持委派工具；子 Agent 各持领域工具且**不能再委派**。
- **provider 无关的 JSON 协议**：每一步只接受一个 JSON 对象：
  - `{"action":"tool","tool":"...","arguments":{...}}`
  - `{"action":"final","answer":"..."}`
  - 解析失败时把整段文本当作最终回答（兼容不遵循协议的小模型）。
- **工具注册表**（`app/tools/`）统一做 Pydantic 参数校验、10s 超时、输出截断与错误码；工具结果以 `<tool_output>` / `<tool_error>` / `<sub_agent_result>` 包裹回填，按不可信数据处理。
- **硬限制**：总步数 ≤8、委派深度 ≤2、单工具超时、每步 LLM 调用前检查配额；全部步数 token 累加到同一条消息。
- **可观测**：SSE 增加 `agent_start` / `agent_end` / `tool_call` / `tool_result`；`traces.agents` 只存 agent/tool/target/耗时/成功/深度，不存参数与输出正文。
- **测试**：用确定性脚本化 provider（D10），不依赖真实模型；真机演示为 best-effort。

## Consequences

- 本地/远端模型都可通过提示词参与工具循环，不绑定 provider 能力。
- 每步缓冲完整 JSON，Agent 回答不是逐 token 流式；最终回答一次性发 `delta`。
- 协议遵循度取决于模型；纯文本兜底保证不会“卡死”。
- 不做 DAG/多 Agent 协作编排，避免范围膨胀。

## Alternatives

- **只支持原生 `tool_calls`**：本地 llama.cpp 模型可能不支持，演示不可控。
- **DAG 工作流引擎**：超出 P3 范围，留 P4。
- **子 Agent 互相委派**：递归与成本不可控，明确禁止。