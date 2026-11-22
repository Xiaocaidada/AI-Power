# P6 演示走查（门户 → 模型 → 项目 → Agent → 插件 → 控制台）

以下步骤基于 LAN 部署：Web `http://192.168.29.100:8080`，API `http://192.168.29.100:8002`。

## 1. 公开门户

1. 打开 `/`：无需登录即可浏览 Banner、推荐/活动、公告与模型卡片。
2. 输入问题并点击“开始对话”：未登录跳转 `/login`，登录后回到新会话。
3. 打开 `/models`：搜索/筛选模型；进入 `/models/:slug` 查看参数与三种调用示例。
4. 打开 `/announcements`：查看公告列表与详情；登录后进入详情自动标记已读。

## 2. Provider 与模型

1. `/settings/providers`：新增 OpenAI-compatible Provider，测试连接并同步模型。
2. `/models` 的“我的模型”标签展示自己的 Provider 模型；平台目录仍可对比。
3. 新建会话时选择“我的模型”，模型能力标签会限制 Agent 模式。

## 3. 项目与会话

1. `/projects`：创建项目，设置默认模型/KB/Agent 与项目指令。
2. 项目卡片“在项目中新建会话”：新会话继承默认配置，指令在创建时快照。
3. 聊天侧栏：搜索会话、项目过滤、置顶、重命名、归档/恢复、移动到项目。
4. 聊天页“会话设置”：切换模型/Provider、设置 temperature/max tokens/top P。
5. assistant 消息可“重新生成”或点赞/点踩；`/archive` 可恢复归档会话。

## 4. Agent 广场

1. `/agents`：浏览内置 Agent，创建自定义 Agent（指令、默认模型/KB、工具、插件）。
2. 自定义 Agent 设为“Workspace 共享”后，其他成员可见但只读。
3. 点击“立即体验”：新会话使用该 Agent 的默认配置；执行过程在消息下方展示。
4. Agent 详情页可查看执行历史。

## 5. 插件

1. 管理员在 `/admin/plugins` 新建 HTTP 插件（Endpoint、GET/POST、参数 Schema、敏感标记）。
2. Workspace owner 在 `/plugins` 启用插件并按需填写凭据。
3. 新会话选择 Agent 模式与插件；敏感插件需勾选确认。
4. 对话中插件调用以 `tool_call/tool_result` 展示；`/plugins` 底部可查看调用记录。
5. 未确认的敏感插件不会发起请求，返回 `plugin_confirmation_required`。

## 6. 控制台与辅助

1. `/dashboard`：查看 Provider/模型/会话/项目/KB/Agent/插件/未读通知与近 30 天用量。
2. `/files`：跨 KB 搜索文档、查看状态并下载原文件。
3. `/search`：跨会话、项目、Agent、提示词、KB、文件搜索。
4. `/settings/prompts`：按分类/关键词搜索，星标收藏，一键“在对话中使用”。
5. `/usage`：查看平台账本用量；页面提示第三方 Provider 账单可能不同。

## 7. 管理员

1. `/admin`：用户、工作区、模型、全局用量、审计。
2. `/admin/content`：首页运营位与公告发布/定时/过期。
3. `/admin/plugins`：平台级插件定义。
4. `/admin/market/models`（API）：公共模型广场目录。