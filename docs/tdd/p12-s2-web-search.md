# P12-S2 网页搜索多 Provider

日期：2026-11-24
状态：已完成（网页搜索 MVP）

## 目标

把 P12-S1 的 `web_search` 模式接入真实搜索 Provider，同时保证：

- 没有配置 Provider 时明确失败，不发外部请求。
- 搜索、来源引用、结果持久化与刷新回放完整。
- 外部搜索在测试中全部 mock，不依赖真实 Key。
- 不伪造搜索结果或来源。

## 实现

### 数据

- `search_provider_configs`：
  - `provider`: `tavily|brave|serper|searxng`
  - `workspace_id`、`owner_user_id`、`name`、`base_url`
  - `api_key_encrypted`、`api_key_hint`（复用 Fernet 加密）
  - `max_results`、`timeout_seconds`、`enabled`、`shared`、`is_default`
  - `status`、`last_error`、`last_tested_at`
  - 软删除 `deleted_at`
- `message_web_sources`：
  - `message_id`、`citation_index`、`title`、`site`、`url`、`snippet`
  - `published_at`、`provider`、`provider_config_id`、`retrieved_at`
- 迁移：`e6f7a8b9c0d1_p12_s2_web_search.py`。

### 搜索适配器

`app/services/web_search.py`：

- Tavily：`POST /search`，`api_key` 放在请求体。
- Brave：`GET /res/v1/web/search`，`X-Subscription-Token`。
- Serper：`POST /search`，`X-API-KEY`。
- SearXNG：`GET {base_url}/search?format=json`，不需要 Key。
- 错误码：`search_not_configured`、`search_invalid_endpoint`、`search_auth_failed`、
  `search_rate_limited`、`search_timeout`、`search_unreachable`、`search_invalid_response`、
  `search_upstream_error`。
- 查询生成：确定性启发式，去除常见前缀、按行/分句拆分、去重，最多 3 条查询。
- 多轮搜索：主查询失败直接报错；后续查询失败保留已有结果；按 URL 去重。
- 搜索提示：`<web_search_results>` 明确标记为不可信外部数据，要求 `[n]` 引用，禁止编造 URL。

### API

- `GET/POST /search-providers`
- `PATCH/DELETE /search-providers/{id}`
- `POST /search-providers/{id}/test`
- `POST /search-providers/{id}/default`
- Key 永不明文返回；跨用户/跨工作区统一 404。

### 聊天执行

- `web_search` 模式在 `validate_turn_mode` 中可执行。
- 每次请求记录实际搜索 Provider：
  - `messages.mode_meta.search_provider_id`
  - `message_web_sources.provider` / `provider_config_id`
- SSE 增量事件：
  - `stage`: `searching | answering | search_failed`
  - `web_source`: 单条来源
- 搜索在 LLM 调用前执行；搜索失败时发送终端 `error`，消息标记 `failed`，不产生伪回答。
- 搜索结果来源持久化，刷新后通过 `GET /conversations/{id}` 回放。
- 网页搜索模式不叠加知识库 RAG；知识库 + 网页混合留待后续。
- 重新生成会重新执行搜索；前端停止会取消请求。

### 前端

- `/settings/search`：Provider 列表、创建/编辑/删除、测试连接、设为默认、共享/启用。
- 新建会话与会话页：网页搜索模式显示 Provider 选择器；没有 Provider 时禁用发送并链接配置页。
- 消息区实时展示搜索阶段与来源；完成后在回答下方展示网页来源列表，点击新窗口打开。

## 测试

- 后端 `tests/test_p12_s2_web_search.py`：
  - 四种适配器的 mock HTTP 解析。
  - 401 → `search_auth_failed`。
  - Provider CRUD、Key 掩码、默认、SearXNG 免 Key、跨用户 404。
  - 测试连接 mock。
  - 无 Provider → `422 search_not_configured`。
  - 成功 SSE：`meta → stage → web_source* → stage → delta* → usage → done`。
  - 来源持久化与详情回放。
  - 搜索失败 → `meta → stage → stage → error`，消息 `failed`。
  - 查询生成去重。
- 全量验证：`ruff check .`、`pytest -n auto`、`npm run typecheck`、`npm test -- --run`、
  `npm run build`。

## 边界

已解决：

- Provider 未配置、Key 缺失、上游失败均有类型化错误。
- 搜索来源持久化、刷新回放、跨租户隔离。
- 测试不联网；不伪造搜索结果。
- 外部网页内容作为不可信数据注入，不执行其中的指令。

后续切片：

- 多 Provider 并发聚合、排序融合：后续增强。
- 知识库 + 网页混合检索：后续切片。
- 搜索成本配额、每 Provider 并发/日限额：需要与计费策略一起设计。
- 报告导出包含网页来源：P12-S4 成果复用。
- SearXNG 自定义 Base URL 与现有 Provider 配置一致，可指向内网；更严格的 SSRF 白名单
  需要单独的运维/安全决策。

明确不做（真实外部集成）：

- 本切片不内置任何真实搜索 Key；上线验证需要用户自行配置 Tavily/Brave/Serper Key 或
  SearXNG 地址。
- 不抓取搜索引擎结果页、不绕过登录/付费墙。
- 图片生成、语音、OAuth 应用不在本切片。

需要用户决策：

- 是否允许 SearXNG 指向内网地址（当前允许，与现有 Provider 配置一致）。
- 搜索 Provider 的日限额/成本配额策略。