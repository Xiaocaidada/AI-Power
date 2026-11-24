# P11-S12：P1 能力与评测补齐

日期：2026-11-24

## 范围

- A-P1-4：Agent 附件能力声明与限制。
- K-P1-4：引用准确性与答案忠实度指标。
- M-P1-4：记忆评测与回答效果联动。

## A-P1-4

- `custom_agents.attachments_enabled`（迁移 `b3c4d5e6f7a8`，默认 true 兼容旧 Agent）。
- 附件上传：自定义 Agent 会话禁用附件时返回 `422 agent_attachments_disabled`；Agent 模式图片仍返回 `image_agent_unsupported`。
- 消息发送：已关联附件（含未绑定后认领）也执行同一能力校验。
- Agent Studio 配置新增“允许附件”开关；发布快照/复制保留该字段。

边界：图片附件在 Agent 模式仍不支持，不因开启附件而改变。

## K-P1-4

- 答案生成时按实际进入提示词的 chunk 计算：
  - `citation_precision`：引用文档中属于相关文档的比例。
  - `citation_recall`：相关文档被引用的比例。
- 聚合指标新增 `citation_precision`、`citation_recall`、`citation_f1`。
- 已有 `faithful_rate`、`judge_avg_score` 在评测详情与对比表展示。
- 仅答案生成开启时计算引用指标；检索-only 运行保持 `null`。

## M-P1-4

`POST /memories/eval/run` 新增可选：

- `generate_answers`、`provider_id`、`model`。

A/B 流程：

- 每个用例分别在有记忆注入、无记忆注入下生成回答。
- 同一模型对两份回答判分（1-5）与忠实度。
- 结果写入 `memory_eval_runs.results`；聚合：
  - `answer_score_with_memory`
  - `answer_score_without_memory`
  - `answer_lift`
  - `faithful_rate_with_memory`
  - `faithful_rate_without_memory`
  - `answer_judge_errors`
- 开启回答评测时最多 50 个用例，默认关闭。
- 用量写入 `usage_events.source=memory_eval`。
- 质量页新增“生成回答并判分”开关和回答指标徽章。

边界：判分模型与回答模型相同；不提供独立 judge 模型或多次重复采样。

## 验证

- `ruff check .` 通过。
- 全量 `pytest -n auto` 通过；新增 `tests/test_p11_s12_p1_followups.py`（3 个测试）。
- `npm run typecheck`、`npm test`（43）、`npm run build` 通过。

## 后续

- A-P1-4：Agent 模式视觉附件（需模型能力与消息图片协议，未排期）。
- K-P1-4：引用片段级准确性/答案完整性（未排期）。
- M-P1-4：独立 judge 模型、多次采样与置信区间（未排期）。