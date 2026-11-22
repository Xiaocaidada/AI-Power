# P6-S2 模型广场与能力 — TDD 证据

- **Date:** 2026-11-23
- **Scope:** 公共/个人双模型广场、模型能力、体验深链、KB Embedding/Reranker 选择用户 Provider。
- **计划:** [`P6 规划`](../plan/p6-plan.md)、[`模型广场 API`](../api/model-marketplace.md)

## 1. 公共模型广场

- 新表 `market_models`：slug、展示名、provider/model、分类、能力、输入/输出类型、上下文、推荐/新发布、排序、上下架、文档链接。
- 公共 API（无登录）：`GET /market/models`、`GET /market/models/{slug}`；支持搜索、分类、能力、provider、输入/输出类型与排序。
- 管理员 API：`/admin/market/models` CRUD，非管理员 404；下架后公共列表/详情不可见。
- `available` 由平台 Provider Registry 计算；不可用时前端引导配置 Provider，不提供虚假体验入口。
- Seed：`scripts/seed_market_models.py` 从平台 Provider 的模型列表幂等生成。

## 2. 个人/团队模型广场

- “我的模型”只消费 `/provider-configs/models`，不混入公共目录。
- 前端模型页三个标签：公共广场、我的模型、平台目录（保留原 `/models` 对比能力）。
- 搜索/能力/分类过滤；深链 `/chat/new?provider=...&model=...` 自动选择模型。

## 3. 能力与校验

- 用户 Provider 模型创建对话时校验：模型启用且包含 `chat`；Agent 模式要求 `tools`；否则 422。
- 新会话页对缺少 `tools` 的个人模型禁用 Agent 模式；缺少 `chat` 则不可发送。
- KB 设置新增 `embedding` / `rerank` 选择：Provider 配置 ID + 模型 ID + embedding 维度。
- 入库与检索按 KB 设置解密对应 Provider Key；跨 workspace/私用配置返回 `embedding_config_unavailable`。

## 4. 测试

后端新增：

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `tests/test_market_models.py` | 4 | 公共无登录、搜索/过滤/排序、管理员隐藏/下架、重复 409 |
| `tests/test_kb_models.py` | 3 | KB 设置持久化、Provider Embedding/Rerank、跨用户配置拒绝 |
| `tests/test_provider_configs.py` | +1 | 模型能力不支持时对话 422 |
| `tests/test_migrations.py` | 更新 | `market_models` 表字段 |

回归：

```text
.venv/Scripts/python.exe -m pytest
391 collected, 387 passed, 4 skipped
```

```text
.venv/Scripts/python.exe -m ruff check app tests scripts sdk/python alembic
All checks passed!
```

前端：typecheck、build 通过；未新增重型 Playwright（按用户要求）。

## 5. 真实部署验证（2026-11-23）

Postgres 迁移到 `b0c1d2e3f4a5 (head)`；API/worker/web 重建；`seed_market_models.py` 从平台 Provider 生成 1 条公共模型，`GET /market/models` 无登录返回且 `available=true`。

用户 Provider 真实链路：

```json
{
  "embed_sync": {"added": 1, "updated": 0, "total": 1},
  "embed_model": "bge-m3",
  "rerank_sync": {"added": 1, "updated": 0, "total": 1},
  "rerank_model": "bge-reranker-v2-m3",
  "settings_status": 200,
  "doc_status": "ready",
  "search_status": 200,
  "search_mode": "hybrid+rerank",
  "hits": 1,
  "rerank_scores": [0.794413149356842]
}
```

说明：KB 指定用户 Provider 的 Embedding/Reranker 后，入库成功，检索走 `hybrid+rerank` 并返回重排分数。

## 6. 已知边界

- 公共目录的元数据由管理员/seed 维护，不从模型文件自动推断上下文与能力。
- 公共目录价格仍以 `model_catalog` 为准；模型广场详情暂不展示价格。
- Embedding 维度固定为当前向量列 1024；选择非 1024 维模型会在入库时失败。
- 原生 Anthropic/Gemini 等协议仍未接入，继续使用 OpenAI-compatible Adapter。