# P11-S5：知识处理节点扩展

日期：2026-11-24

## 范围

对应缺口清单 K-P0-1、K-P0-2、K-P1-1（部分）。

1. 切片策略：自定义分隔符、父子切片、语义切片，保留切片元数据。
2. 文档增强节点：文本过滤、元数据增强、关键词、摘要、去重。
3. 处理节点库：新增节点、模板与前端节点图标/预览/分块元数据展示。
4. 检索：父子切片按父块展开，减少重复上下文。

## 切片

- `ChunkStrategy` 新增 `custom`、`parent_child`、`semantic`。
- `ChunkTextConfig` 新增 `separators`、`parent_size`、`child_size`、`semantic_threshold`，并校验父子大小关系。
- `chunk_custom`：按 `|` 分隔的自定义分隔符递归切片。
- `chunk_parent_child`：父块按 `parent_size` 生成，子块按 `child_size` 切片；子块 `meta` 写入 `parent_id`、`parent_index`、`parent_text`。
- `semantic`：按句子切分并调用 KB Embedding 模型，按相邻句子余弦相似度与 `chunk_size` 分组；Embedding 失败返回 `embedding_unavailable` / `chunk_embedding_failed`。

## 增强节点

| 节点 | 行为 | 主要配置 |
|---|---|---|
| `filter_text` | 行级过滤：最短长度、正则、页内去重、全角转半角、跨页重复行清理 | `min_line_chars`、`drop_patterns`、`dedupe_lines`、`normalize_width`、`drop_boilerplate` |
| `enrich_metadata` | 把文档标题、文件名、文件夹、标签、来源 URL 写入每个切片 `meta`，可把标题写入正文 | `include_*`、`prepend_title` |
| `extract_keywords` | 词频提取中英文关键词，可写入正文前缀 | `count`、`prepend` |
| `summarize_chunks` | 抽取式/首句摘要写入 `meta.summary`，可写入正文前缀 | `max_chars`、`mode`、`prepend` |
| `dedupe_chunks` | 规范化文本哈希 + 字符三元组 Jaccard 去重，重新编号 | `threshold`、`min_chars` |

新增实现：`app/services/knowledge/enhance.py`。

## 存储与检索

- `chunks` 新增 `chunk_meta`（迁移 `b7c8d9e0f1a2`）。
- 应用暂存时复制 `knowledge_chunk_drafts.chunk_meta` 到 `chunks.chunk_meta`。
- `ChunkOut` 返回 `chunk_meta`，分块页展示标题/关键词/摘要/父块。
- `RetrievedChunk` 携带 `chunk_meta`；内置检索与自定义检索工作流的 `context/output` 阶段均按 `(document_id, parent_id)` 展开父块并去重。

## 模板与前端

- 新增模板：`enhanced`（增强文档处理）、`parent_child`（父子切片处理）。
- 图谱节点清单新增五类节点与配置字段，AI Builder manifest 自动包含。
- `StudioCanvas` 增加新节点图标；知识画布预览显示切片关键词/摘要；分块页显示元数据。

## 验证

- `tests/test_p11_s5.py`：
  - `chunk_custom`、`chunk_parent_child`、`split_sentences` 行为。
  - 增强 + 父子切片全链路：过滤、元数据、关键词、摘要、去重、向量化、暂存、应用、分块元数据。
  - 自定义/语义切片管线均能完成。
  - 目录节点/模板存在，非法父子大小返回 422。
  - 应用后检索命中父块内容。
- 全量 `ruff`、`pytest -n auto`、`npm run typecheck`、`npm test`、`npm run build`。

## 边界

- K-P1-1 仅部分完成：OCR 仍由既有解析器与 `OCR_*` 全局配置控制，未新增独立 OCR 节点；未新增格式专用解析器节点；未新增独立全文/混合索引节点（现有 pg_trgm + pgvector 检索继续使用）。目标：P11 后续知识节点切片（未排期）。
- 语义切片每个句子都要调用 Embedding，长文档成本更高；不做跨页父块合并。目标：后续性能优化（未排期）。
- 关键词/摘要为规则/抽取式，不调用 LLM。目标：P11-S6 之后按需增加 LLM 增强。
- 父子切片的每个子块都保存完整 `parent_text`，大文档会放大存储。目标：后续改为父块单存 + 子块引用（未排期）。
- 去重为精确哈希 + 长度分桶三元组相似度，极端大文档仍可能较慢。目标：后续性能优化（未排期）。