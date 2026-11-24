# P11-S3 AI Builder 控制能力

## 目标

补齐 X-P0-4 / A-P1-3：

- 澄清提问：需求存在关键歧义时先问一个问题，不强行生成。
- 取消生成：用户可以中止正在进行的 Builder 请求。
- 部分采纳：按差异项勾选要应用的节点/边，而不是只能整包应用。

## 澄清提问

`AgentBuilderResult` / `AgentBuilderTurnOut` 增加 `clarification`。

Prompt 约定：

- 只有在歧义会显著改变图结构时才提问；
- 返回 `clarification` 且省略 `definition`；
- 不要为次要细节提问，优先采用低风险默认。

会话：

- 助手消息同时保存澄清文本；
- 后续请求会把最近 10 条 user/assistant 消息加入模型上下文，用户回答后继续生成。

前端：

- 聊天区与结果区展示“需要澄清”；
- 没有 definition 时不显示“应用到画布”。

## 取消生成

后端：

- Builder 请求通过 `_run_cancellable` 包装；
- 每 0.5s 检查客户端是否断开；断开时取消生成协程并返回 `generation_cancelled`（499）。
- 前端 abort 后展示“已取消生成”。

前端：

- `apiRequest` 携带 `AbortSignal`；
- 生成中显示“取消生成”按钮，点击 abort 当前请求。

## 部分采纳

`web/src/lib/builderApply.ts`：

- `defaultBuilderSelection(diff)`：默认勾选全部差异。
- `applyBuilderSelection(current, target, diff, selection)`：
  - 按勾选项增删/更新节点；
  - 按勾选项增删边；
  - 自动剪除端点已不存在的悬空边。

`DiffView`：

- 每个新增/删除/更新节点、增删边带复选框；
- 未勾选变更不会进入应用的画布定义。

`StudioBuilderPanel` / `KnowledgeBuilderPanel`：

- 应用时先计算部分合并结果；
- 后端 session `/apply` 保存实际应用的定义；
- 画布只应用选中变更。

## 测试

- `tests/test_p11_s3.py`：
  - 首次返回澄清、无 definition；
  - 回答后生成 definition；
  - 第二次请求的模型上下文包含上一次澄清问题；
  - session 消息保存 `clarification`。
- `web/src/lib/builderApply.test.ts`：
  - 全选应用、取消勾选、悬空边剪除。
- `web/e2e/p8.spec.ts`：
  - Builder 差异复选框存在并可切换；
  - 澄清问题展示且无“应用到画布”。

验证：

- `ruff check .` 通过。
- `pytest -n auto` 全量通过。
- `npm run typecheck`、`npm test`（40 个）、`npm run build` 通过。
- Playwright `e2e/p8.spec.ts` 6 个通过。

## 边界

| 边界 | 状态 | 说明 |
|---|---|---|
| 澄清提问 | 已解决 | 单问题、可继续多轮 |
| 取消生成 | 已解决 | 客户端 abort + 服务端断连取消（尽力而为） |
| 部分采纳 | 已解决 | 节点/边粒度复选框 |
| 流式生成阶段 | 未实现 | 当前仍为单次请求返回 |
| 取消后的 Provider 计费 | 尽力 | 上游是否立即停止取决于 Provider SDK |
| 冲突合并策略 | 简化 | 部分采纳后剪除悬空边，不做自动重连 |