# P1-S5 前端 UI 规划（React + TS）

- **Status:** S5-pre、S5a、S5b、S5c 已完成（2026-11-21）；下一步 S6 部署
- **Date:** 2026-11-21
- **Scope source:** [`p1-plan.md`](./p1-plan.md) S5、[`CAPABILITY.md`](../product/CAPABILITY.md)、[`ADR-0004`](../adr/0004-auth-sessions.md)、[`ADR-0007`](../adr/0007-api-keys.md)
- **No code:** 本文只做 UI/交互/契约规划。

## 1. 目标与非目标

**目标**

1. 局域网内完成 3 分钟 demo：注册 → 建知识库 → 上传 → 带引用提问 → 回放历史 → 查看用量 → 创建 Key → 用 Key 调用。
2. 界面可截图放进作品集：视觉统一、状态完整（加载/空/失败/流式中断）、移动端不崩。
3. 中文为默认语言，支持中/英切换；所有文案走 i18n，不写死在组件里。
4. 只消费既有 API；不为 UI 便捷破坏后端契约。

**非目标**

- 模型广场、模型对比、管理后台、计费、组织/团队（P2/P3）。
- SSR/SEO、PWA/离线、富文本编辑器、文件在线预览。
- 深色主题不是本切片阻塞项：先做浅色 + 令牌级暗色变量，S5c 有余量再开开关。

## 2. 视觉方向：Soft 产品化

已确认：**产品化**，参考 OpenAI、Anthropic、阿里云百炼、GLM 的主流做法。

| 参考 | 借用 | 不照搬 |
|---|---|---|
| OpenAI | 左侧会话列表 + 居中输入框 + 干净的对话流 | 极简到缺少元信息（模型/token/引用） |
| Anthropic | 暖中性色、登录页编辑感（衬线大标题）、宽松行高、右侧资料面板 | 全站米色与强文学气质 |
| 阿里云百炼 | 控制台结构清晰、用量面板、知识库是一等公民 | 密集表格带来的压迫感 |
| GLM | 中文优先文案、顶部模型 chip、知识库 attachment chip | 营销式渐变与装饰 |

**结论**：聊天区像 OpenAI 一样安静，控制台区像百炼一样有信息密度；用 Anthropic 的排版克制感把两者缝合。单一蓝紫强调色，引用用琥珀色作为第二强调。

## 3. 设计令牌

### 3.1 颜色

| Token | Light | Dark | 用途 |
|---|---|---|---|
| `canvas` | `#F6F7F9` | `#0B0F19` | 页面底色 |
| `surface` | `#FFFFFF` | `#111827` | 卡片/侧栏 |
| `surface-muted` | `#F1F2F5` | `#1A2234` | 输入框、hover |
| `border` | `#E4E6EB` | `#263042` | 1px 分隔 |
| `ink` | `#171A20` | `#E8EAF0` | 主文字 |
| `ink-muted` | `#6B7280` | `#94A3B8` | 次要文字 |
| `accent` | `#4F46E5` | `#818CF8` | 主按钮、选中态、链接 |
| `accent-soft` | `#EEF2FF` | `#1E1B4B` | 选中背景、chip |
| `citation` | `#B45309` | `#FBBF24` | 引用编号、引用高亮 |
| `citation-soft` | `#FEF3C7` | `#3B2A0B` | 引用 chip 背景 |
| `success` | `#16A34A` | `#4ADE80` | ready、成功 |
| `warning` | `#D97706` | `#FBBF24` | 处理中、限流提示 |
| `danger` | `#DC2626` | `#F87171` | failed、删除/吊销 |

规则：状态不能只靠颜色，必须同时有图标或文字（如 `● 处理中` / `✕ 失败`）。

### 3.2 字体与排版

