# TDD Evidence — P2-S1: 多租户数据模型与隔离

- **Date:** 2026-11-21
- **Scope:** Workspace/成员、`workspace_id` 迁移、`X-Workspace-Id`、跨租户 404、API Key 绑定 workspace
- **Source:** [`docs/plan/p2-plan.md`](../plan/p2-plan.md) S1
- **Test runner:** pytest（Python 3.13）；SQLite 单测 + 真实 Postgres 迁移

## User Journeys

1. 作为新用户，注册后自动拥有个人 workspace，现有页面无需改动即可使用。
2. 作为 owner，我能创建团队 workspace 并按邮箱邀请已注册用户。
3. 作为成员，我能看到团队共享的知识库/会话/文档。
4. 作为非成员，我访问他人 workspace 一律 404。
5. 作为 owner，我能移除成员，成员立即失去访问。
6. 作为 API Key 使用者，Key 只能访问其所属 workspace，指定其他 workspace 返回 404。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| RED | `pytest tests/test_workspaces.py` | `6 failed`（`/workspaces` 404、无 workspace 上下文） |
| GREEN | `pytest tests/test_workspaces.py` | `7 passed` |
| 全量 | `pytest` | **209 passed, 3 skipped** |
| 覆盖率 | `pytest --cov=app` | **TOTAL 95%** |
| Lint / Format | `ruff check` / `ruff format --check` | 通过 |

**实现范围**：`workspaces`/`workspace_members` 模型与迁移、认证上下文（workspace + role）、workspace 路由、所有资源按 `workspace_id` 过滤、API Key 绑定 workspace、评测脚本改为 workspace。

## 真实 Postgres 迁移验证

```
docker compose up -d --build api   # alembic upgrade head
users=17  workspaces=17  members=17
kb_null=0 conv_null=0 doc_null=0 chunk_null=0 usage_null=0 key_null=0
```

每个历史用户都获得个人 workspace 与 owner 成员关系，全部资源完成回填。

## 真实 API 端到端（`http://192.168.29.100:8080/api`）

```
注册后 GET /workspaces                → 个人 workspace，is_personal=true，role=owner
创建 E2E Team                         → 201，role=owner
邀请 member 邮箱                      → 201
member GET /workspaces                → 个人 workspace + E2E Team(role=member)
owner 在团队创建知识库                 → 201
member 用 X-Workspace-Id 列表          → ["Team KB"]
outsider 指定该 workspace              → 404
member 不带 header（个人）             → []
团队 API Key 不带 header 列表           → ["Team KB"]
同一 Key + 个人 workspace header       → 404
移除成员                               → 204
被移除成员再访问团队                    → 404
```

## Test Specification（7）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 注册自动创建个人 workspace（owner/free） | `test_registration_creates_personal_workspace` | PASS |
| 2 | 团队成员可见共享知识库 | `test_shared_workspace_resources_are_visible_to_members` | PASS |
| 3 | 跨 workspace 访问 404 | `test_cross_workspace_access_returns_404` | PASS |
| 4 | 非成员不能选择 workspace | `test_non_member_cannot_select_workspace` | PASS |
| 5 | 移除成员后失去访问 | `test_removed_member_loses_workspace_access` | PASS |
| 6 | API Key 绑定 workspace，冲突 header 404 | `test_api_key_is_bound_to_its_workspace` | PASS |
| 7 | 用量按 workspace 隔离 | `test_usage_is_scoped_to_workspace` | PASS |

## 关键设计

- **资源归属**：`knowledge_bases/conversations/documents/chunks/ingestion_jobs/usage_events/api_keys` 均带 `workspace_id`；`user_id` 保留为创建者审计字段。
- **默认租户**：无 `X-Workspace-Id` 时使用个人 workspace；注册与迁移都会创建个人 workspace。
- **认证**：`AuthContext = user + workspace + role + scopes`；JWT 读 header，API Key 使用自身 workspace。
- **角色**：`owner` 可邀请/移除；`member` 只读成员列表。移除 owner 返回 409。
- **唯一约束**：文档去重索引从 `(user_id, kb_id, content_hash)` 改为 `(workspace_id, kb_id, content_hash)`。
- **迁移**：SQLite 使用 batch alter；回填后置 `NOT NULL`；迁移可重复执行（head 两次）。

## Known Gaps

- **前端尚无 workspace 切换器/成员页**：S5 实现；当前前端默认进入个人 workspace。
- **邀请仅限已注册用户**：不做邀请邮件/待接受状态。
- **无 workspace 删除/退出**：个人 workspace 始终存在；owner 不能移除自己。
- **API Key 对成员可见**：列表/吊销按 workspace，未区分 owner。
- **无每成员资源级权限**：workspace 内资源默认全员可见。
- **usage 只按 workspace 聚合**：成员维度留给后续。
- **documents 旧唯一索引替换**：迁移会重建索引，部署前应 `pg_dump`。
- **评测脚本参数改为 `--workspace-id`**：旧命令需更新。