# P11-S1 画布工程化与版本恢复

## 目标

补齐 Agent 画布与知识画布共用的基础能力：

- 撤销/重做
- 自动保存草稿（后端草稿 + 本地回退）
- 工作流 JSON 导入/导出
- 工作流版本列表与恢复

## 后端

### 草稿

迁移 `c2d3e4f5a6b7` 为 `workflows` 增加：

- `draft_definition`：原始画布 JSON，可不完整
- `draft_saved_at`

API：

- `GET /workflows/{id}/draft`
- `PUT /workflows/{id}/draft`（只校验 `nodes`/`edges` 为列表、数量上限）
- `DELETE /workflows/{id}/draft`
- `GET /workflows/{id}` 同时返回 `draft_definition`/`draft_saved_at`

保存新版本或恢复版本时自动清除草稿。

### 版本

- `GET /workflows/{id}/versions`：按版本倒序。
- `POST /workflows/{id}/versions/{version}/restore`：以目标版本为基础创建新版本（`latest + 1`），写 `workflow.restore` 审计。

所有新接口沿用 workspace 隔离，跨工作区返回 404。

## 前端

`web/src/pages/studio/StudioCanvas.tsx`：

- 本地历史栈（`web/src/lib/canvasHistory.ts`）：
  - 工具栏撤销/重做按钮；
  - `Ctrl/Cmd+Z`、`Shift+Ctrl/Cmd+Z`、`Ctrl/Cmd+Y`；
  - 添加节点、连线、删除、配置变更、拖拽、边条件修改都会进入历史。
- 导入/导出：
  - 导出当前定义为 JSON 文件；
  - 导入 JSON 文件并应用，格式错误提示。
- 草稿：
  - 变更后 1.2s 防抖回调 `onAutosave`；
  - 显示“正在保存/草稿已保存/保存失败”。
- 版本：
  - 底部工具栏选择历史版本并恢复。

`web/src/lib/canvasDraft.ts`：

- 工作流已存在时使用后端草稿；
- 新建 Agent/知识画布尚未创建 workflow 时使用 localStorage；
- 保存版本后清理本地草稿。

三个页面接入：

- `AgentStudioPage`（`/studio/:id`）
- `KnowledgeStudioPage`（`/knowledge/:id/studio`）
- `KnowledgeRetrievalStudioPage`（`/knowledge/:id/retrieval`）

进入画布时优先恢复未保存草稿，并显示“已恢复上次未保存的草稿 / 丢弃草稿”。

## 测试

- `tests/test_p11_s1.py`：
  - 草稿保存/读取/自动清除；
  - 非法草稿 422；
  - 版本列表与恢复生成新版本；
  - 跨工作区 404。
- `web/src/lib/canvasHistory.test.ts`：撤销/重做/历史上限。
- `web/e2e/p8.spec.ts`：
  - 画布撤销按钮、版本选择、草稿保存状态；
  - 进入画布恢复草稿并可丢弃。

验证：

- `ruff check .` 通过。
- `pytest -n auto` 全量通过。
- `npm run typecheck`、`npm test`（37 个）、`npm run build` 通过。
- Playwright `e2e/p8.spec.ts` 5 个通过。

## 边界

| 边界 | 状态 | 说明 |
|---|---|---|
| 撤销/重做 | 已解决 | 本地历史栈 + 快捷键 |
| 自动保存草稿 | 已解决 | 后端草稿 + localStorage 回退 |
| 导入/导出 | 已解决 | JSON 文件 |
| 版本列表/恢复 | 已解决 | 恢复生成新版本并审计 |
| 恢复后自动重新绑定知识库 | 不自动 | 知识画布仍需用户点击“绑定最新版本” |
| 实时协同 | 后续 | 未实现 CRDT/多人协同 |
| 草稿合法性 | 宽松 | 草稿允许不完整，保存版本时严格校验 |