- 正文：`ui-sans-serif, -apple-system, "Segoe UI", "PingFang SC", "Microsoft YaHei", "Noto Sans SC", sans-serif`
- 展示（仅登录页/空状态大标题）：`Georgia, "Noto Serif SC", "Songti SC", serif`（系统字体，不引外链 webfont）
- 等宽（Key、ID、token）：`ui-monospace, Consolas, "JetBrains Mono", monospace`
- 字号：12（辅助）/13（控制台表格）/14（正文控件）/16（对话内容）/20（页面标题）/32–40（登录 hero）
- 行高：正文 1.6；对话 1.75；标题 1.2
- 对话内容最大宽度 `72ch`，超出留白而不是拉满

### 3.3 形状与层次

- 圆角：输入/按钮 8px，卡片 12px，抽屉 16px，pill 999px
- 阴影：`0 1px 2px rgb(16 24 40 / 0.04)`；浮层 `0 12px 32px rgb(16 24 40 / 0.12)`
- 间距：4 的倍数；页面水平内边距 24（桌面）/16（移动）
- 动效：120–180ms ease-out；流式光标 1s 闪烁；`prefers-reduced-motion` 下关闭非必要动画

## 4. 信息架构与路由

| 路由 | 页面 | 守卫 | 说明 |
|---|---|---|---|
| `/login` | 登录/注册 | 公开（已登录跳 `/chat`） | 左右分栏：品牌叙述 + 表单 |
| `/chat` | 新对话 | 需登录 | 空状态：模型/知识库选择 + 输入框 |
| `/chat/:id` | 对话详情 | 需登录 | 三栏：会话列表 / 对话 / 引用抽屉 |
| `/knowledge` | 知识库列表 | 需登录 | 卡片网格 + 新建 |
| `/knowledge/:id` | 知识库详情 | 需登录 | 上传区 + 文档表格 |
| `/usage` | 用量 | 需登录 | KPI + 图表 + 明细 |
| `/settings/api-keys` | API Key | 需登录 | 列表 + 创建一次性展示 |
| `/settings/profile` | 个人资料 | 需登录 | 账号信息、语言、登出 |
| `*` | 404 | — | 返回对话 |

导航：侧栏一级入口 `对话 / 知识库 / 用量 / 设置`；会话列表只在对话页出现（避免其他页面拥挤）。

## 5. App Shell

```
┌─────────────┬───────────────────────────────────────────────┐
│ ▍AI 平台     │  页面顶栏：标题 · 状态 · 主操作                │
│             ├───────────────────────────────────────────────┤
│ 对话         │                                               │
│ 知识库       │                 页面内容                       │
│ 用量         │                                               │
│ 设置         │                                               │
│ ─────────── │                                               │
│ 会话列表     │                                               │
│ …           │                                               │
│ ─────────── │                                               │
│ 用户菜单     │                                               │
└─────────────┴───────────────────────────────────────────────┘
```

- 侧栏 264px，`lg` 以下变为抽屉（汉堡按钮），`md` 以下隐藏会话列表只保留导航。
- 顶栏 56px，sticky；对话页顶栏含 `模型 · 知识库` chips 与引用抽屉开关。
- 引用抽屉 360px；`xl` 以下改为覆盖式 Sheet。

## 6. 页面规格

### 6.1 登录/注册（`/login`）

- 布局：左侧 5/12 品牌区（衬线大标题、三行能力说明、当前部署地址），右侧表单卡；`lg` 以下只保留表单。
- Tab：登录 / 注册。注册字段 email、password（≥8）、确认密码（仅前端校验）。
- 交互：注册成功 → 自动调用登录 → 进入 `/chat`；登录成功 → 若有 `returnTo` 则回跳。
- 错误：`invalid_credentials` → 邮箱或密码错误；429 → 显示倒计时（读 `Retry-After`），按钮禁用至倒计时结束。
- 状态：提交中禁用按钮 + spinner；网络错误顶部 banner，不丢输入。

### 6.2 对话页

**新对话空状态**

