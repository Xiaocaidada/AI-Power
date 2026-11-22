# Webhook API 参考

Webhook 是 workspace 级订阅：平台事件发生后写入投递队列，由 worker 带 HMAC 签名推送。所有管理接口仅 **workspace owner 的 JWT** 可用（API Key 不可管理 Webhook）。

## 事件

| 事件 | 触发时机 | 关键字段 |
|---|---|---|
| `message.completed` | 助手消息 finalize（含 cancelled） | `message_id`, `conversation_id`, `status`, `provider_id`, `model`, `prompt_tokens`, `completion_tokens`, `cost`, `content` |
| `document.ready` | 文档入库成功 | `document_id`, `kb_id`, `filename`, `status`, `page_count` |
| `document.failed` | 文档达到最大重试次数后失败 | 同上 + `error_code` |
| `workflow.completed` | 工作流 run 终态 | `run_id`, `workflow_id`, `status`, `error_code`, `total_ms`, `prompt_tokens`, `completion_tokens`, `cost` |
| `collaboration.completed` | 协作 run 终态 | `run_id`, `status`, `error_code`, `rounds`, `total_ms`, token/cost |
| `budget.exceeded` | workspace 当日成本首次超阈值 | `workspace_id`, `workspace_name`, `plan`, `cost_usd`, `limit_usd`, `date` |

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/webhooks` | 列表（不返回 secret） |
| POST | `/webhooks` | 创建，响应含一次性 `secret` |
| PATCH | `/webhooks/{id}` | 修改 URL / events / active |
| DELETE | `/webhooks/{id}` | 软删除并停止投递 |
| GET | `/webhooks/{id}/deliveries?limit=50` | 投递日志 |
| POST | `/webhooks/{id}/deliveries/{delivery_id}/replay` | 重放（重置为 pending） |

创建请求：

```json
{
  "url": "https://example.com/ai-power",
  "events": ["message.completed", "document.ready"]
}
```

响应：

```json
{
  "id": "…",
  "url": "https://example.com/ai-power",
  "events": ["document.ready", "message.completed"],
  "active": true,
  "secret": "whsec_…",
  "created_at": "2026-11-22T…"
}
```

`secret` 只在创建时返回，服务端用 `WEBHOOK_SECRET_KEY`（dev 下回退 JWT secret）派生的 Fernet 密钥加密存储；之后不可再次读取。

## 请求头与签名

```
Content-Type: application/json
X-AI-Power-Event: message.completed
X-AI-Power-Delivery: <delivery uuid>
X-AI-Power-Signature: t=<unix>,v1=<hex>
```

签名算法：

```text
v1 = HMAC_SHA256(secret, f"{timestamp}.{raw_body}")
```

Python 验证示例：

```python
import hashlib
import hmac
import time


def verify(secret: str, header: str, body: bytes) -> bool:
    parts = dict(item.split("=", 1) for item in header.split(","))
    timestamp = int(parts["t"])
    expected = hmac.new(
        secret.encode(), f"{timestamp}.{body.decode()}".encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(parts["v1"], expected) and abs(time.time() - timestamp) < 300
```

建议集成方：
- 用原始 body（不要重新序列化）计算签名；
- 拒绝时间戳偏差超过 5 分钟的请求（防重放）；
- 用 `X-AI-Power-Delivery` 做幂等去重；
- 在 5 秒内返回 2xx；非 2xx 会重试。

## 重试与日志

- 最多 `WEBHOOK_MAX_ATTEMPTS`（默认 5）次，退避 1m / 5m / 30m / 2h / 6h。
- 每次投递记录 `status`（`pending|delivered|failed|dead`）、`attempts`、`response_status`、`error`、`next_attempt_at`。
- worker 每分钟扫描到期投递；`dead` 后可在 UI 手动重放。
- 超时 `WEBHOOK_TIMEOUT_SECONDS`（默认 10s），不跟随重定向。

## SSRF 防护

- 仅允许 `http/https`，拒绝 URL 内嵌用户名/密码。
- 解析主机并拒绝 loopback、私网、link-local、reserved、multicast、unspecified 地址。
- 局域网演示如确需私网回调，设置 `WEBHOOK_ALLOW_PRIVATE_HOSTS=true`；仍拒绝 multicast/unspecified。
- DNS rebinding 残余风险：投递前会再次解析校验，但仍建议在可信网络内使用。

## 配置

```bash
WEBHOOK_SECRET_KEY=          # 非 dev 必填；任意字符串会派生 Fernet key
WEBHOOK_ALLOW_PRIVATE_HOSTS=false
WEBHOOK_TIMEOUT_SECONDS=10
WEBHOOK_MAX_ATTEMPTS=5
```