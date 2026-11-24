# P11-S14：K-P1-1 完整处理节点库

日期：2026-11-24

## 范围

- 独立 OCR 节点。
- 格式专用解析选择。
- 独立全文 / 向量 / 混合索引模式。
- 检索按文档索引模式过滤。

## OCR 节点

新增 `ocr_document` 节点：

- 触发方式：`blank`（空白页）、`short`（短于阈值）、`always`。
- 支持格式：PDF（按页渲染后 OCR）、图片文档。
- 最大 OCR 页数可配置，超限返回 `too_many_ocr_pages`。
- OCR 未配置返回 `ocr_not_configured`；不支持格式返回 `ocr_unsupported_format`。
- 解析节点不再对空文本立即报错，允许后续 OCR 节点补全文本。

`app/services/parsing.py` 新增 `ocr_file_text` / `ocr_pdf_pages` 辅助。

## 格式专用解析

`parse_document` 新增 `format`：

- `auto` 保持按 MIME 自动选择；
- 可显式指定 `pdf/text/markdown/html/csv/docx/xlsx/pptx/image`；
- 与实际 MIME 不匹配返回 `format_mismatch`，避免用错误解析器处理文件。

## 索引模式

`index_knowledge` 新增 `mode`：

- `hybrid`（默认）：向量 + 全文；
- `vector`：仅向量；
- `fulltext`：仅全文，不要求 embedding；
- 兼容旧配置：未填 `mode` 时，`require_embeddings=false` 视为 `fulltext`，否则 `hybrid`。

数据模型（迁移 `c4d5e6f7a8b9`）：

- `documents.index_mode` 默认 `hybrid`。
- 应用处理运行时按 run `index_mode` 校验并写入：
  - `fulltext` 不写 `chunk_embeddings`；
  - `vector/hybrid` 要求全部 chunk 已向量化。

## 检索过滤

- 向量召回只读 `index_mode in (vector, hybrid)` 的文档。
- 全文召回只读 `index_mode in (fulltext, hybrid)` 的文档。
- 旧文档默认 `hybrid`，行为不变。

## 前端

- 知识处理节点目录新增“OCR 识别”，解析节点新增“解析格式”，索引节点新增“索引模式”。
- 新增 `ocr` 与 `fulltext` 处理模板。
- 文档列表展示索引模式。

## 验证

- `ruff check .` 通过。
- 全量 `pytest -n auto` 通过；新增 `tests/test_p11_s14_knowledge_complete.py`（2 个测试）：
  - OCR 节点 + fulltext 应用 + 向量/全文检索过滤；
  - 解析格式不匹配返回 `format_mismatch`。
- `npm run typecheck`、`npm test`（43）、`npm run build` 通过。

## 边界

- OCR 节点仅支持 PDF 与图片；DOCX/PPTX 内嵌图片仍由解析器自动 OCR。
- 索引模式按文档生效，不改变 KB 级 embedding/rerank 配置。
- vector 文档不参与全文召回、fulltext 文档不参与向量召回，这是有意语义。
- 未实现外部数据源/多模态深度理解等 P2 能力。