- 居中：`开始新对话`（衬线）+ 一行说明。
- 选择器：Provider（`GET /providers`，`available=false` 禁用并标注“不可用”）、Model（随 provider 变化，默认第一个）、知识库（可选，默认“不使用知识库”）。
- 4 个静态示例问题 chip（点击填入输入框，不自动发送）。
- Provider 列表 `staleTime=60s`；接口失败显示“模型服务不可用”，输入框禁用。

**对话详情**

```
┌──────────┬───────────────────────────────┬──────────────┐
│ 会话列表  │ Qwen2.5-7B · 产品文档   [引用 2]│ 引用          │
│          ├───────────────────────────────┤ 1 《差旅…》p3 │
│ ● 报销制度│ 你：差旅报销标准？             │   snippet…   │
│   产品文档│                               │ 2 《补充…》p1 │
│          │ AI：根据《差旅管理办法》…      │   snippet…   │
│          │     [1] 一线城市 800/天        │              │
│          │     [2] 需提前 3 天申请        │              │
│          │     Qwen2.5-7B · 143+17 tok   │              │
│          ├───────────────────────────────┤              │
│          │ [输入…]                 发送  │              │
└──────────┴───────────────────────────────┴──────────────┘
```

- 用户消息：右对齐、`surface-muted` 气泡、最大宽 80%。
- 助手消息：左对齐、无气泡、16px 正文、Markdown 渲染（`react-markdown`，不启用 raw HTML）。
- 流式渲染：流中按纯文本显示 + 末尾光标 `▍`；`done` 后一次性转 Markdown（避免每个 delta 重解析）。
- 引用条：助手消息下方 `引用 N` chip，点击展开右侧抽屉；抽屉条目含序号、文档名（若可得）、页码、snippet、复制。
  - 后端只给 `document_id/chunk_id/page_no/snippet`，没有文档名 → 默认显示“文档 8f3c…”+ 页码；需要名称时按 `document_id` 懒加载 `GET /documents/{id}`，失败降级为 ID。
- 消息尾：provider/model、`prompt + completion` tokens；复制正文。
- 生成中：输入框禁用，`停止生成` 按钮调用 `AbortController.abort()`；本地把该助手消息标记为“已中断”，随后重取会话以对齐后端 `cancelled`。
- 失败：SSE `error` 事件 → 消息下方红色内联条（含 code 映射文案）+ “重新发送”（把上一条用户消息重新提交）。
- 刷新恢复：`GET /conversations/{id}` 返回 `status=streaming` 的历史消息说明上次异常中断 → 显示“上次生成已中断”徽标，正文保留已生成部分。
- 标题：后端首条消息后写入，前端在 `done` 后刷新会话列表。
- 归档：顶栏更多菜单 → 确认 → `DELETE` → 回 `/chat`。

**输入框**

- 自适应高度 1–6 行；Enter 发送，Shift+Enter 换行；`Cmd/Ctrl+Enter` 也可发送。
- 上限 20000 字符，超过显示计数与错误态。
- 流式中禁用；空内容禁用发送。

### 6.3 知识库

**列表**

- 卡片网格（`sm` 1 列 / `lg` 2 列 / `xl` 3 列）：名称、创建时间、进入、删除（确认对话框，说明“软删除后文档不再参与检索”）。
- 顶部“新建知识库”按钮 → 对话框输入名称（1–100，自动 strip）。
- 空状态：说明 + 新建按钮 + 去对话页的次要链接。

**详情**

```
┌────────────────────────────────────────────────────────┐
│ 产品文档            [上传文档]                          │
├────────────────────────────────────────────────────────┤
│  拖拽 PDF / MD / TXT 到此处，或点击选择（≤20MB）        │
├──────────┬────────┬────────┬──────┬──────────┬────────┤
│ 文件名    │ 状态   │ 大小   │ 页数 │ 失败原因  │ 操作    │
│ 差旅.pdf  │ ● 就绪 │ 1.2MB  │ 12   │ —        │ 删除    │
│ 合同.md   │ ◐ 处理中│ 30KB  │ —    │ —        │ 删除    │
│ 坏文件.pdf│ ✕ 失败 │ 2MB    │ —    │ 解析失败  │ 重试/删除│
└──────────┴────────┴────────┴──────┴──────────┴────────┘
```

