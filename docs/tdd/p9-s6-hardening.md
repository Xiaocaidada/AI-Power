# P9-S6 权限/项目联动、配额与可观测性

## 项目-知识库联动

- `projects.kb_ids`（JSON 列表，最多 10 个）与既有 `default_kb_id` 并存。
- 项目创建/更新校验每个 KB 属于当前 workspace；跨工作区 404。
- 会话创建优先级：显式 `kb_id/kb_ids` > 自定义 Agent 默认 KB > 项目 `kb_ids`
  > 项目 `default_kb_id`。
- 未显式指定 KB 时，项目内新会话继承全部 `kb_ids`（最多 10 个），
  写入 `conversation_knowledge_bases`。
- 前端项目表单增加“关联知识库”多选。

## 知识配额

`PlanLimits` 新增：

- `max_kbs`
- `max_documents_per_kb`
- `max_kb_bytes`

默认值：

| 计划 | KB 数 | 单 KB 文档 | 单 KB 字节 |
|---|---|---|---|
| free | 10 | 200 | 100 MB |
| pro | 100 | 5000 | 10 GB |

- `enforce_knowledge_base_creation`：KB 创建前检查 workspace KB 数。
- `enforce_kb_document_quota`：上传、URL 导入、站点导入时检查文档数与
  已用字节 + 新增字节；超限返回 429，`X-Quota-Metric` 为
  `knowledge_bases|documents|bytes`。
- 上传超限会删除刚写入的临时文件。
- `/usage/quota` 新增 `knowledge` 汇总（KB 数/上限、字节/上限、单库文档上限）；
  用量页展示。

## 可观测性

新增 Prometheus 计数器（`/metrics`）：

- `ai_power_knowledge_imports_total{kind,status}`：
  `kind=upload|url|site`，`status=created|duplicate|failed`。
- `ai_power_knowledge_eval_runs_total{status,mode|code}`。
- `ai_power_knowledge_optimizations_total{action}`：
  `generated|applied|reverted|dismissed`。

既有 HTTP/SSE/检索/重排指标不变。

## 压测

`scripts/loadtest_knowledge.py`：

- 注册临时账号、创建 KB、上传小文档并等待 ready。
- 以固定并发调用 `POST /knowledge-bases/{id}/retrieval/search`。
- 输出 wall time、成功率、P50/P95/均值与吞吐。
- 不打印密码或 token。

示例：

```bash
.venv/Scripts/python.exe scripts/loadtest_knowledge.py \
  --base-url http://192.168.29.100:8002 --concurrency 10 --requests 50
```

## 迁移与加固

- `c6d7e8f9a0b1` 为 `projects` 增加 `kb_ids` JSON（默认 `[]`）。
- 配额超限统一 429 + `Retry-After`/`X-Quota-*` 头，与既有请求/Token/Key 配额一致。
- 知识字节统计仅计未删除文档的 `size_bytes`。

## 验证

- `ruff check .` 通过；`pytest -n auto` 全量通过。
- 新增 `tests/test_p9_s6.py`：
  - 项目多 KB 创建与会话继承。
  - KB 数、单 KB 文档数、单 KB 字节配额 429。
  - `/usage/quota` 知识汇总。
  - `/metrics` 知识导入计数。
- 前端 typecheck、Vitest、Playwright、构建通过。
- 迁移在真实 Postgres 执行并核对。

## 边界

- 项目 KB 联动仅影响新建会话，不回溯修改历史会话。
- 配额按 workspace 计划静态计算；管理员改计划后立即生效。
- 字节配额按 `documents.size_bytes` 统计，不含 chunks/embeddings 的存储开销。
- 压测脚本只覆盖检索端点，不覆盖入库并发。