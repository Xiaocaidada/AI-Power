# TDD Evidence — P2-S5: 前端平台化

- **Date:** 2026-11-21
- **Scope:** workspace 切换/成员、模型广场与对比、配额面板、`auto` 选择、trace 抽屉；后端 `/usage/quota` 与消息 `request_id`
- **Source:** [`docs/plan/p2-plan.md`](../plan/p2-plan.md) S5
- **Test runner:** Vitest 3 + `tsc --noEmit` + `vite build`；pytest

## User Journeys

1. 作为用户，我能在侧栏切换 workspace，切换后资源列表随之变化。
2. 作为 owner，我能新建 workspace、邀请已注册成员并移除成员。
3. 作为用户，我能浏览模型广场，选择 2–3 个模型并排对比。
4. 作为用户，我能选择「自动路由」开始对话。
5. 作为用户，我能在用量页看到配额余量与重置时间。
6. 作为用户，我能从回答的「详情」查看检索/首 token/总耗时。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 前端类型 | `npm run typecheck` | 通过 |
| 前端测试 | `npm test` | **7 files / 18 tests passed** |
| 前端构建 | `npm run build` | 入口 gzip **136.21 kB**；Usage chunk gzip 130.08 kB |
| 后端全量 | `pytest` | **225 passed, 3 skipped** |
| Lint | `ruff check` / `ruff format --check` | 通过 |

## 真实环境验证

```
GET /usage/quota → 200
  plan=free, requests 0/60 (reset 6s), tokens 0/200000 (reset 40925s),
  max_keys=5, active_keys=0
模型广场页面 → 两个目录条目（local-qwen 原模型 + Qwen Local Alt），选择后按钮显示「已选 1」
侧栏 → 工作区下拉（个人空间）、成员入口、模型广场导航
```

浏览器自动化工具在点击时存在坐标/重连抖动，本次对模型广场渲染与选择做了验证；对比表、成员邀请与 trace 抽屉以类型检查、构建和对应 API 测试为准。

## 关键实现

- **workspace**：`localStorage.ai_power_workspace` 保存当前 workspace；`apiRequest` 自动附加 `X-Workspace-Id`；切换时清空 Query 缓存并回到对话。
- **成员页**：`/settings/workspace` 列出 workspace、成员，owner 可邀请（已注册邮箱）与移除。
- **模型广场**：`/models` 卡片（可用状态、上下文、价格、标签）、最多选 3 个对比，调用 `/models/compare`。
- **新对话**：模型下拉改为 `/models` + 「自动路由」，显式选择时提交 provider/model。
- **配额**：`GET /usage/quota` 返回计划、请求/分钟、token/天、Key 数量；用量页展示进度与重置秒数。
- **trace**：`MessageOut.request_id` 透出；助手消息「详情」打开 `TraceDialog`，按 `request_id` 查询。

## Known Gaps

- **无 Playwright**：浏览器验证仍为人工/工具驱动；S6 接入。
- **配额超限提示为通用错误**：前端未解析 `X-Quota-*` 展示倒计时。
- **对比上限**：前端 3 个，后端允许 5 个。
- **成员页仅 owner 可邀请**：无待接受邀请、无角色变更。
- **trace 抽屉依赖旧消息**：只有本次升级后的消息带 `request_id`。
- **暗色主题仍未实现**。
- **工作区删除/退出未提供**。