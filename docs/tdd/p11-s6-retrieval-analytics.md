# P11-S6：知识检索节点、多 KB 与运行分析

日期：2026-11-24

## 范围

对应缺口清单 K-P0-3、K-P0-4、K-P1-2（部分）。

1. 检索节点：元数据过滤、相似度/结果过滤与去重、多 KB 联合检索。
2. 检索节点：LLM 多查询、空结果回退。
3. 知识库处理运行分析：成功率、耗时、切片量、失败原因与最近运行。
4. S5 边界修复：自定义检索工作流也展开父块。

## 检索节点

### 搜索节点扩展

`vector_search` / `lexical_search` / `hybrid_search` 新增：

- `metadata_filter`：绑定到 `Document.doc_metadata` 的精确过滤，最多 10 个键。
- `kb_ids`：覆盖本次节点的知识库范围，支持同一工作区多 KB 联合检索；未配置时使用执行时传入的 KB 列表。

`app/services/retrieval.py` 的 `vector_search_chunks` / `lexical_search_chunks` / `hybrid_search_chunks` 增加 `metadata_filter` 参数；节点过滤优先于 KB 默认过滤。

### 新节点

| 节点 | 行为 |
|---|---|
| `filter_results` | 按 `max_distance`、`min_rerank_score`、`min_fused_score`、`min_text_chars` 过滤；支持按文档或父块去重 |
| `multi_query` | LLM 生成 2–5 个查询变体，原查询 + 变体分别混合检索，RRF 融合 |
| `fallback_search` | 当前结果为空时执行一次混合检索兜底 |

`multi_query` / `rewrite_query` 在未显式传入 registry 时使用 `build_user_registry`，使绑定检索工作流也能使用用户个人 Provider。

### 模板

新增“多查询 + 过滤”模板：多查询 → 结果过滤 → 空结果回退 → 上下文 → 输出。

## 运行分析

新增 `GET /knowledge-bases/{id}/processing/analytics?days=7|30|90`：

- 运行总数、完成/失败/取消/进行中。
- 成功率、平均耗时、P95 耗时、平均切片数。
- 已应用/待应用数量。
- 失败原因聚合。
- 最近 20 条运行（文档、状态、错误码、耗时、切片、是否应用）。

前端在知识库详情页新增“运行分析”页签，包含范围切换、KPI、失败原因和最近运行表。

## S5 边界修复

- `expand_parent_context` 改为公开函数。
- 自定义检索工作流的 `context` / `output` 阶段同样按父块展开并去重。

## 验证

- `tests/test_p11_s6.py`：
  - 元数据过滤只返回匹配文档。
  - 节点 `kb_ids` 可检索另一知识库。
  - `filter_results` 去重文档。
  - `multi_query` 使用 Provider 生成变体并返回结果。
  - 空结果后 `fallback_search` 兜底。
  - 处理运行分析返回总数、成功率、最近运行与文件名。
  - 检索目录包含新节点与模板。
- 全量 `ruff`、`pytest -n auto`、`npm run typecheck`、`npm test`、`npm run build`。
- Playwright 知识画布/分析页签回归。

## 边界

- K-P1-2 仅部分完成：未新增意图识别/分类路由、同义词扩展、查询去重；目标：后续知识检索增强切片（未排期）。
- 多 KB 检索使用第一个 KB 的 Embedding/Rerank 配置；不同 Embedding 维度的 KB 不能混合检索。目标：跨模型多 KB 检索（未排期）。
- 搜索节点的 `kb_ids` 在执行时会校验工作区归属，缺失或不可访问返回 `invalid_knowledge_base`；`metadata_filter` 的键限制为 `[A-Za-z0-9_.-]`，防止 JSONPath 注入。
- `multi_query` 的变体解析按行文本处理，不解析 JSON 数组。
- 运行分析最多采样最近 1000 条运行，不做长期趋势存储。
- 结果过滤的 `min_rerank_score`/`min_fused_score` 只对已有对应分数的结果生效。
- 未新增独立全文/混合索引节点；索引仍由 `index_knowledge` 写入文本 + 向量，检索模式由 KB 设置选择。