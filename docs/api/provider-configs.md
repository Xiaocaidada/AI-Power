# 用户 Provider 配置 API

用户/团队可接入自己的 OpenAI-compatible 模型服务。所有接口仅支持 JWT；跨 workspace 或非本人私有配置一律 404。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/provider-configs` | 我的 + 当前 workspace 共享配置 |
| POST | `/provider-configs` | 新建配置 |
| GET | `/provider-configs/{id}` | 详情（含掩码 Key） |
| PATCH | `/provider-configs/{id}` | 修改名称/Endpoint/Key/备注/共享 |
| DELETE | `/provider-configs/{id}` | 软删除 |
| POST | `/provider-configs/{id}/test` | 测试连接 |
| POST | `/provider-configs/{id}/sync` | 同步模型列表 |
| GET | `/provider-configs/{id}/models` | 模型列表 |
| POST | `/provider-configs/{id}/models` | 手动添加模型 |
| PATCH | `/provider-configs/{id}/models/{model_pk}` | 修改能力/启停/显示名 |
| DELETE | `/provider-configs/{id}/models/{model_pk}` | 删除模型 |
| GET | `/provider-configs/models` | 可用的我的/共享模型（对话选择器） |

## 创建

```json
{
  "name": "My DeepSeek",
  "provider_type": "openai_compatible",
  "base_url": "https://api.deepseek.com/v1",
  "api_key": "sk-...",
  "note": "",
  "shared": false
}
```

`provider_type` 支持 `openai_compatible` / `custom`（自定义 Endpoint 也按 OpenAI 兼容协议调用）。

响应永远不会包含明文或密文 Key，只返回掩码：

```json
{
  "id": "…",
  "api_key_hint": "••••1234",
  "status": "unknown",
  "owned": true,
  "model_count": 0
}
```

## 测试与同步

```bash
curl -s -X POST "$BASE/provider-configs/$ID/test" -H "Authorization: Bearer $TOKEN"
# {"status":"ok","model_count":3,"error_code":null}

curl -s -X POST "$BASE/provider-configs/$ID/sync" -H "Authorization: Bearer $TOKEN"
# {"added":3,"updated":0,"total":3}
```

同步按 `(config_id, model_id)` upsert，不覆盖已手动修改的能力/启停状态。

## 模型能力

`capabilities` 允许值：`chat`、`stream`、`tools`、`vision`、`file`、`structured`、`reasoning`、`long_context`、`embedding`、`rerank`。同步模型默认 `chat, stream`；用户可手动调整。

## 使用

新会话的模型选择器会将“我的模型”作为独立分组；选择后 `provider_id` 为 Provider 配置 ID，`model` 为模型 ID。工作流/协作 worker 也会按 run 的 workspace/user 构建同一套 Provider。

## 安全

- Key 使用 `PROVIDER_SECRET_KEY` 派生 Fernet 密钥加密；非 dev 必须配置。
- 共享配置只读：成员可使用模型，但不能编辑、删除、测试或同步。
- 自定义 Endpoint 允许私网地址以支持本地部署；生产环境建议增加出站白名单。