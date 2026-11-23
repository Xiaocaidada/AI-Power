# P10-S6 记忆质量、优化与评测

## 目标

闭环记忆生命周期：发现重复/冲突/过期/低价值记忆 → 生成可解释建议 → 用户确认应用 → 支持回滚；同时提供记忆评测集、配额、指标与压测。

## 数据模型

迁移 `b1c2d3e4f5a6`：

- `memory_optimizations`
  - `kind`：`merge_duplicates | resolve_conflict | expire_memory | archive_memory | recategorize`
  - `status`：`pending | applied | dismissed | rolled_back`
  - `memory_ids`、`payload`、`before_snapshot`
- `memory_eval_cases`
  - `query`、`expected_memory_ids`、可选 `project_id`/`agent_id`
- `memory_eval_runs`
  - `metrics`、逐用例 `results`、`duration_ms`

## 质量分析

`app/services/memory_quality.py`：

- 重复：相似度 ≥ 0.6 的记忆通过并查集分组（复用 `memory_linking.memory_similarity`）。
- 冲突：
  - 已有 `contradicts` 关系；
  - 启发式语义冲突：高相似度且极性相反、标题相同但内容不同、或 `uses X` / `uses Y` 取值不同。
- 过期：`valid_until <= now`。
- 长期未用：90 天未被调用。
- 缺失来源：非手动来源但没有 `source_id`/`source_ref`。
- 内容不完整：正文 < 12 字符。
- 统计同时返回重复组 ID，便于前端定位。

## 优化建议

- `POST /memories/quality/analyze` 生成建议；相同 `(kind, memory_ids, target/status/category)` 的待处理建议不重复创建。
- 建议包含 `title`、`reason`、`expected_effect`、`memory_ids`、`payload`。
- 应用：
  - `merge_duplicates`：更新保留项内容、归档重复项、建立 `supersedes` 关系。
  - `resolve_conflict`：归档冲突中的低优先级项。
  - `expire_memory` / `archive_memory`：修改状态。
  - `recategorize`：调整分类。
- 应用前保存受影响记忆的标题/内容/分类/状态/启用/重要度/标签快照。
- `POST /memories/optimizations/{id}/rollback` 恢复快照并删除合并时创建的 `supersedes` 关系。
- `POST /memories/optimizations/{id}/dismiss` 忽略建议。
- 跨用户/工作区访问返回 404。

夜间整理：worker 每天 04:00 运行 `consolidate_memories_job`，为启用记忆中心的用户重建自动关系并生成建议。

## 记忆评测集

- `GET/POST /memories/eval/cases`、`DELETE /memories/eval/cases/{id}`。
- 用例包含查询、期望记忆 ID、可选项目/Agent 上下文。
- `POST /memories/eval/run`：
  - 对每个用例调用 `select_memories`（Top K，默认 5）。
  - 计算 Precision、Recall、MRR、Hit Rate。
  - 保存逐用例检索结果与汇总指标。
- `GET /memories/eval/runs` 返回最近运行。

## 指标与配额

Prometheus：

- `ai_power_memory_quality_actions_total{action=generated|applied|rolled_back|dismissed|nightly}`
- `ai_power_memory_eval_runs_total{status=completed}`

记忆配额：

- `QUOTA_FREE_MAX_MEMORIES`（默认 500）
- `QUOTA_PRO_MAX_MEMORIES`（默认 10000）
- `create_memory` 创建前按 workspace plan 计数（排除 archived/rejected），超限返回 429，带 `X-Quota-Metric: memories`。
- `/usage/quota` 新增 `memory.max_memories` / `memory.memory_count`。

## 界面

`/memory` 新增“质量分析”标签：

- 质量统计卡片与“重新分析”。
- 建议列表：类型、状态、原因、预期效果；待处理可应用/忽略，已应用可回滚。
- 评测集：创建用例（选择期望记忆）、删除用例、运行评测、查看 Precision/Recall/MRR 与逐用例结果。
- `/usage` 配额区展示长期记忆用量。

## 压测

`scripts/loadtest_memories.py`：

```bash
python scripts/loadtest_memories.py --base-url http://192.168.29.100:8002 \
  --concurrency 10 --requests 30 --memories 60
```

实测（60 条记忆，10 并发）：

- `/memories`：30/30 成功，P50 79.5ms，P95 172.6ms，最大 178.3ms。
- `/memories/graph`：15/15 成功，P50 118.7ms，P95 156.0ms，最大 182.7ms。

## 测试证据

`tests/test_p10_s6.py`：

1. 重复建议应用后归档重复项、保留合并内容；回滚恢复两条记忆原文与状态。
2. 冲突/过期建议生成与应用；冲突项归档、过期项标记 expired。
3. 忽略建议后不可再应用；跨用户应用返回 404。
4. 评测用例创建、运行、指标 > 0、运行历史、跨用户删除 404。
5. 记忆配额：免费计划上限 1 时第二条创建返回 429。

全量验证：

- `ruff check .` 通过。
- `pytest -n auto` 全量通过。
- `npm run typecheck`、`npm test`（33 个）、`npm run build` 通过。
- Playwright memory 用例覆盖质量标签渲染。

## 边界处理

| 边界 | 状态 | 说明 |
|---|---|---|
| 重复/冲突/过期/未用分析 | 已解决 | 规则 + 启发式 |
| 建议应用/回滚 | 已解决 | 快照恢复 + 关系清理 |
| 记忆评测集 | 已解决 | Precision/Recall/MRR |
| 指标 | 已解决 | 质量动作与评测运行计数 |
| 配额 | 已解决 | Workspace plan 计数 + 429 |
| 夜间整理 | 已解决 | 每日 04:00 rebuild + 建议 |
| 通用语义矛盾推理 | 部分解决 | 极性/取值/同标题启发式，未接入 LLM 语义判断 |
| 通用实体消歧 | 后续规划 | 关系图谱第一版不做实体识别 |
| 自动删除记忆 | 未实现 | 建议只归档/过期，避免不可逆操作 |