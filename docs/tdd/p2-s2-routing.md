# TDD Evidence — P2-S2: 模型目录、广场与路由降级

- **Date:** 2026-11-21
- **Scope:** `model_catalog`、`/models`、`/models/compare`、`auto` 路由、首 token 前降级、Redis 熔断
- **Source:** [`docs/plan/p2-plan.md`](../plan/p2-plan.md) S2
- **Test runner:** pytest（Python 3.13）+ 真实 Postgres / 本机 Qwen

## User Journeys

1. 作为用户，我能看到目录中的模型、上下文、价格、标签与可用状态。
2. 作为用户，我能并排对比 2–3 个模型。
3. 作为用户，我选择 `auto` 后，系统按优先级选择健康 provider。
4. 作为用户，首选 provider 在首 token 前失败时，回答由下一个 provider 完成。
5. 作为用户，所有 provider 不可用时会得到明确的 503。
6. 作为维护者，连续失败的 provider 会短暂从可用列表中移除。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 单测 | `pytest tests/test_models.py` | `5 passed` |
| 全量 | `pytest` | **214 passed, 3 skipped** |
| 覆盖率 | `pytest --cov=app` | **TOTAL 94%** |
| Lint / Format | `ruff check` / `ruff format --check` | 通过 |

> 本片测试与实现同批完成，未保留独立 RED 输出；测试覆盖目录、对比、降级、全失败与熔断。

## 真实环境验证

```
alembic 0006 应用（api 容器启动）
seed_models.py → provider local-qwen: 1 models；catalog: 1 new rows
GET /models                    → 200 [("local-qwen", "...qwen2.5-7b...gguf", available=True)]
GET /models/compare?ids=<id>   → 200
GET /models/compare?ids=nope   → 404 model_not_found
POST /conversations auto/auto  → 201
POST .../messages（SSE）        → 200，meta.provider=local-qwen，meta.model=<实际模型>
```

本机只有 `local-qwen` 一个可用 provider（DeepSeek 无密钥），因此真实环境只能验证单 provider 路由；双 provider 降级由单测覆盖。

## Test Specification（5）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 目录只返回启用模型，含标签与可用状态；compare 返回选中项 | `test_models_lists_catalog_and_compare` | PASS |
| 2 | 首选 provider 首 token 前失败 → 自动切换下一个并返回其 meta/delta | `test_auto_falls_back_to_next_provider` | PASS |
| 3 | 全部 provider 失败 → 503 `no_provider_available` | `test_auto_returns_503_when_all_providers_fail` | PASS |
| 4 | 连续 3 次失败后 `/models` 标记不可用 | `test_circuit_breaker_marks_provider_unavailable` | PASS |
| 5 | 未知模型 ID → 404 `model_not_found` | `test_compare_rejects_unknown_ids` | PASS |

## 关键实现

- **目录**：`model_catalog(provider_id, model_id)` 唯一；`priority` 决定 `auto` 顺序；`enabled` 控制上架。目录为空时回退到实时 `/providers` 结果，保证可用性。
- **熔断**：Redis 计数 `circuit:provider:<id>`，3 次失败后 60s 内跳过；成功即清零。Redis 故障时 fail-open。
- **降级**：`auto` 在创建会话时保存为 `auto/auto`；发送时解析候选，逐个打开流并读取首个 chunk，失败则记录并尝试下一个。首 token 之后失败不重试，按 SSE `error` 终止。
- **消息审计**：消息记录实际 provider/model，便于历史回放与用量统计。
- **对比**：最多 5 个，返回顺序与请求一致；缺失 ID 整体 404。

## Known Gaps

- **真实双 provider 降级未现场演示**：需 DeepSeek 密钥或第二个本地 provider。
- **目录元数据需人工维护**：价格/上下文/标签通过种子脚本默认值，未做管理端。
- **熔断为全局 provider 维度**：不区分 workspace/模型。
- **`/providers` 仍保留**：实时上游列表与目录并存，前端在 S5 切到 `/models`。
- **无模型级配额/路由策略**：P2-S3 配额按 workspace + Key，不做按模型。
- **目录为空时回退实时列表**：会调用上游 `list_models`，增加首屏延迟。
- **前端尚未展示广场/对比**：S5。