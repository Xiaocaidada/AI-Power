# 项目与会话工作区 API

项目是 workspace 级资源，成员可见可用；创建者或 workspace owner 可编辑/归档。跨 workspace 一律 `404`。

## 1. 项目

### `GET /projects?archived=false`

返回项目列表，含未归档会话数：

```json
[
  {
    "id": "…",
    "name": "Research",
    "description": "Deep dives",
    "instructions": "Be concise",
    "default_provider_id": "fake",
    "default_model": "fake-model",
    "default_kb_id": null,
    "default_agent": false,
    "archived": false,
    "conversation_count": 3,
    "owned": true,
    "created_at": "…",
    "updated_at": "…"
  }
]
```

### `POST /projects`

```json
{
  "name": "Research",
  "description": "Deep dives",
  "instructions": "Be concise",
  "default_provider_id": "fake",
  "default_model": "fake-model",
  "default_kb_id": null,
  "default_agent": false
}
```

- `default_provider_id=auto` 时 `default_model` 固定为 `auto`。
- 非 auto 的 provider/model 必须存在且具备 `chat`（`default_agent=true` 时为 `tools`）能力，否则 `404/422`。
- `default_kb_id` 必须属于当前 workspace 且未删除。
- 只有 owner/创建者可 `PATCH`/`DELETE`；其他成员可见但编辑返回 `403`。

### `PATCH /projects/{id}`

可更新名称、描述、指令、默认 Provider/模型/KB/Agent，以及 `"archived": true|false`。默认配置变更写 `audit_logs`。

### `DELETE /projects/{id}`

软归档项目，不级联删除会话。

## 2. 会话列表与搜索

### `GET /conversations`

| 参数 | 说明 |
|------|------|
| `limit` / `before` | 现有游标分页 |
| `q` | 标题或消息内容模糊搜索（`%`/`_` 已转义） |
| `project_id` | UUID，或 `none` 表示未归属项目 |
| `archived` | `false`（默认）/`true`/`all` |
| `pinned` | `true`/`false`，可选 |

排序：置顶优先，其次按会话 ID 倒序。

### `PATCH /conversations/{id}`

```json
{
  "title": "New title",
  "pinned": true,
  "project_id": "…",
  "archived": false,
  "provider_id": "fake",
  "model": "fake-model",
  "generation_settings": { "temperature": 0.7, "max_tokens": 1024, "top_p": 0.9 }
}
```

- `project_id: null` 表示移出项目。
- `archived: true` 软归档；`false` 恢复。
- Provider/模型切换只影响后续消息，历史消息保留各自 attribution。
- 生成参数白名单与范围：`temperature` 0–2，`max_tokens` 1–32768，`top_p` 0–1；越界自动 clamp，未知键忽略。

### `POST /conversations/batch`

```json
{
  "action": "archive | unarchive | move",
  "conversation_ids": ["…"],
  "project_id": "…"
}
```

最多 100 条，全部必须属于当前 workspace；任一条不存在返回 `404`，不会部分更新。

## 3. 项目内新会话继承

`POST /conversations` 支持：

```json
{ "project_id": "…", "prompt_version_id": "…", "prompt_variables": {} }
```

继承顺序：

1. 请求显式字段；
2. 项目默认 Provider/模型/KB/Agent；
3. 系统默认（`auto` / 无 KB / 非 Agent）。

项目 `instructions` 在创建会话时与 Prompt 模板结果合并写入 `system_prompt` 快照；之后修改项目不影响历史会话。

## 4. 重新生成

### `POST /conversations/{id}/messages/{message_id}/regenerate`

- `message_id` 必须是该会话中 `assistant` 且状态为 `completed`/`cancelled` 的消息。
- 使用该回答之前的最近一条用户消息重跑完整链路（RAG/Agent/Provider/配额/用量）。
- SSE 契约与发送消息一致：`meta → citation* → delta* → usage → done`。
- 新 assistant 消息通过 `reply_to_message_id` 指向旧回答；旧回答保留。
- 旧回答不进入新请求上下文，避免自我引用。

## 5. 消息反馈

### `PUT /messages/{message_id}/feedback`

```json
{ "rating": "up | down", "reason": "optional" }
```

同一用户对同一消息只有一条反馈，重复 PUT 为更新。

### `DELETE /messages/{message_id}/feedback`

取消当前用户反馈，返回 `204`。

会话详情会返回当前用户反馈：

```json
{
  "messages": [
    { "id": "…", "feedback": { "rating": "up", "reason": "useful" } }
  ]
}
```

反馈按 `(message_id, user_id)` 唯一；同一 workspace 的其他用户看到的是各自反馈。跨 workspace 返回 `404`。

## 6. 安全与边界

- 项目/会话/消息均按 `workspace_id` 过滤，跨租户 `404`。
- 项目编辑/归档仅创建者或 workspace owner；成员只读。
- 反馈只允许 assistant 且已完成/已取消消息。
- 重新生成是新的计费调用，每次写一条 `usage_events`。
- 附件上传/多模态不在本切片；前端仅保留占位入口。