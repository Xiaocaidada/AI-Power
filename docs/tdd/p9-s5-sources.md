# P9-S5 数据源与文档工作区

## URL/HTML 导入

- `POST /knowledge-bases/{kb_id}/documents/import-url`
  - 入参：`{url, folder, tags}`。
  - 抓取前复用 `validate_outbound_url`：URL 形状、非 dev 强制 HTTPS、
    `URL_IMPORT_ALLOWED_HOSTS` 允许列表、DNS 解析、私网/保留地址拒绝。
  - 新增 `URL_IMPORT_*` 配置：开关、超时、最大字节、允许列表、私网开关。
  - 仅接受 `text/html`、`application/xhtml+xml`、`text/plain`、
    `text/markdown`；缺失 Content-Type 时按 `.html/.htm/.md/.txt` 后缀推断。
  - 禁用重定向、`trust_env=False`、流式读取并按 `URL_IMPORT_MAX_BYTES`
    截断报错；再受 `MAX_UPLOAD_BYTES` 约束。
  - 内容写入 `UPLOAD_DIR`（UUID 文件名），创建 `Document` 并复用既有入库队列；
    同 KB 同内容哈希返回 `duplicate=true`（HTTP 200）。
  - `documents.source_url` 保存来源 URL。
- 错误映射：非法/被拒地址 422、类型不支持 415、过大 413、抓取失败 502、
  队列不可用 503。

## 文件夹与元数据

- `documents.folder`（`a/b` 归一化路径，最长 255）与 `documents.doc_metadata`
  （字符串键值对，最多 20 项、键 50 / 值 500 字符）。
- `GET /knowledge-bases/{kb_id}/folders` 返回 `{folder, count}`（含根目录空串）。
- `GET /knowledge-bases/{kb_id}/documents?folder=` 精确过滤；空串表示根目录。
- `PATCH /documents/{id}` 支持可选 `tags`、`folder`、`doc_metadata`：
  仅更新传入字段，未传字段保持不变。旧客户端只传 `tags` 仍然兼容。

## Excel / PPT

- 新增依赖 `openpyxl`、`python-pptx`。
- `.xlsx`：每个 sheet 一页，逐行以制表符连接非空单元格，页首写 sheet 名称。
- `.pptx`：每张幻灯片一页，提取文本框段落与表格单元格。
- `.html/.htm`：标准库 `HTMLParser` 提取可见文本，跳过
  `script/style/noscript/svg/template/iframe`，块级标签换行。
- 以上类型均进入既有上传校验、入库、重新分块与知识处理画布解析节点。

## 前端

- 知识库详情页：
  - 头部新增“从 URL 导入”对话框（URL、文件夹、标签）。
  - 文档筛选新增文件夹下拉（全部/根目录/各文件夹及计数）。
  - 文档行展示文件夹与“来自 URL”标记。
  - 文档属性对话框：文件夹、标签、元数据 JSON；非法 JSON 本地拦截。
- 上传区文案更新为 `.pdf/.docx/.xlsx/.pptx/.html/.csv/.md/.txt`。

## 边界能力（S5b）

### 安全重定向与站点抓取

- URL 抓取不再一律拒绝重定向：最多 `URL_IMPORT_MAX_REDIRECTS` 跳，
  每一跳重新执行 URL 形状/HTTPS/允许列表/DNS/私网校验；超限 502
  `too_many_redirects`，无 Location 502。
- 拒绝带用户名/密码的 URL。
- `POST /knowledge-bases/{id}/documents/import-site`：
  `{url, max_pages(1-20), same_origin}`，BFS 抓取同站页面；
  `URL_IMPORT_CRAWL_MAX_PAGES` 为硬上限；单页失败记录 `{url, code}` 不阻断。
- 返回 `{pages, created, duplicates, failed}`；起始页全部失败返回 502。
- 前端 URL 导入对话框新增“抓取同站页面 + 最多页数”。

### OCR

- 新增可选 OCR：`OCR_ENABLED/OCR_BASE_URL/OCR_API_KEY/OCR_MODEL`，
  走 OpenAI 兼容 `chat/completions` 视觉消息；密钥仅服务端使用。
- 图片 `.png/.jpg/.jpeg/.webp` 作为知识库文档时通过 OCR 解析；
  未启用 OCR 时上传返回 415。
- PDF 空白页回退：用 `pymupdf` 以 144 DPI 渲染该页后 OCR；
  非空白页仍用 pypdf 文本。
- PPTX 图片形状也会 OCR 并追加到幻灯片文本。
- OCR 失败映射 `ocr_failed`；超时/不可达/空结果有独立错误码。

### 元数据检索过滤

- KB `settings.retrieval.metadata_filter`：最多 10 个键值对，
  键限 `[A-Za-z0-9_.-]{1,50}`，值 ≤200；设置页支持 JSON 编辑。
- 内置检索、混合检索、自定义检索流程（`vector_search_chunks` /
  `lexical_search_chunks`）、评测与 Agent `kb_search` 全部应用该过滤。
- Postgres 使用 `doc_metadata ->> key`，SQLite 使用 `json_extract`。

### 文件夹重命名

- `POST /knowledge-bases/{id}/folders/rename`：`{from_folder, to_folder}`，
  同时重命名该文件夹及所有子文件夹下的文档；目标不能位于源目录内部（422）。
- 前端在选中具体文件夹时显示“重命名文件夹”并调用该 API。

## 验证

- `ruff check .` 通过；`pytest -n auto` 全量通过。
- 新增 `tests/test_p9_s5_boundaries.py`：安全重定向/上限、链接提取、
  同站有界爬取、图片/PPTX OCR、元数据检索过滤、文件夹重命名。
- 新增 `tests/test_p9_s5.py`：
  - HTML 提取可见文本并剔除脚本/样式。
  - XLSX 读取 sheet、PPTX 读取幻灯片文本。
  - URL 导入创建文档并写入 `source_url/folder/tags`，重复导入 200 + duplicate。
  - 私网地址 422 `invalid_url`。
  - 文件夹/元数据 PATCH 与 folder 过滤、文件夹计数。
- 前端 typecheck、Vitest、`e2e/p9.spec.ts` 4 个 Playwright、构建通过。
- 迁移 `b5c6d7e8f9a0` 在真实 Postgres 执行并核对。

## 剩余边界

- URL 导入不执行 JavaScript；单页/同站爬取上限 20 页，不跨站递归。
- OCR 依赖管理员配置的视觉模型端点；未配置时图片文档不可入库，
  扫描 PDF 仍按纯文本处理（无文字则空文档失败）。
- 元数据过滤为精确匹配、文档级；不支持范围/布尔表达式。
- 文件夹仍是逻辑路径字符串，无独立目录表；重命名通过批量更新文档实现。