# P11-S8b：工作流 / 文档记忆提取来源

日期：2026-11-24

## 目标

完成 M-P0-5 剩余来源：

- 已完成工作流的运行结果提取。
- 上传者明确授权的文档提取。
- 两个来源都必须同时满足“记忆中心全局开关”和“来源级授权”，默认全部关闭。

## 数据模型

迁移 `e0f1a2b3c4d5`：

| 表 | 字段 | 默认 | 作用 |
|---|---|---|---|
| `memory_settings` | `allow_workflow_extract` | false | 全局允许工作流来源 |
| `memory_settings` | `allow_document_extract` | false | 全局允许文档来源 |
| `workflows` | `memory_extract_enabled` | false | 单个工作流授权 |
| `documents` | `memory_extract_enabled` | false | 单篇文档授权（仅上传者可开启） |

`memory_extraction_runs` 继续使用 `(source_type, source_id)` 唯一约束：

- 工作流：`source_type=workflow_run`，`source_id=<run_id>`。
- 文档：`source_type=document`，`source_id=<document_id>`。

重复任务不再产生候选。

## 后端

- `app/services/memory_extraction.py`
  - `_persist_candidates` 统一候选分类、去重、blocked topic、密文过滤与保存策略。
  - 工作流/文档来源强制 `global` 作用域（没有可信的项目/Agent 绑定）。
  - `run_workflow_memory_extraction`：仅处理 `completed` 且已授权的运行；输入/输出截断后交给 LLM；模型优先级为全局 `MEMORY_EXTRACTION_*` → 工作流首个 `llm|agent` 节点 → 目录中第一个启用模型。
  - `run_document_memory_extraction`：仅处理 `ready`、未删除、上传者已授权的文档；读取前 40 个 chunk 并截断；模型优先级为全局配置 → 目录首个启用模型。
  - 调度函数会先校验来源授权与全局设置，避免无意义入队。
- `app/services/queue.py` / `app/worker.py`
  - 新增 `run_workflow_memory_extraction_job`、`run_document_memory_extraction_job`。
  - 入库成功、处理画布应用、工作流完成时 best-effort 调度。
- `app/routers/workflows.py`
  - `POST /workflows` 接受 `memory_extract_enabled`。
  - 新增 `PATCH /workflows/{id}`：创建者或工作区 owner 可修改名称/描述/授权开关。
- `app/routers/documents.py`
  - `PATCH /documents/{id}` 支持 `memory_extract_enabled`；仅上传者可开启。
  - 开启且文档已 ready 时立即调度一次。

## 前端

- 记忆规则设置新增“允许从工作流运行提取”“允许从授权文档提取”。
- 工作流页面创建时可选授权；已选工作流头部可切换授权。
- 文档属性对话框新增“授权从本文档提取记忆”。

## 验证

- `ruff check app tests alembic` 通过。
- 全量 `pytest -n auto` 通过（新增 `tests/test_p11_s8b_memory_sources.py`）。
- `tests/test_p10_s2.py` 原有聊天提取回归通过。
- `npm run typecheck`、`npm test`（43）、`npm run build` 通过。

## 边界

- 工作流/文档来源固定为全局记忆，不做自动项目作用域推断。
- 文档提取只读取已入库 chunk，不做 OCR 或原文件重新解析。
- 文档授权仅上传者可开启；同工作区其他成员会被拒绝（403）。
- 工作流授权可随时切换，但不会回溯已提取过的历史运行（幂等）。
- 未提供全局提取模型且目录无启用模型时，任务以 `provider_not_configured` 跳过，不伪造成功。