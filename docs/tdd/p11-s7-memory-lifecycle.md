# P11-S7：记忆仪表盘 / 生命周期 / 版本 diff

日期：2026-11-24

## 范围

对应缺口清单 M-P0-1、M-P0-2、M-P0-3。

1. 记忆完整度与使用聚合。
2. 生命周期：全局/单条保留策略、定期过期、blocked topic 统一拦截。
3. 记忆版本 diff、变化摘要与风险提示。

## 仪表盘

`GET /memories/stats` 扩展：

- 完整度：按标题、正文长度、分类、标签、来源、向量、重要度、项目/Agent 绑定计算 0–100 分，输出 `average_score` 与 `complete/partial/sparse` 分布。
- 生命周期：`retention_days`、`expiring_soon`（7 天内到期）、`stale`（30 天未使用）。
- 使用聚合：`usage_total`、`usage_chars`、按模型、上下文类型、Agent、项目、会话聚合。
- 其他：`by_status`、`by_source`、`active_chars`。

前端 `/memory` 总览新增：

- 平均完整度、即将过期、30 天未使用、注入次数 KPI。
- 完整度分布与来源统计。
- 使用聚合（模型、上下文、Agent、项目、会话）。
- 生命周期预览：全局保留天数、即将过期条数与前 5 条。

## 生命周期

- `agent_memories.retention_days`（迁移 `c8d9e0f1a2b3`）：单条记忆覆盖全局策略。
- `MemorySettings.retention_days` 作为全局策略；单条优先。
- `GET /memories/lifecycle`：当前用户即将过期的记忆预览（最多 50 条）。
- Worker 每日 04:30 执行 `expire_memories_job`：
  - 扫描 active、未 pin/favorite 的记忆；
  - 按单条或全局保留天数判断；
  - 将过期记忆标记为 `expired`，写入版本记录；
  - **不硬删除用户数据**，单次最多处理 500 条。
- `blocked_topics` 从仅提取链路扩展到手动创建/更新：
  - 创建或修改内容命中 blocked topic 返回 `422 blocked_topic`。

## 版本 diff

`GET /memories/{id}/versions/diff?from_version=&to_version=`：

- 默认比较最新两个版本；只传 `to_version` 时比较其上一版。
- 返回字段变化（标题、分类、作用域、项目/Agent、状态、重要度、标签、敏感级别、置信度、有效期、保留天数等）。
- 内容变化返回 unified diff（截断 20000 字符）。
- 风险标记：
  - `content_shrunk`、`content_changed`
  - `sensitivity_increased`
  - `scope_changed`、`binding_changed`
  - `deactivated`
  - `confidence_dropped`
  - `tags_removed`

前端记忆详情历史版本新增“对比上一版”，展示风险徽标、字段变化与内容 diff。

## 验证

- `tests/test_p11_s7.py`：
  - 统计完整度、使用聚合、生命周期预览与过期任务。
  - blocked topic 创建/更新拦截。
  - 版本 diff 字段/内容/风险标记与跨用户 404。
  - 单条保留策略创建/清除与版本快照。
- 全量 `ruff`、`pytest -n auto`、`npm run typecheck`、`npm test`、`npm run build`。
- Playwright `memory-dashboard.spec.ts`：仪表盘与版本 diff 2 个测试通过。

## 边界

- 保留策略只标记 `expired`，不自动硬删除；用户仍可手动恢复/归档。
- 生命周期任务每天运行一次，单次最多扫描 5000 条、过期 500 条；没有到期前通知。
- 完整度为启发式评分，不代表语义质量。
- 使用聚合读取全部历史 `memory_usage_events`，未做时间窗口过滤。
- 版本 diff 基于快照字段，不追踪关系/图谱变化。
- blocked topic 为子串匹配，可能产生误拦截；目标：后续支持正则/分类级规则（未排期）。
- 生命周期过期不发送邮件/短信通知；真实通知渠道不在本切片。