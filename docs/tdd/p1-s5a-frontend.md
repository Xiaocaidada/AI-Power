# TDD Evidence — P1-S5a: 前端骨架、认证与对话

- **Date:** 2026-11-21
- **Scope:** Vite + React 18 + TS 脚手架、设计令牌、i18n、App Shell、登录/注册/静默刷新、对话（SSE/引用/取消/历史）
- **Source:** [`docs/plan/p1-s5-frontend-ui.md`](../plan/p1-s5-frontend-ui.md) S5a
- **Test runner:** Vitest 3（jsdom）；构建 `tsc --noEmit && vite build`

## User Journeys

1. 作为新用户，我能注册并自动登录，进入对话页。
2. 作为回访用户，刷新页面后仍是登录状态，历史消息与引用可回放。
3. 作为用户，我能选择 provider/model（可选知识库）并流式收到回答。
4. 作为用户，回答中的引用可打开侧栏查看片段与页码。
5. 作为用户，我能中途停止生成，界面不崩溃。
6. 作为用户，我能在中/英之间切换，且选择被记住。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| RED（类型） | `npm run typecheck` | 失败：Vitest 2 内置 Vite 5 与项目 Vite 6 类型冲突 → 升级 Vitest 3.2.7 |
| 单元 | `npm test` | `4 files / 9 tests passed` |
| 构建 | `npm run build` | 通过；JS `392.72 kB`（gzip `124.94 kB`）、CSS gzip `4.15 kB` |
| 开发代理 | `curl localhost:5173/` / `/api/healthz` | `200` / `200` |

**实现范围**：`web/` 工程、设计令牌（`styles/index.css` + Tailwind）、中英词典、HTTP 客户端与单飞刷新、SSE 解析器、App Shell、登录/注册、对话页与引用抽屉。

## 真实浏览器验证（Chrome DevTools，`localhost:5173` → API `:8002`）

```
注册 s5a-ui-1@example.com            → 自动登录，跳转 /chat
Provider 列表                         → local-qwen（真实模型）
发送「用一句话说明什么是 RAG」         → 流式 delta，完成后 35 + 31 tokens
第二问「再用一个生活化的例子…」        → 流式出现「想象你正在准备做一道复杂的菜肴…」，完成后 83 + 50 tokens
刷新页面                              → refresh token 换回 access，历史与 token 数完整回放
切换 English                          → 全站文案切换；刷新后仍是 English
```

知识库 + 引用（通过 API 预置文档「一线城市 800 元/天，提前 3 天申请」）：

```
新对话选择「差旅制度」                  → 顶栏出现 KB chip
提问住宿标准与申请天数                  → 流式「…800 元。出差需提前 3 天…[1]」，165 + 33 tokens
点击「引用 1」                         → 侧栏显示 1、文档 01a1fda0、完整 snippet
刷新页面                              → 引用按钮仍在（来自 message_citations 回放）
```

## 浏览器端发现的缺陷

| 现象 | 根因 | 修复 |
|---|---|---|
| 新会话创建后空白，消息不出现 | React StrictMode 的模拟卸载触发了 `useEffect` cleanup 中的 `abort()`，把刚发起的流取消 | 移除卸载即 abort；只保留「停止生成」按钮主动取消 |
| 侧栏会话列表要等回答结束才出现 | 创建会话后未失效 `['conversations']` | 创建成功即 `invalidateQueries` |
| 发送后输入框在流式期间仍显示原文 | 清空依赖 `onSend` 完成 | `start()` 入口立即清空输入 |

## Test Specification（9）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | SSE 事件跨 chunk 正确重组（中文多字节） | `sse.test.ts` | PASS |
| 2 | CRLF、注释行、单 chunk 多事件 | `sse.test.ts` | PASS |
| 3 | 多行 `data` 拼接、非 JSON 保留字符串 | `sse.test.ts` | PASS |
| 4 | 末尾无空行时 `flush` 仍产出事件 | `sse.test.ts` | PASS |
| 5 | 并发 401 只刷新一次，并轮换 refresh token | `tokens.test.ts` | PASS |
| 6 | refresh 被拒绝时清空 token | `tokens.test.ts` | PASS |
| 7 | 中英词典 key 完全一致 | `i18n.test.ts` | PASS |
| 8 | Enter 发送、Shift+Enter 不发送 | `Composer.test.tsx` | PASS |
| 9 | 纯空白不发送 | `Composer.test.tsx` | PASS |

## 关键实现

- **Token**：access 只在内存；refresh 在 `localStorage`；`refreshAccessToken()` 单飞，失败清空并回登录页。
- **HTTP**：`apiRequest` 在 401 时刷新并重放一次；`publicRequest` 用于登录/注册/登出。
- **SSE**：`fetch` + `ReadableStream`，解析 `meta/citation/delta/usage/done/error`；abort 后忽略后续事件。
- **流式渲染**：流中纯文本 + 光标；完成后一次 Markdown 解析（`react-markdown`，禁用 raw HTML）。
- **引用**：来自 SSE 的 `citation` 与历史 `message_citations`；抽屉展示序号、页码/文档前缀、snippet。
- **i18n**：`zh` 为默认与兜底；`en` 以 `Dictionary` 类型约束，测试保证 key 对齐。
- **开发代理**：`/api` → `VITE_PROXY_TARGET`（默认 `http://192.168.29.100:8002`），避免开发时依赖 CORS。

## Known Gaps

- **未接入 Playwright**：本次用 Chrome DevTools 手工验证；E2E 自动化留到 S5c 收口。
- **ChatPage 无组件级测试**：SSE 状态机目前靠浏览器验证，后续补 reducer 抽取与测试。
- **知识库/用量/设置页为占位**：S5b/S5c 实现。
- **无暗色主题开关**：令牌已备，按计划不阻塞。
- **access token 仅在内存**：刷新页面必然走一次 refresh（预期行为）。
- **多标签页并发轮换**：仍可能触发一次重新登录，P2 换 httpOnly cookie。
- **无消息分页**：长会话一次性加载。