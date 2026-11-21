# ADR-0009: Workspace 多租户

- **Status:** Accepted
- **Date:** 2026-11-21
- **Related:** [`docs/plan/p2-plan.md`](../plan/p2-plan.md) S1、[`docs/tdd/p2-s1-workspaces.md`](../tdd/p2-s1-workspaces.md)

## Context

P1 的资源都按 `user_id` 隔离，无法团队共享。P2 要求“多租户隔离”，且不能破坏已有的个人数据与前端。

## Decision

- 新增 `workspaces` 与 `workspace_members(workspace_id, user_id, role)`；角色仅 `owner`/`member`。
- 每个用户注册时自动创建 `is_personal=true` 的个人 workspace。
- 资源表增加 `workspace_id`：知识库、会话、文档、chunk、入库任务、用量事件、API Key；`user_id` 保留为创建者。
- 请求通过 `X-Workspace-Id` 选择 workspace；缺省使用个人 workspace；非成员返回 404。
- API Key 绑定自身 workspace；若 header 指定其他 workspace，返回 404。
- 迁移 0005 为历史用户建个人 workspace 并回填所有资源，随后置 `NOT NULL`。
- 文档去重唯一索引改为 `(workspace_id, kb_id, content_hash)`。

## Consequences

**Positive**

- 个人用户无感升级（无 header 时行为不变）。
- 跨租户统一 404，不泄露存在性。
- 成员移除立即生效；Key 无法跨 workspace。

**Negative**

- 所有资源查询必须带 `workspace_id`，遗漏即越权，需要隔离测试兜底。
- 无组织/团队层级、无角色变更、无邀请接受流程。
- API Key 对整个 workspace 可见（未区分 owner）。
- 成员无资源级权限，workspace 内默认全员可见。

## Follow-ups

1. 邀请邮件与待接受状态。
2. 角色管理（admin/editor/viewer）与资源级权限。
3. workspace 删除/退出与所有权转移。