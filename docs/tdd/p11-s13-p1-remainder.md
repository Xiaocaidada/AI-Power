# P11-S13：剩余 P1（关系编辑 / Builder 流 / 检索节点）

日期：2026-11-24

## 范围

- M-P1-2：记忆关系类型与依据编辑。
- A-P1-3：AI Builder 流式状态。
- K-P1-2：意图分类与同义词扩展节点。

## M-P1-2

- 新增 `PATCH /memories/relations/{relation_id}`：
  - 可修改 `relation_type` 与 `basis`；
  - 关系类型必须在既有枚举内；
  - 改类型后若同一对端点已存在该类型，返回 `422 invalid_relation`；
  - 工作区/用户隔离，跨用户 404。
- 记忆详情关系行新增内联编辑：类型下拉、依据输入、保存/取消。

## A-P1-3

- 新增 `POST /agent-builder/sessions/{id}/messages/stream`：
  - SSE `stage` 事件：`preparing`、`generating`、`finalizing`、`done`；
  - `result` 事件携带完整 turn 结果；
  - `error` 事件携带类型化错误；
  - 客户端断开时取消生成任务。
- Studio Builder 改用该流式接口，生成期间展示阶段文案。
- 原有同步 `/messages` 保留，兼容现有调用。

边界：这是阶段流，不是模型 token 级流式；生成/校验仍由原服务完成。

## K-P1-2

新增检索节点：

- `intent_classify`：
  - LLM 从配置分类中选择一个意图；
  - `routes` 可把意图映射到指定知识库，后续检索节点自动使用路由后的 KB；
  - 路由 KB 仍需工作区可访问，否则 `intent_route_unavailable`。
- `synonym_expand`：
  - LLM 生成同义词/相关词并追加到查询；
  - 最多 `max_terms` 个，结果写入 `rewritten_query`。

画布节点目录与图标已补齐；仍保持线性管线，不做条件分支。

## 验证

- `ruff check .` 通过。
- 全量 `pytest -n auto` 通过；新增 `tests/test_p11_s13_p1_remainder.py`（3 个测试）。
- `npm run typecheck`、`npm test`（43）、`npm run build` 通过。

## 剩余

- K-P1-1 仍为部分：OCR 独立节点、格式专用解析节点、全文/混合索引模式尚未实现。
- A-P1-3 可继续做 token 级流式与生成阶段内细分（未排期）。
- K-P1-2 可继续做条件分支路由与同义词词典（未排期）。