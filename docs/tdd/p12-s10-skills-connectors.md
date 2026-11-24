# P12-S10 Skills 与外部应用连接器（子集）

日期：2026-11-24
状态：Skills 与 GitHub 只读连接器完成；Google OAuth 未实现

## 决策

- Skills 走平台内部定义/执行，不需要外部 Key。
- 外部应用先做 GitHub PAT：用户粘贴 token，平台只读访问。
- Google Drive/Gmail/Calendar 需要平台 OAuth 应用、回调、scope 审核，单独立项。

## Skills

### 数据

- `skills`：workspace、owner、name、description、instructions、`tool_names`、`shared`、`enabled`。
- `skill_runs`：skill、user、status、input、output、provider/model、error_code、tokens、`tool_records`、时间。
- 同一 owner 下名称唯一。

### API

- `GET/POST /skills`
- `GET/PATCH/DELETE /skills/{id}`
- `GET /skills/match?q=`
- `POST /skills/{id}/run`
- `GET /skills/{id}/runs`
- `GET /skills/runs/{run_id}`

### 执行

- `run` 使用 `AgentRunner`：Skill instructions 作为 system prompt，`tool_names` 只保留内置注册表中存在的工具。
- 最多 `SKILL_RUN_MAX_STEPS` 步；工具调用记录写入 `skill_runs.tool_records`。
- 模型调用写入 `usage_events.source='skill'`，`source_ref_id=skill_run.id`。
- 请求配额先经过 `enforce_quota`，完成后累计 token 用量。
- 模型失败、空输出、步数超限返回 `failed` + 类型化 `error_code`。

### 前端

`/skills`：列表、创建/编辑、共享/启用、运行、输出、工具记录与执行历史。

## GitHub 只读连接器

- 复用 `integration_configs(kind=github, auth_type=pat)`，凭证 Fernet 加密。
- `GET /connectors/github/repos`
- `GET /connectors/github/repos/{owner}/{repo}/issues?state=open|closed|all`
- 只发 GET；不提供写入、评论、合并、删除等操作。
- 调用写入 `external_calls`，失败映射 `integration_auth_failed`、`integration_rate_limited` 等。
- 前端 `/connectors`：选择 GitHub 集成、浏览仓库、查看 open issues。

## 测试

`tests/test_p12_s10_skills.py`：

- Skill CRUD、名称冲突 409、匹配、跨用户 404、workspace 共享可见。
- Skill run 完成、token 记录、`usage_events.source='skill'`、运行历史。
- 禁用 Skill 运行返回 409。

`tests/test_p12_s9_integrations.py` 覆盖 GitHub PAT 必填、仓库/Issues 只读接口与跨用户隔离。

## 边界

已解决：

- Skills 可复用、可共享、有执行记录与用量归属。
- GitHub 只读、凭证加密、调用审计。
- 所有外部失败都有类型化错误，不伪造结果。

后续/未实现：

- Google Drive/Gmail/Calendar OAuth：需要平台 OAuth 应用注册、回调域名、scope 审核、token 刷新与撤销；当前未实现。
- 用户自建 OAuth 应用模式未实现。
- GitHub 写入操作（评论/issue/PR）未实现，避免未经审批的外部副作用。
- Skill 自动匹配注入聊天未实现；当前只提供 `/skills/match`。
- Skill 工具白名单仅覆盖内置工具，不含插件/MCP；后续可按风险分级扩展。
- Skill 运行是同步请求，不是长任务；超大任务应使用 Agent 任务。

明确不做：

- 伪造 OAuth 授权或 GitHub 写入成功。
- 在未授权时执行外部写操作。