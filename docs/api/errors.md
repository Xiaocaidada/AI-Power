# API 错误契约

所有非流式错误返回 JSON：

```json
{"detail": {"code": "quota_exceeded", "message": "Quota exceeded: workspace requests_per_minute"}}
```

部分校验错误（FastAPI/Pydantic）`detail` 为数组。跨用户/跨 workspace 的资源访问统一返回 **404**，不返回 403。

## 认证与权限

| HTTP | code | 含义 |
|---|---|---|
| 401 | — | 缺少/过期/无效 access token；过期 API Key |
| 403 | `insufficient_scope` | API Key 缺少所需 scope |
| 404 | — | 资源不存在或不属于当前 workspace（含非管理员访问 `/admin/*`） |

## 配额与限流

| HTTP | code | 附带头 |
|---|---|---|
| 429 | `quota_exceeded` | `Retry-After`、`X-Quota-Scope`、`X-Quota-Metric`、`X-Quota-Limit`、`X-Quota-Remaining`、`X-Quota-Reset` |

`scope` 为 `workspace` 或 `api_key`，`metric` 为 `requests_per_minute` / `tokens_per_day` / `api_keys`。

## 对话与模型

| code | 场景 |
|---|---|
| `provider_not_found` | 指定 provider 不存在 |
| `no_provider_available` | `auto` 路由无可用 provider（HTTP 503） |
| `provider_http_error` / `provider_unreachable` | 上游模型调用失败 |
| `provider_failed_after_start` | 流已开始后失败，不重试（SSE `error`） |
| `retrieval_failed` | 检索/embedding 失败（HTTP 502 或工具错误） |
| `agent_step_limit` | Agent 超过总步数上限（SSE `error`） |
| `tool_error` / `tool_timeout` / `invalid_arguments` | 工具执行失败 |
| `delegation_not_allowed` / `invalid_delegation` | 非法 Agent 委派 |
| `no_knowledge_base` | Agent 调 `kb_search` 但会话未绑定知识库 |

## 文档与入库

| code | 场景 |
|---|---|
| `unsupported_type` | 扩展名不在 .pdf/.md/.txt |
| `upload_too_large` / `empty_upload` | 文件过大或为空 |
| `queue_unavailable` | 入库队列不可用（文档标记 failed） |
| `too_many_pages` / `empty_document` / `parsing_failed` | 解析失败 |
| `embedding_failed` / `embedding_count_mismatch` / `embedding_dimension_mismatch` | 向量化失败 |

## SSE 事件

成功流：`meta → (citation*) → (agent_start/agent_end/tool_call/tool_result)* → delta* → usage → done`。

`error` 是终止事件，之后不会再有 `done`；已生成内容仍会保存。前端应把 `error` 当作最终状态。

## Prompt 模板

| HTTP | code | 含义 |
|---|---|---|
| 422 | `missing_variables` | 渲染缺少变量，`missing` 列出变量名 |
| 422 | `prompt_version_required` | 传了 `prompt_variables` 但没有 `prompt_version_id` |
| 404 | — | 模板/版本不存在或不在当前 workspace |

## 管理端

| HTTP | code | 含义 |
|---|---|---|
| 404 | — | 非管理员访问 `/admin/*`（隐藏接口） |
| 404 | — | 模型/workspace 不存在 |

## 通用约定

- 每个响应带 `X-Request-ID`，可与 `GET /traces/{request_id}` 对应。
- 时间均为 UTC ISO-8601；列表分页使用 `limit` + `before`（UUID 游标）。
- 流式响应 `Content-Type: text/event-stream`，禁用缓冲（`X-Accel-Buffering: no`）。