- **前置缺口**：当前没有“列出知识库文档”的接口，S5-pre 必须补 `GET /knowledge-bases/{kb_id}/documents`。
- 上传：拖拽 + 点击；扩展名前端先校验（.pdf/.md/.txt），后端仍为准；413/415 映射文案；重复文件 `duplicate=true` → toast“该文件已存在”。
- 进度：用 `XMLHttpRequest` 的 `upload.onprogress`（fetch 无上传进度）；完成后乐观插入一行 `uploaded`。
- 轮询：存在 `uploaded/parsing/embedding` 时每 2s 刷新文档列表；全部终态后停止；页面隐藏时暂停（`visibilitychange`）。
- 重试：仅 `failed` 可重试；`409 document_not_failed` → toast“当前状态不可重试”。
- 删除：确认后 `DELETE /documents/{id}`，乐观移除并在失败时回滚。
- 错误码文案映射：`too_many_pages`、`empty_document`、`embedding_failed`、`embedding_dimension_mismatch`、`ingestion_failed`、`queue_unavailable`，未知码显示“处理失败（code）”。

### 6.4 用量

- 顶部：时间范围分段 `近 7 天 / 近 30 天 / 近 90 天` + 自定义（两个原生 date input）。
- 分组分段：`按日 / 按 Provider / 按模型`（对应 `group_by=day|provider|model`）。
- KPI 卡 4 个：请求数、Prompt tokens、Completion tokens、Total tokens；均由 buckets 求和。
- 图表：
  - `day`：堆叠柱状图（prompt / completion），缺失日期客户端补 0。
  - `provider` / `model`：横向条形图，按 total 降序。
- 明细表：key、请求数、prompt、completion、total；数字右对齐、等宽。
- 空状态：说明“还没有用量，去发起一次对话”，按钮跳 `/chat`。
- 注意：usage 为 NULL 的请求计入请求数但 token 为 0，图表下方小字说明。

### 6.5 API Key

- 表格列：名称、前缀（等宽 `ap_xxxxxxxx`）、scope chips、创建时间、最后使用、状态、操作（吊销）。
- 已吊销行降透明度并显示 `已吊销` 徽标；仍保留在列表。
- 创建对话框：名称 + scope 复选（`chat:write`、`kb:read`，默认全选）。
- **一次性展示弹窗**：等宽 Key、复制按钮、醒目提示“关闭后无法再次查看”，关闭需点击“我已保存”；Esc 与点遮罩不关闭（防误触丢失）。
- 吊销：确认对话框说明“立即失效，无法恢复”；成功后 `204`，列表刷新。
- 认证：本页所有请求仅 JWT；若 access 过期，走静默刷新，不弹登录。

### 6.6 个人资料

- 只读：email、角色、注册时间。
- 语言切换（中文/English，即时生效并持久化）。
- 登出：先 `POST /auth/logout` 吊销 refresh token；即使请求失败也清除本地状态并跳转。

## 7. 组件清单

| 区域 | 组件 | 职责 |
|---|---|---|
| Shell | `AppShell`、`Sidebar`、`Topbar`、`MobileNav` | 布局、导航、折叠 |
| 通用 | `Button`、`IconButton`、`Input`、`Textarea`、`Select`、`Dialog`、`Sheet`、`Toast`、`Badge`、`Spinner`、`EmptyState`、`ErrorBanner`、`ConfirmDialog` | 基础 UI（shadcn/ui 之上封装） |
| 认证 | `LoginForm`、`RegisterForm`、`AuthLayout` | 表单与错误映射 |
| 对话 | `ProviderModelPicker`、`KbPicker`、`ConversationList`、`MessageList`、`MessageItem`、`MarkdownContent`、`StreamingCursor`、`CitationStrip`、`CitationDrawer`、`Composer`、`MessageMeta` | 对话与流式 |
| 知识库 | `KbCard`、`CreateKbDialog`、`UploadDropzone`、`DocumentTable`、`DocumentStatusPill`、`RetryButton` | 知识库管理 |
| 用量 | `RangePicker`、`GroupByTabs`、`KpiCard`、`UsageChart`、`UsageTable` | 用量可视化 |
| Key | `KeyTable`、`CreateKeyDialog`、`KeyRevealDialog`、`ScopePicker` | Key 管理 |
| 设置 | `ProfileCard`、`LanguageSwitch`、`LogoutButton` | 账号 |

