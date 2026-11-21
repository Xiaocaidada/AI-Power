# TDD Evidence — P3-S3: Prompt 模板

- **Date:** 2026-11-21
- **Scope:** workspace 级 Prompt 模板、不可变版本、变量渲染、会话绑定与快照、前端模板管理
- **Source:** [`docs/plan/p3-plan.md`](../plan/p3-plan.md) P3-S3（D4 模板 + 不可变版本）

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 新增 Prompt 测试 | `pytest tests/test_prompt_templates.py` | **9 passed** |
| 后端全量 | `pytest -q` | **260 passed, 3 skipped** |
| Lint/Format | `ruff check` / `ruff format --check` | 通过 |
| 前端单测 | `npm test` | 18 passed |
| 类型/构建 | `npm run typecheck` / `npm run build` | 通过 |

## 交付

- **数据模型**：`prompt_templates(id, workspace_id, name, description, created_by, deleted_at)`、`prompt_versions(id, template_id, version, system_prompt, variables)`，`(template_id, version)` 唯一；版本只增不改。
- **会话快照**：`conversations.prompt_version_id` + `conversations.system_prompt`；创建会话时按版本与变量渲染并落库，后续模板/版本变化不影响历史。
- **API**（均 workspace 隔离，跨租户 404）：
  - `GET /prompt-templates`、`POST /prompt-templates`
  - `GET /prompt-templates/{id}`
  - `POST /prompt-templates/{id}/versions`
  - `POST /prompt-templates/{id}/render`（可选 `version`；缺变量返回 422 `missing_variables` + `missing` 列表）
  - `DELETE /prompt-templates/{id}`（软删除）
- **变量**：`{{name}}` 正则提取，创建版本时写入 `variables`；渲染保留未知占位符。
- **对话接入**：
  - 普通对话：模板渲染结果作为 system prompt；带知识库时与 `<reference_material>` 合并，并强制附加不可信数据防护语。
  - Agent 对话：模板替换 supervisor system prompt，工具协议与委派说明仍然追加；子 Agent 保持专用 prompt。
- **前端**：`/settings/prompts` 管理页（列表、创建、新版本、变量渲染预览、软删除）；新建会话可选择模板并填写变量；对话头部显示“自定义 Prompt”；中英文案对齐。

## Test Specification（新增 9）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 创建模板提取变量、列表可见、渲染正确 | `test_create_template_extracts_variables_and_renders` | PASS |
| 2 | 缺变量返回 422 `missing_variables` 与缺失列表 | `test_render_reports_missing_variables` | PASS |
| 3 | 新版本递增、旧版本内容不变、可按版本渲染 | `test_new_version_is_immutable_and_render_can_pick_one` | PASS |
| 4 | 跨 workspace 读取/渲染/删除均 404 | `test_prompt_templates_are_workspace_scoped` | PASS |
| 5 | 会话保存版本并实际使用渲染后的 system prompt | `test_conversation_uses_rendered_prompt_and_reports_version` | PASS |
| 6 | 创建会话缺变量返回 422 | `test_conversation_rejects_missing_prompt_variables` | PASS |
| 7 | Agent supervisor 使用模板且保留委派协议 | `test_agent_supervisor_uses_template` | PASS |
| 8 | 删除模板不影响已有会话的 Prompt 与后续对话 | `test_deleting_template_keeps_existing_conversation` | PASS |
| 9 | RAG 模板与引用材料、防护语共存 | `test_rag_prompt_combines_template_with_references` | PASS |

## Known Gaps

- **模板名称/版本未在对话历史展示**：ConversationOut 只返回 `prompt_version_id`，前端显示“自定义 Prompt”徽标。
- **不支持重命名/改描述**；同名模板允许重复。
- **子 Agent 不使用模板**：模板只作用于 supervisor（避免破坏工具协议）。
- **无模板导入/导出、无共享市场**；无变量类型校验（均为字符串）。
- **前端新页面无 Vitest 覆盖**，以 typecheck/build 为准。
- **未做模板内容安全扫描**；变量值属于用户输入，按纯文本替换。