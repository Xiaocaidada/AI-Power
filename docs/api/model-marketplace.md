# 模型广场 API

P6 有两个数据源：

- **公共模型广场**：管理员维护的系统支持模型，未登录可浏览。
- **我的模型**：当前用户/workspace 的 Provider 同步或手填的模型，需要登录。

## 公共广场（无需登录）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/market/models` | 已上架模型列表 |
| GET | `/market/models/{slug}` | 模型详情 |

查询参数：`search`、`category`、`capability`、`provider_id`、`input_type`、`output_type`、`sort=featured|new|name`。

```bash
curl -s "$BASE/market/models?category=coding&capability=tools&sort=featured"
```

响应字段：

```json
{
  "slug": "local-qwen-qwen2-5",
  "name": "Qwen2.5 7B Instruct",
  "provider_id": "local-qwen",
  "provider_name": "Local Qwen",
  "model_id": "…",
  "description": "…",
  "category": "general",
  "capabilities": ["chat", "stream"],
  "input_types": ["text"],
  "output_types": ["text"],
  "context_window": 32768,
  "max_output": null,
  "featured": true,
  "is_new": false,
  "available": true
}
```

`available` 表示平台当前是否配置了对应提供商。不可用时，前端展示“配置提供商”，不提供虚假的体验入口。

## 管理员维护

需要 `users.role=admin`；非管理员访问返回 404。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/admin/market/models` | 全部模型（含下架） |
| POST | `/admin/market/models` | 新增 |
| PATCH | `/admin/market/models/{id}` | 编辑/上下架 |
| DELETE | `/admin/market/models/{id}` | 删除 |

`market_models` 与平台路由/价格表 `model_catalog` 分离：前者负责展示元数据，后者负责实际调用价格与启停。

### Seed

从平台 Provider 的 `/models` 同步生成公共目录：

```bash
docker compose cp scripts/seed_market_models.py api:/tmp/seed_market_models.py
docker compose exec -T api python /tmp/seed_market_models.py
```

脚本按 slug 幂等；已存在的条目不覆盖管理员编辑内容。

## 我的模型（需登录）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/provider-configs/models` | 当前用户/共享 Provider 的启用模型 |

前端“我的模型”标签只消费这个接口；它不会把公共目录混入个人模型。

## 能力与体验

- 能力标签：`chat/stream/tools/vision/file/structured/reasoning/long_context/embedding/rerank`。
- 对话创建校验：用户 Provider 模型必须启用且包含 `chat`（Agent 模式要求 `tools`），否则 422。
- 模型详情/卡片可跳转 `/chat/new?provider=<id>&model=<model_id>`；新会话页自动选中对应模型。
- KB 设置可选择带 `embedding` / `rerank` 能力的用户模型；未选择时使用平台默认服务。