## 8. 技术栈与数据层

### 8.1 选型

Vite + React 18 + TypeScript、React Router v6、TanStack Query v5、Zustand（仅会话/偏好）、Tailwind CSS 3.4 + shadcn/ui、lucide-react、Recharts、react-markdown、sonner（toast）、Vitest + Testing Library + Playwright。

### 8.2 状态划分

- **服务端状态**：TanStack Query，禁止复制到全局 store。
- **会话状态**：`authStore`（user、accessToken、status）、`uiStore`（language、sidebarOpen、theme）。
- Query keys：

| Key | 数据 | 失效时机 |
|---|---|---|
| `['me']` | 当前用户 | 登录/登出 |
| `['providers']` | provider 与模型 | 60s stale |
| `['kbs']` | 知识库列表 | 创建/删除 |
| `['kb', id]` | 知识库详情 | 进入详情 |
| `['documents', kbId]` | 文档列表 | 上传/重试/删除/轮询 |
| `['conversations']` | 会话列表 | 首条消息完成/归档 |
| `['conversation', id]` | 会话详情（含引用） | 发送完成、中断后 |
| `['usage', from, to, groupBy]` | 用量 | 切换参数 |
| `['api-keys']` | Key 列表 | 创建/吊销 |

### 8.3 认证与刷新

- access token **只放内存**（Zustand，不落 localStorage）；refresh token 放 localStorage。
  - 取舍：localStorage 有 XSS 读取风险；彻底解决需要后端把 refresh 放 httpOnly cookie（跨端口部署需 CORS credentials），留 P2。
- 请求拦截：`401` → 单飞刷新（`refreshPromise` 复用）→ 成功后重放原请求一次；刷新失败 → 清空状态、跳 `/login?returnTo=...`。
- 刷新本身绝不重试；refresh token 一次性轮换，重复使用会被后端拒绝（ADR-0004）。
- 多标签页：监听 `storage` 事件同步 refresh token；仍可能出现并发轮换失败 → 提示“登录状态已失效，请重新登录”，不做静默循环。

### 8.4 SSE 客户端

- `POST /conversations/{id}/messages` 返回 `text/event-stream`，必须用 `fetch` + `ReadableStream`（`EventSource` 不支持 POST/自定义头）。
- 解析器要求：
  - `TextDecoder(..., {stream:true})`；按 `\n\n` 切事件，兼容 `\r\n`；`data:` 多行拼接；忽略注释行。
  - 事件：`meta`（message_id）、`citation`（可多条）、`delta`（text）、`usage`、`done`、`error`（终态）。
  - 未知事件忽略并 `console.debug`（生产不打日志）。
- 状态机：`idle → sending → streaming → done | failed | cancelled`。
- 取消：`AbortController`；abort 后忽略后续事件，本地标记 `cancelled` 并重取会话。
- 发送流程（乐观更新）：
  1. 追加本地用户消息 + 空助手占位（临时 id）。
  2. 收到 `meta` 用真实 `message_id` 替换临时 id。
  3. `citation` 收集到占位消息。
  4. `delta` 追加文本；`usage` 写入元信息。
  5. `done` → 失效 `conversation`/`conversations`/`usage`；`error` → 保留部分文本 + 错误条。

### 8.5 统一错误处理

- 后端错误体是 FastAPI `{"detail": string | {code,message,...}}`；客户端归一化为 `AppError {status, code, message, retryAfter?}`。
- 已知映射：

