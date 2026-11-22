# P6-S1 用户 Provider Hub — TDD 证据

- **Date:** 2026-11-23
- **Scope:** 用户/团队自有 Provider 配置、加密 Key、模型同步/手填、动态 Registry、对话可用。
- **计划:** [`P6 规划`](../plan/p6-plan.md)

## 1. 数据与安全

- `provider_configs`：workspace + owner、类型、Endpoint、加密 Key、掩码提示、备注、共享、状态、测试时间。
- `provider_models`：模型 ID、显示名、能力标签、来源（synced/manual）、启停。
- Key 使用 Fernet 加密（`PROVIDER_SECRET_KEY`，dev 回退 JWT）；API 只返回 `••••1234` 形式的提示，不返回明文或密文。
- 个人配置默认私有；`shared=true` 时 workspace 成员可使用但不可编辑/同步/查看 Key。

## 2. 测试

`tests/test_provider_configs.py`（8 条）：

| 用例 | 覆盖 |
|---|---|
| `test_provider_config_crud_encrypts_key` | CRUD、Key 不出现在响应、DB 中加密、掩码 |
| `test_provider_configs_are_isolated_and_shared_read_only` | 团队 workspace 共享只读、私有 404、跨用户隔离 |
| `test_provider_test_and_sync_models` | 测试连接、同步模型、个人模型列表 |
| `test_provider_test_failure_marks_status` | 失败状态与 error code |
| `test_manual_model_capabilities_and_toggle` | 手动模型、能力、启停、删除 |
| `test_invalid_provider_endpoint_is_rejected` | 非 http(s) Endpoint 422 |
| `test_chat_uses_user_provider_config` | 对话使用用户 Provider 配置 |
| `test_provider_config_not_found_is_404` | 不存在配置 404 |

迁移测试新增 `provider_configs` / `provider_models` 表与字段断言。

回归：

```text
.venv/Scripts/python.exe -m pytest
383 collected, 379 passed, 4 skipped
```

```text
.venv/Scripts/python.exe -m ruff check app tests scripts sdk/python alembic
All checks passed!
```

前端：

```text
npm test -- --run
24 passed
npm run build
built in 4.04s
```

## 3. 动态调用

- `get_scoped_registry`：平台 Provider + 当前用户私有/共享 Provider 合并，供 chat/Agent 使用。
- 工作流/协作 worker 按 run 的 workspace/user 构建同一 Registry。
- 新会话模型选择新增“我的模型”分组（`/provider-configs/models`）。
- 前端 `/settings/providers`：新增/编辑/删除、测试、同步、模型展开、手动加模型、启停、共享。

## 4. 真实部署验证（2026-11-23）

Postgres 迁移到 `f8a9b0c1d2e3 (head)`；API/worker/web 重建，`/readyz` 正常。

真实 API 使用本机 vLLM/llama.cpp Endpoint 配置 Provider：

```json
{
  "key_hint": "••••demo",
  "test": {"status": "ok", "model_count": 1, "error_code": null},
  "sync": {"added": 1, "updated": 0, "total": 1},
  "models": 1,
  "personal_models": 1,
  "chat": {"status": 200, "has_delta": true}
}
```

提交创建的响应状态为 `unknown`，测试后持久化为 `ok`；对话使用该配置流式返回。

## 5. 已知边界

- 第一期只支持 OpenAI-compatible / 自定义 Endpoint；原生 Anthropic/Gemini 等 Adapter 后补。
- KB 的 Embedding/Reranker 仍使用全局配置；P6-S2 接入用户 Provider。
- Provider 能力标签目前用于展示/手填，能力校验在 P6-S2 完整落地。
- 自定义 Endpoint 允许私网地址（满足本地部署），SSRF 风险由用户配置范围与后续白名单策略约束。