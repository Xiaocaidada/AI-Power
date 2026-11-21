# ADR-0013: Prompt 模板与版本化

- **Status:** Accepted
- **Date:** 2026-11-21
- **Context:** system prompt 原先是 RAG 路径里的硬编码常量，无法按团队/场景管理，也无法回溯“这条回答当时用了什么 prompt”。

## Decision

- **workspace 级模板**：`prompt_templates(workspace_id, name, description, deleted_at)`。
- **不可变版本**：`prompt_versions(template_id, version, system_prompt, variables)`，`(template_id, version)` 唯一；编辑产生新版本，旧版本永不修改。
- **变量**：创建版本时用 `{{name}}` 正则提取并存入 `variables`；渲染在服务端完成，缺变量返回 422 `missing_variables` + 缺失列表。
- **会话快照**：创建会话时按 `prompt_version_id` + `prompt_variables` 渲染，结果写入 `conversations.system_prompt`，同时保存 `prompt_version_id`。后续改版本/删模板不影响历史。
- **接入语义**：
  - 普通对话：快照作为 system prompt；带 KB 时与 `<reference_material>` 合并，并强制附加不可信数据防护语。
  - Agent 对话：快照替换 supervisor prompt，工具协议/委派说明仍然追加；子 Agent 保持专用 prompt。
- **软删除**：`deleted_at` 保留版本，已绑定会话继续可用；新会话不能再绑定已删除模板。

## Consequences

- 历史可复现，删除模板不会破坏会话。
- 变量只有字符串类型，无 schema/类型校验。
- 模板只作用于 supervisor，不能覆盖子 Agent 的领域 prompt。
- 同名模板允许重复；改名/改描述未提供。

## Alternatives

- **全局模板**：无法按 workspace 定制。
- **查询时重新渲染**：改版本会改变历史语义，不可接受。
- **硬删除模板**：会破坏已绑定会话的可追溯性。