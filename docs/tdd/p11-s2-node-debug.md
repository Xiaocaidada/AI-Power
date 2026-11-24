# P11-S2 单节点调试与从节点运行

## 目标

补齐 X-P0-3：

- 单节点测试：使用已保存版本，只执行目标节点。
- 从指定节点运行：跳过上游节点，可用注入输出补齐 `{{node_id}}`。
- 查看节点实际输入、输出、耗时与错误码。

## 后端

### 单节点调试

`POST /workflows/{workflow_id}/nodes/{node_id}/debug`

请求：

```json
{
  "version": 3,
  "input": "测试输入",
  "node_outputs": { "first": "上游模拟输出" }
}
```

响应：

```json
{
  "run_id": "…",
  "node_id": "second",
  "node_type": "llm",
  "status": "completed",
  "output": "…",
  "input_summary": "渲染后的节点输入",
  "error_code": null,
  "duration_ms": 12.3,
  "node_run_id": "…"
}
```

实现：

- 仅支持 `kind=agent`；知识处理/检索分别使用既有 preview / retrieval test。
- `review` 节点不进入单节点调试（需要排队 run 与人工审核）。
- 创建一条真实 `workflow_runs`/`workflow_node_runs` 记录，便于审计与查看。
- 使用 `get_scoped_registry`，支持用户私有 Provider。
- 执行前检查请求配额。

### 从节点运行

`POST /workflows/{id}/runs` 新增：

- `start_node_id`
- `node_outputs`

`WorkflowRunner`：

- 记录 `start_node_id`，直接把该节点置为 `ready`。
- 注入的 `node_outputs` 先写入 `_outputs`，对应节点标记为 `completed`，其出边视为可用。
- 未注入的上游节点保持 pending，不影响从目标节点向下的执行。
- 运行事件、节点记录、取消、usage ledger 与普通 run 一致。

## 前端

`StudioNodePanel`：

- Agent 画布节点配置底部增加“单节点调试”：
  - 测试输入；
  - 上游节点输出 JSON；
  - 测试节点按钮；
  - 显示状态、耗时、错误码、节点输入摘要与输出。
- 知识画布不显示该面板（使用各自测试入口）。

`StudioRunPanel`：

- 增加“从指定节点开始”下拉；
- 选择节点后可填写上游输出 JSON；
- 运行请求携带 `start_node_id`/`node_outputs`。

## 测试

- `tests/test_p11_s2.py`：
  - 单节点调试注入上游输出；
  - 从节点运行只产生目标节点的 `node_start`；
  - 缺失节点返回 404；
  - 跨 workspace 调试返回 404。
- `web/e2e/p8.spec.ts`：
  - 节点面板展示调试区并返回 mock 输出；
  - Run 面板展示从节点运行与上游输出输入。

验证：

- `ruff check .` 通过。
- `pytest -n auto` 全量通过。
- `npm run typecheck`、`npm test`（37 个）、`npm run build` 通过。
- Playwright `e2e/p8.spec.ts` 5 个通过。

## 边界

| 边界 | 状态 | 说明 |
|---|---|---|
| 单节点调试 | 已解决 | Agent 画布 |
| 从节点运行 | 已解决 | 注入上游输出 |
| 节点输入/输出查看 | 已解决 | 响应 + node run |
| review 节点调试 | 不支持 | 需要排队 run 与人工审核 |
| 知识处理节点调试 | 沿用现有 preview | 不在本切片扩展 |
| 知识检索节点调试 | 沿用 retrieval test | 不在本切片扩展 |
| 上游分支条件自动推断 | 简化 | 注入节点出边全部视为可用 |