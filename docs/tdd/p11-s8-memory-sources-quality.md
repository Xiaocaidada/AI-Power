# P11-S8：记忆提取来源与质量广度

日期：2026-11-24

## 范围

对应缺口清单 M-P0-4、M-P0-5（部分）、M-P1-1、M-P1-3。

1. 质量建议广度：孤儿、关系异常、项目缺口、规则提示。
2. 更多提取来源：项目活动来源。
3. 模型/Agent 细粒度读取白名单。
4. 记忆变化分析：最近版本变化与偏好/项目/技术维度统计。

## 质量建议广度（M-P0-4）

`analyze_memories` 新增：

- `orphans`：没有任何关系连接的活跃记忆。
- `relation_anomalies`：自关联、重复关系、与高度相似记忆矛盾的关联。
- `project_gaps`：分类为 project 但未绑定 project_id 的记忆。
- `rule_hints`：重复率、冲突率、不完整率、长期未用率过高时的规则提示。

`generate_suggestions` 新增信息型建议：

- `link_orphans`
- `review_relations`
- `supplement_project`
- `adjust_rules`

信息型建议仅用于提示，前端只对可执行建议显示“应用”，可忽略。

## 更多提取来源（M-P0-5，部分）

- 新增项目活动来源 `create_project_memory_candidate`：
  - 项目创建/更新后，如果记忆中心已启用、允许项目提取且项目说明/描述有效，生成项目范围的记忆候选。
  - 默认进入待确认列表；只有 `auto_save=true` 且无需确认时直接保存。
  - 按内容哈希与已有候选去重。
- 聊天消息提取保持不变。
- 工作流执行、文档授权的自动提取仍为边界。

## 模型/Agent 读取白名单（M-P1-1）

`memory_settings` 新增（迁移 `d9e0f1a2b3c4`）：

- `allowed_provider_ids`
- `allowed_models`
- `allowed_agent_ids`

`select_memories` 在提供当前 provider/model/agent 时执行白名单过滤；空列表表示不限制。聊天注入、工作流 memory_read、Agent `memory_search` 工具均读取该设置。

前端“规则设置”新增三个逗号分隔白名单输入。

## 变化分析（M-P1-3）

新增 `GET /memories/changes?days=30&limit=20`：

- 最近发生版本变化的记忆及 `from_version`/`to_version`。
- 变化字段与风险标记。
- 偏好变化、项目/作用域变化、技术内容变化计数。

前端 `/memory` 总览新增“最近变化”区块。

## 验证

- `tests/test_p11_s8.py`：
  - 模型/Agent 白名单允许与拒绝。
  - 孤儿、关系异常、项目缺口分析与对应建议。
  - 项目活动来源生成待确认候选。
  - `/memories/changes` 返回变化记录与跨用户 404。
- 全量 `ruff`、`pytest -n auto`、`npm run typecheck`、`npm test`、`npm run build`。
- Playwright `memory-dashboard.spec.ts` 回归通过。

## 边界

- M-P0-5 部分完成：项目活动来源已实现；工作流执行与文档授权的自动提取未实现，目标：后续记忆提取来源切片（未排期）。
- 白名单仅在上下文提供 provider/model/agent 时生效；未提供该维度时不会因为白名单为空而拦截。
- 关系异常检测为启发式（自关联/重复/高相似矛盾），不覆盖全部图谱异常。
- 项目缺口只检测“project 分类但无 project_id”，不自动创建项目。
- 变化分析只扫描最近 30 天有更新的最多 50 条记忆，偏好/技术判断为关键词启发式。
- 信息型质量建议不可自动应用，避免误改用户数据。
- 未实现到期/质量提醒的邮件、短信或其他真实通知渠道。