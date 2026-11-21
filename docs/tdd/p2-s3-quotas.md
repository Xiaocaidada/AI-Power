# TDD Evidence — P2-S3: 配额与限流

- **Date:** 2026-11-21
- **Scope:** workspace 请求/分钟、token/天、API Key 限流与数量上限、Key 过期
- **Source:** [`docs/plan/p2-plan.md`](../plan/p2-plan.md) S3
- **Test runner:** pytest（Python 3.13）+ 真实 Postgres / Redis / 本机 Qwen

## User Journeys

1. 作为用户，我在 workspace 请求超限时收到 429，并能从响应头看到限额与重置时间。
2. 作为用户，我在当日 token 用尽后无法继续发送消息。
3. 作为 Key 持有者，单个 Key 的每分钟请求数受限，不影响 workspace 内其他 Key。
4. 作为 owner，我受 workspace 计划的 Key 数量上限约束。
5. 作为用户，我创建的 Key 到期后立即失效。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 单测 | `pytest tests/test_quotas.py` | `5 passed` |
| 全量 | `pytest` | **219 passed, 3 skipped** |
| 覆盖率 | `pytest --cov=app` | **TOTAL 94%** |
| Lint / Format | `ruff check` / `ruff format --check` | 通过 |

## 真实环境验证

```
并发两个 Key 请求（key rate_limit=1）
  → 一个 200；另一个 429，X-Quota-Scope=api_key，Retry-After=45
创建 Key（free 计划上限 5，已含 1 个限流 Key）
  → 前 4 个 201，第 5 个 429（metric=api_keys）
DB 将 Key 的 expires_at 改为 1 分钟前
  → 使用该 Key 访问 /knowledge-bases → 401
```

workspace 请求/分钟与 token/天通过单测覆盖（真实默认值较高，未现场打满）。

## Test Specification（5）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | workspace 请求超限 → 429 + 配额响应头 | `test_workspace_request_quota_returns_429_with_headers` | PASS |
| 2 | 日 token 超限 → 429（metric=tokens_per_day） | `test_daily_token_quota_blocks_further_messages` | PASS |
| 3 | Key 级每分钟限制独立生效 | `test_api_key_rate_limit_applies_per_key` | PASS |
| 4 | workspace Key 数量上限 | `test_workspace_key_limit_blocks_creation` | PASS |
| 5 | 过期 Key → 401 | `test_expired_key_is_rejected` | PASS |

## 关键实现

- **计划限额**（`Settings`）：free 60 req/min、200k token/天、5 Key；pro 600 req/min、5M token/天、50 Key。
- **Redis 计数**：`quota:req:ws:<id>:<minute>`、`quota:req:key:<id>:<minute>`、`quota:tokens:ws:<id>:<date>`；请求窗口 120s、token 窗口 2 天。
- **入口**：发送消息与上传文档前检查；Key 创建时检查数量。Redis 故障时 fail-open 并记 warning。
- **429 响应**：`code=quota_exceeded`、`scope/metric`，并带 `Retry-After`、`X-Quota-Scope/Metric/Limit/Remaining/Reset`。
- **token 计费**：流结束（含取消/失败）按实际 usage 累加，NULL usage 记 0。
- **Key**：`expires_at` 与 `rate_limit_per_minute` 可选项；过期在认证阶段拒绝。

## Known Gaps

- **token 配额是事后计费**：单条消息可能让用量超过上限（检查发生在发送前）。
- **计划仅静态配置**：无 API/管理端切换 free/pro，需改库或配置。
- **无配额查询接口**：前端 S5 需要剩余额度时需新增 `/usage/quota`。
- **上传只计入请求数**：不计 token。
- **Redis 故障 fail-open**：限流可能暂时失效。
- **配额按 workspace**：无成员维度限额；Key 限额仅对 Key 请求生效。
- **前端未展示配额**：S5。