| HTTP | code | UI 行为 |
|---|---|---|
| 401 | `invalid_credentials` / `invalid_token` | 登录页错误 / 静默刷新 |
| 401 | `invalid_refresh_token` | 清空登录态，提示重新登录 |
| 403 | `insufficient_scope` | 提示“该 Key 权限不足”（主要影响 API 调用方） |
| 404 | 任意 | 资源不存在页/提示，不回显他人资源 |
| 409 | `document_not_failed` | toast |
| 413 | — | “文件超过 20MB” |
| 415 | — | “仅支持 PDF/MD/TXT” |
| 429 | `login_rate_limited` | 倒计时禁用登录按钮 |
| 502 | `retrieval_failed` | “知识库检索失败，请重试或关闭知识库” |
| 503 | `queue_unavailable` | “入库队列暂不可用，文档已标记失败，可稍后重试” |

## 9. 后端前置缺口（S5-pre）— **已完成（2026-11-21）**

| 优先级 | 缺口 | 影响 | 建议 |
|---|---|---|---|
| **P0** | 无 CORS 中间件 | `:8080` 前端无法调用 `:8002` API | 加 `CORSMiddleware`，origins 从配置读（默认 `http://192.168.29.100:8080`、`http://localhost:5173`），允许 `Authorization/Content-Type/X-API-Key`，暴露 `Retry-After`，不开 credentials |
| **P0** | 无文档列表接口 | 知识库详情页无法渲染 | `GET /knowledge-bases/{kb_id}/documents` → `list[DocumentOut]`，`kb:read`，过滤软删，按创建时间倒序 |
| P1 | 会话/消息无分页 | 数据多时首屏变慢 | 本切片先不分页，文档记录上限；P2 再加 `limit/cursor` |
| P1 | 错误体不统一 | 前端需兼容两种 `detail` | 前端适配即可；若要统一信封再单开 ADR |
| P2 | `/providers` 每次请求上游 `list_models` | 首屏慢 | 前端缓存 60s，失败降级；后端缓存留 P2 |
| P2 | 上传无进度事件 | 大文件体验差 | 前端用 XHR 进度；后端无需改 |

**门禁**：S5-pre 属于后端改动，需在 S5a 编码前单独确认。

**已完成**：CORS 中间件（`CORS_ORIGINS`）与文档列表接口均已实现，证据见 [`docs/tdd/p1-s5-pre-frontend-contract.md`](../tdd/p1-s5-pre-frontend-contract.md)。

## 10. i18n

- `src/locales/zh.ts` / `en.ts`，类型化 key（`as const` + 联合类型），缺 key 编译期报错。
- 默认中文，持久化 `localStorage.language`；切换时更新 `<html lang>` 与 `Intl` 格式。
- 文案规则：不拼接句子；数量用 `{count}` 占位；日期用 `Intl.DateTimeFormat(locale)`；token 数用千分位。
- 测试：Vitest 断言 zh/en key 集合完全一致。
- 技术术语保留英文：`API Key`、`token`、`Provider`、`SSE`、模型名。

## 11. 可访问性与响应式

- 语义 landmark（`nav/main/aside`）；对话框焦点陷阱与 Esc 关闭（Key 一次性弹窗除外）。
- 流式完成时用 `aria-live="polite"` 播报“回答完成”，不逐 token 播报。
- 对比度 ≥ 4.5:1；焦点环 `2px accent`；图表提供表格替代（用量页本身有明细表）。
- 断点：`sm 640 / md 768 / lg 1024 / xl 1280`。
  - ≥1280：侧栏 + 对话 + 引用三栏。
  - 1024–1279：引用变 Sheet。
  - <1024：侧栏抽屉，对话单列，输入框贴底。
- 触控目标 ≥ 40px；移动端隐藏 hover-only 操作，改为菜单。

## 12. 性能

