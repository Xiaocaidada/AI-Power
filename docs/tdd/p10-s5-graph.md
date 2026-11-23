# P10-S5 记忆关系图谱

## 目标

把分散的记忆与项目/Agent/文档来源组织成可浏览、可筛选、可维护的关系网络：

- 自动发现记忆-记忆相似关系。
- 自动建立记忆到项目/Agent/文档的外部引用边。
- 提供图查询 API（节点、边、统计、焦点邻域）。
- 提供手动创建/删除关系。
- 在 Memory Hub 增加“关系图谱”视图。

## 自动关系

`app/services/memory_linking.py`：

- 记忆创建、更新、版本恢复后调用 `auto_link_memory`。
- 记忆-记忆相似度：词元重合度 + 分类加成 + 标签 Jaccard；有向量时取向量余弦与词法分数的较大值。
- 阈值 `MIN_LINK_SCORE=0.35`，每条记忆最多自动连接 5 条。
- 作用域隔离：全局记忆可与任意作用域关联；项目记忆只与同项目记忆关联；Agent 记忆只与同 Agent 记忆关联。
- 外部节点：
  - 项目作用域记忆 → 项目
  - Agent 作用域记忆 → Agent
  - 文档来源记忆 → 文档
- 自动边 `source="auto"`，记录 `confidence` 与 `basis`。
- 双向去重；记忆作用域变化时清理过期的外部自动边。

`POST /memories/graph/rebuild` 可为历史记忆补建关系（最多 500 条记忆）。

## 图 API

`GET /memories/graph`：

- 过滤：`q`、`scope_type`、`project_id`、`agent_id`、`category`、`status`（默认 `active`）、`limit`。
- `focus_id` 返回该记忆的一跳邻域。
- 节点：
  - `memory:<uuid>`：标题、分类、作用域、状态、置顶、重要度。
  - `project|agent|document:<uuid>`：解析后的名称/文件名。
- 边：`source`、`target`、`relation_type`、`confidence`、`basis`、`source_kind`。
- 统计：记忆节点数、外部节点数、关系边数、孤立记忆数。
- 无法解析或跨工作区的外部节点会被丢弃，边同步过滤。

手动关系：

- `POST /memories/{id}/relations` 支持 `memory|project|document|agent`，校验目标属于当前工作区/用户；禁止自关联。
- `DELETE /memories/{id}/relations/{relation_id}` 与顶层 `DELETE /memories/relations/{relation_id}`。

## 界面

`/memory` 新增“关系图谱”标签：

- React Flow 圆形布局，记忆节点内圈、外部节点外圈。
- 自动边虚线、手动边实线。
- 支持搜索、作用域/分类过滤、拖拽/缩放、MiniMap。
- 点击节点选中其邻域；勾选“仅显示选中节点邻域”进入局部视图。
- 点击记忆节点打开详情；详情中可添加/删除手动关系。
- “重建自动关系”按钮补建历史关系。

## 测试证据

`tests/test_p10_s5.py`：

1. 相似记忆自动生成 `related` 边；项目记忆自动生成记忆→项目外部边。
2. 图 API 返回记忆/项目节点、边与统计。
3. 作用域过滤与 `focus_id` 邻域。
4. 自关联 422、跨工作区目标 404、手动关系创建/删除。
5. 清空关系后 `POST /graph/rebuild` 可补建。

同步调整 `tests/test_p10_s0.py` 的手动关系断言，使其容纳自动关系。

全量验证：

- `ruff check .` 通过。
- `pytest -n auto` 全量通过。
- `npm run typecheck`、`npm test`（33 个）、`npm run build` 通过。
- Playwright memory 用例覆盖图谱标签渲染。

## 边界处理

| 边界 | 状态 | 说明 |
|---|---|---|
| 自动记忆-记忆关系 | 已解决 | 词法/向量相似度 + 阈值 |
| 项目/Agent/文档外部节点 | 已解决 | 自动建边，图查询解析名称 |
| 手动关系创建/删除 | 已解决 | 校验工作区与目标类型 |
| 局部关系图 | 已解决 | API `focus_id` + 前端邻域过滤 |
| 孤立节点识别 | 已解决 | 图统计 `orphans` |
| 通用实体消歧 | 后续规划 | 第一版不做实体识别 |
| 语义矛盾检测 | 后续 P10-S6 | 仅保留 `contradicts` 关系类型 |
| 自动关系清理任务 | 按需 | 图查询忽略悬空边；作用域变化时清理外部自动边 |