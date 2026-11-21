# 开放 API Quickstart

本文用 `curl` 与 Python 走通：注册/登录 → 上传文档 → 流式对话 → 用量与成本 → API Key。
完整错误码见 [`errors.md`](./errors.md)；交互式文档在 `http://<host>:8080/api/docs`。

## 0. Base URL

| 入口 | URL |
|---|---|
| 经 nginx（推荐） | `http://192.168.29.100:8080/api` |
| 直连 API | `http://192.168.29.100:8002` |

```bash
export BASE=http://192.168.29.100:8080/api
```

所有业务接口需要 `Authorization: Bearer <access_token>`；多 workspace 用户可加 `X-Workspace-Id`（缺省为个人 workspace）。

## 1. 注册与登录

```bash
curl -s -X POST "$BASE/auth/register" \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"S3cret!pass"}'

TOKEN=$(curl -s -X POST "$BASE/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"S3cret!pass"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -s "$BASE/auth/me" -H "Authorization: Bearer $TOKEN"
```

access token 30 分钟；用 `POST /auth/refresh`（一次性轮换）续期。

## 2. 知识库与文档

```bash
KB=$(curl -s -X POST "$BASE/knowledge-bases" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Demo KB"}' | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

curl -s -X POST "$BASE/knowledge-bases/$KB/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -F 'file=@./note.txt'

# 轮询状态，ready 后可检索
curl -s "$BASE/knowledge-bases/$KB/documents" -H "Authorization: Bearer $TOKEN"
```

## 3. 流式对话（SSE）

```bash
# 查看可用模型；provider_id="auto" 走路由
curl -s "$BASE/models" -H "Authorization: Bearer $TOKEN"

CONV=$(curl -s -X POST "$BASE/conversations" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"provider_id\":\"auto\",\"model\":\"auto\",\"kb_id\":\"$KB\",\"agent\":false}" \
  | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

curl -N -X POST "$BASE/conversations/$CONV/messages" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"content":"这份资料的核心结论是什么？"}'
```

响应是 `text/event-stream`：

```
event: meta
data: {"message_id":"...","provider":"local-qwen","model":"...","conversation_id":"..."}

event: citation
data: {"index":1,"document_id":"...","chunk_id":"...","page_no":1,"snippet":"..."}

event: delta
data: {"text":"核心结论"}

event: usage
data: {"prompt_tokens":120,"completion_tokens":80}

event: done
data: {"finish_reason":"stop"}
```

- `agent: true` 时会出现 `agent_start` / `agent_end` / `tool_call` / `tool_result`。
- `error` 是终止事件；已生成内容仍会保存。
- 429 响应带 `Retry-After` 与 `X-Quota-*`。

### Python（httpx）流式读取

```python
import json

import httpx

BASE = "http://192.168.29.100:8080/api"
TOKEN = "<access_token>"
CONVERSATION_ID = "<conversation_id>"

with httpx.stream(
    "POST",
    f"{BASE}/conversations/{CONVERSATION_ID}/messages",
    headers={"Authorization": f"Bearer {TOKEN}"},
    json={"content": "用一句话总结"},
    timeout=180,
) as response:
    response.raise_for_status()
    event = None
    for line in response.iter_lines():
        if line.startswith("event: "):
            event = line[len("event: ") :]
        elif line.startswith("data: "):
            payload = json.loads(line[len("data: ") :])
            if event == "delta":
                print(payload["text"], end="", flush=True)
            elif event == "error":
                raise RuntimeError(payload)
            elif event == "done":
                print()
                break
```

## 4. 用量与成本

```bash
curl -s "$BASE/usage/summary?group_by=day" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/usage/cost?group_by=model" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/usage/quota" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/traces?limit=10" -H "Authorization: Bearer $TOKEN"
```

成本按请求写入时的模型价格快照计算（USD，6 位小数）；未定价模型计 0 并计入 `unpriced_requests`。

## 5. 用 API Key 调用

```bash
KEY=$(curl -s -X POST "$BASE/api-keys" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"script","scopes":["chat:write","kb:read"]}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["key"])')

# 明文只返回一次；之后只存 SHA-256
curl -s "$BASE/conversations" -H "X-API-Key: $KEY"
```

API Key 绑定创建时的 workspace；可用 `expires_at` 与 `rate_limit_per_minute` 限制。Key 管理、上传、删除、用量、Prompt 模板与管理端仅支持 JWT。

## 6. Prompt 模板与 Agent（可选）

```bash
# 创建模板 + 渲染
TPL=$(curl -s -X POST "$BASE/prompt-templates" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Support","system_prompt":"You are {{tone}}. Answer in {{language}}."}')
TPL_ID=$(echo "$TPL" | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')
VER_ID=$(echo "$TPL" | python -c 'import json,sys; print(json.load(sys.stdin)["versions"][0]["id"])')

# 会话绑定模板（服务端渲染并快照）
curl -s -X POST "$BASE/conversations" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"provider_id\":\"auto\",\"model\":\"auto\",\"agent\":true,
       \"prompt_version_id\":\"$VER_ID\",
       \"prompt_variables\":{\"tone\":\"concise\",\"language\":\"Chinese\"}}"
```

## 7. 分页与请求追踪

- 列表：`?limit=20&before=<last_id>`，按 id 倒序；返回不足 `limit` 即无下一页。
- 每个响应带 `X-Request-ID`；用 `GET /traces/{request_id}` 查看检索/首 token/总耗时与工具调用。
- 时间参数为 UTC ISO-8601（`from` / `to`）。

## 8. 常见问题

| 现象 | 排查 |
|---|---|
| 401 | token 过期（30 分钟），用 refresh token 续期 |
| 403 `insufficient_scope` | API Key 缺少 `chat:write` / `kb:read` |
| 429 | 查看 `Retry-After` 与 `X-Quota-*`；等待或改用 pro workspace |
| 503 `no_provider_available` | `/models` 检查 provider 健康/熔断状态 |
| 404 | 资源属于其他用户/workspace（统一 404） |