- 路由级 `React.lazy`；首屏目标 < 300KB gzip。
- 流式期间纯文本渲染，结束后一次 Markdown 解析。
- 会话列表 `staleTime=30s`；provider 列表 60s；文档轮询仅在有待处理项时运行。
- 长会话：消息项 `content-visibility: auto`；超过 200 条时提示归档（不做虚拟列表）。

## 13. 测试策略

| 层 | 工具 | 覆盖 |
|---|---|---|
| 单元 | Vitest | SSE 解析（分片/多行/CRLF）、刷新单飞、错误归一化、用量补零、状态码文案、i18n key 对齐 |
| 组件 | Testing Library | Composer 禁用/回车、引用抽屉、Key 一次性弹窗、文档状态 pill |
| 构建 | `npm run build` + `tsc --noEmit` | 类型与产物 |
| E2E | Playwright | 登录 → 发消息 → 看到 delta 与 done；上传 MD → 状态变 ready（需真实后端 + 模型服务） |
| CI | GitHub Actions 前端 job | lint + typecheck + unit + build；E2E 手动/定时 |

## 14. 切片与验收

| 切片 | 内容 | 验收 |
|---|---|---|
| **S5-pre** — 已完成 | CORS + 文档列表接口 + 测试 | 前端 `:5173` 可跨域登录；`GET /knowledge-bases/{id}/documents` 返回本人文档；两用户隔离 404 |
| **S5a** — 已完成（2026-11-21） | 脚手架、设计令牌、i18n、App Shell、登录/注册、刷新、对话（SSE/引用/取消/历史）、空状态 | 浏览器完成 登录 → 选模型/KB → 提问 → 引用可见 → 刷新后历史含引用；取消生成不报错 |
| **S5b** — 已完成（2026-11-21） | 知识库列表/详情、上传（进度）、状态轮询、失败原因、重试、删除 | 上传 3 种格式；失败文件显示原因并可重试；删除后表格消失 |
| **S5c** — 已完成（2026-11-21） | 用量（范围/分组/图表/明细）、API Key（创建一次性展示/吊销）、个人资料、语言切换（暗色未做） | 用量与 `curl` 聚合一致；Key 关闭后无法再看；吊销后 401 |

总计约 **6–8 天**（含 S5-pre）。

**S5 完成定义**

1. 无刷新完成 demo 全流程（注册 → 上传 → 带引用提问 → 历史 → 用量 → Key）。
2. `npm run build`、`tsc`、单测通过；1 条 Playwright 冒烟通过。
3. zh/en 文案 key 对齐，切换无遗漏。
4. 移动端（375px）关键路径可用。
5. 仓库无密钥；Key 明文只在一次性弹窗出现，不进日志/localStorage。

## 15. 风险与对策

| 风险 | 对策 |
|---|---|
| 没有 CORS，联调直接卡死 | S5-pre 先做，验收后再写 UI |
| refresh token 多标签页并发轮换导致误登出 | 单飞刷新 + `storage` 同步 + 明确提示；P2 换 httpOnly cookie |
| 流式中断后消息停留 `streaming` | 历史渲染识别 `streaming` → 标注“上次生成已中断” |
| 文档列表靠轮询打爆后端 | 2s 间隔 + 页面隐藏暂停 + 终态停止 |
| Markdown XSS | `react-markdown` 禁用 raw HTML；不引入 `dangerouslySetInnerHTML` |
| 组件库版本漂移 | 锁定 Tailwind 3.4 / shadcn 当前版本；升级单独开切片 |
| 中英文案维护成本 | key 对齐测试 + 只翻译用户可见文案，技术术语保留英文 |
| 演示环境字体/图标缺失 | 系统字体栈 + lucide 内联 SVG，不依赖 CDN |

## 16. 已确认（2026-11-21）

1. S5-pre（CORS + 文档列表接口）随本切片一起开工 —— 已完成。
2. 暗色主题不阻塞：先做浅色 + 暗色令牌变量，S5c 有余量再开开关。
3. 用量图表使用 **Recharts**。