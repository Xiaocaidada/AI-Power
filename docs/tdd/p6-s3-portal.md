# P6-S3 门户与模型页面（S3a/S3b）— 实现证据

- **Date:** 2026-11-23
- **Scope:** 公开门户壳、独立模型广场/详情/体验页、控制台导航减负、设置中心。
- **计划:** [`P6 规划`](../plan/p6-plan.md)

## 1. 路由与壳

- `PortalLayout`：公开顶部导航（首页/模型广场/控制台）、登录/进入控制台、页脚。
- 公开路由：
  - `/` 首页
  - `/models` 公共模型广场
  - `/models/:slug` 模型详情
  - `/models/:slug/playground` 模型体验（RequireAuth）
- 控制台保留原 URL：`/chat`、`/chat/:id`、`/knowledge`、`/workflows`、`/collaborations`、`/evaluation`、`/usage`、`/settings/*`、`/admin`。
- 未登录访问 `/chat` 或 playground 时由 `RequireAuth` 记录回跳路径，登录后返回。

## 2. 模型页面

- `/models`：
  - 公共广场搜索、分类、能力、排序。
  - 登录后显示“我的模型”和“平台目录”标签；未登录只显示公共广场。
- `/models/:slug`：
  - Hero、详细描述、参数、能力、文档链接。
  - 调用方式：平台 API、Python SDK、OpenAI-compatible 三组可复制示例。
  - 可用时“立即体验”；不可用时引导配置 Provider。
- `/models/:slug/playground`：
  - 独立模型对话页，复用 Composer/MessageItem/CitationDrawer。
  - 首次发送创建 conversation，URL 带 `?conversation=`；刷新恢复历史。
  - 模型不可用时显示配置引导，不显示输入框。

## 3. 控制台导航

- 侧边栏分为：
  - 工作：对话、知识库
  - 构建：工作流、协作、评测
  - 账户：用量、设置、管理后台（仅管理员）
- 移除主导航中的模型广场、Prompt、API Key、Webhook、Provider 等零散入口；统一收进 `/settings` 设置中心。
- 设置中心为卡片式入口：Provider、API Key、Prompt、Webhook、Workspace、个人资料、用量。
- Logo 链接回公开首页。

## 4. 验证

```text
npm run typecheck
passed
npm test -- --run
24 passed
npm run build
built in 3.81s
npm run test:e2e
3 passed
```

后端本次无表结构变更；S3c（公告/首页运营内容/通知）仍待实现。

## 5. 已知边界

- 首页目前使用公共模型广场的推荐/最新数据；管理员 Banner/公告/推荐位与通知属于 S3c。
- 门户暂未加全局搜索与帮助文档。
- 模型详情调用示例为前端模板，不读取用户真实 Key。
- 移动端导航为基础响应式，尚未做抽屉式二级菜单。