# P6 Chat UI 切片 1–2 实施证据

## 范围

按 `docs/plan/p6-chat-ui-plan.md` 实施切片 1–2，纯前端，不修改后端 API、SSE 契约或数据模型：

- 独立聊天布局 `ChatLayout` 与专用侧栏 `ChatSidebar`。
- 新建会话页改为“输入优先”：居中大输入框、模型选择内嵌、项目/Agent/知识库 chip、高级设置弹层。
- 会话页：可编辑标题、精简 header、更多菜单、消息时间、悬停操作、运行详情折叠、智能滚动。
- 控制台侧栏移除会话历史，聊天侧栏承担搜索、项目筛选、置顶与时间分组。

## 文件

新增：

- `web/src/components/ChatLayout.tsx`
- `web/src/components/ChatSidebar.tsx`
- `web/src/lib/conversationGroups.ts` / `conversationGroups.test.ts`
- `docs/plan/p6-chat-ui-plan.md`

修改：

- `web/src/App.tsx` — `chat`、`chat/:id` 路由移入 `ChatLayout`。
- `web/src/components/AppShell.tsx` — 删除旧会话列表与菜单逻辑。
- `web/src/pages/chat/NewChatPage.tsx`
- `web/src/pages/chat/ChatPage.tsx`
- `web/src/pages/chat/MessageItem.tsx`
- `web/src/pages/chat/Composer.tsx`
- `web/src/lib/format.ts` / `format.test.ts`
- `web/src/locales/zh.ts` / `en.ts`
- `web/e2e/workflow.spec.ts` — 登录后直接访问 `/workflows`，不再依赖对话页中的控制台导航。

## RED / GREEN

1. `conversationGroups.test.ts`：先定义今天/昨天/7 天内/更早分桶与空组丢弃行为，再实现 `conversationTimeGroup` / `groupConversationsByTime`。
2. `format.test.ts`：新增 `formatTime` 用例；首次运行失败（`09:05 AM`），改为 `hour12: false` 后通过。
3. `Composer.test.tsx`：保留 Enter 发送、Shift+Enter 换行、纯空白不发送三条既有行为，Composer v2 保持兼容。

## 验证结果

- `npm run typecheck`：通过。
- `npm test -- --run`：11 个测试文件、28 个用例全部通过。
- `npm run build`：通过（仅既有 chunk 体积提示）。
- `npm run test:e2e`：7 个 Playwright 用例全部通过（smoke / content / projects / assist / agents / workflow ×2）。
- 真实渲染检查（Playwright + mock 数据，1440×900 与 390×844）：
  - 新建会话页：居中标题、大输入框、模型 chip、配置 chips、2×2 推荐卡片。
  - 会话页：用户气泡、助手全宽正文、引用 chip、复制/重生成/反馈、运行详情折叠。
  - 深色模式：侧栏、输入框、选中会话、正文对比度正常。
  - 移动端：侧栏收起为抽屉，输入区与配置 chips 正常换行。
- 容器：`docker compose up -d --build web` 后 `web=200`、`/api/readyz=200`。

## 视觉打磨（追加）

在本轮反馈后补充：

- 新增 `web/src/components/ui/popover-select.tsx`，替换新建页项目 / Agent / 知识库 / 模型四个原生 `<select>`。浮层支持分组、选中勾选、Esc / 方向键 / Home / End、点击外部关闭，选中后触发器使用 `accent-soft` 高亮。
- 新建页标题改为“让想法，从一句话开始。”，强调词使用陶土橙并带手绘 SVG 下划线；背景增加低透明度 `chat-hero-glow`。
- 深色模式切换为 Claude 风格暖色令牌：`canvas 26 25 23`、`surface 34 33 30`、`ink 238 235 228`、`accent 217 119 87`；新增 `--accent-ink` 保证橙底按钮对比度，新增 `--chart-1/2/3` 并替换用量页硬编码图表色。
- 聊天侧栏左上角新增返回箭头（`navigate(-1)`，无站内历史回 `/dashboard`）；移除“项目”右侧“管理”链接与底部“返回控制台”。

验证：`npm run typecheck`、`npm test -- --run`（12 个文件 / 31 个用例，含新增 `popover-select.test.tsx`）、`npm run build`、`npm run test:e2e`（7 个用例）全部通过；并用 Playwright + mock 数据复检浅色/深色/移动端与下拉展开态。

## 边界

以下仍按规划留待后续切片，不在本次范围：

- 编辑历史提问并重发（需要消息 PATCH/截断语义）。
- 会话硬删除与批量操作。
- 附件与多模态上传。
- 正文内 `[1]` 引用上标跳转。