# P11-S9：LLM 语义矛盾检测

日期：2026-11-24

## 目标

在现有启发式质量分析之外，提供按需、显式触发的 LLM 语义矛盾检测。只生成待确认建议，不自动归档或修改记忆。

## 实现

- `app/services/memory_semantic.py`
  - 取当前用户 60 条活跃记忆，同分类、作用域兼容的两两组合按词面相似度 + 共享标签排序，最多 12 对。
  - 单次批量调用 LLM，要求返回 `pair_id/contradicts/confidence/reason` JSON。
  - 只接受 `confidence >= 0.6` 且 `pair_id` 属于本次输入的结果。
  - 复用 `MemoryOptimization(kind=resolve_conflict, payload.semantic=true)`，保留 `keep_id`/`archive_id`。
  - 相同记忆对已有 pending 建议时跳过，重复触发幂等。
  - 模型优先级：请求参数 → `MEMORY_EXTRACTION_*` → 模型目录首个启用模型。
- `app/routers/memories.py`
  - `POST /memories/quality/semantic`，请求 `provider_id`/`model`/`limit`，返回检查对数、矛盾数、新建建议数与建议列表。
  - 记忆中心关闭时返回 `422 memory_disabled`；Provider 不存在时 `422 provider_unavailable`。
- 用量与指标
  - `usage_events.source=memory_quality`。
  - `ai_power_memory_semantic_checks_total`、`ai_power_memory_semantic_contradictions_total`。
- 前端
  - 质量页新增“深度冲突分析”按钮，显示检查/矛盾/新增数量，完成后刷新质量与建议列表。

## 验证

- `tests/test_p11_s9_semantic.py`
  - 语义矛盾生成一条 `resolve_conflict` 建议，重复分析不重复创建。
  - 记忆中心关闭和 Provider 不可用返回类型化错误。
  - 分析只读取调用者自己的记忆。
- `ruff check app tests alembic` 通过。
- 全量后端测试、前端类型检查/测试/构建通过。

## 边界

- 只比较同分类、作用域兼容的记忆；跨分类冲突不检测。
- 只生成建议，不自动应用；应用仍走人工确认与现有回滚链路。
- 调用成本受 60 条记忆 / 12 对上限约束。
- 未实现实体级知识图谱、外部连接器、多模态与实时协同。