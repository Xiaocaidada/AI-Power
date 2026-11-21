# TDD Evidence — P1-S5b: 知识库与文档管理

- **Date:** 2026-11-21
- **Scope:** 知识库列表/创建/删除、文档上传（进度）、状态轮询、失败原因、重试、删除
- **Source:** [`docs/plan/p1-s5-frontend-ui.md`](../plan/p1-s5-frontend-ui.md) S5b、[`docs/tdd/p1-s5-pre-frontend-contract.md`](./p1-s5-pre-frontend-contract.md)
- **Test runner:** Vitest 3（jsdom）；构建 `tsc --noEmit && vite build`

## User Journeys

1. 作为用户，我能新建知识库并从列表进入详情。
2. 作为用户，我能拖拽或点击上传 PDF/MD/TXT，并看到上传进度。
3. 作为用户，我能看到文档从排队 → 解析 → 向量化 → 就绪，轮询自动停止。
4. 作为用户，我能看到失败原因，并对失败文档点“重试”。
5. 作为用户，我能删除文档；删除后表格与检索都不再包含它。
6. 作为用户，我能删除整个知识库（软删）。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| RED | `npm test` | `2 failed`：`Cannot find module './documentMeta'` 与 `Cannot find module './format'` |
| GREEN | `npm test` | `6 files / 13 tests passed` |
| 类型 | `npm run typecheck` | 通过 |
| 构建 | `npm run build` | 通过；JS `410.37 kB`（gzip `129.33 kB`）、CSS gzip `4.35 kB` |

**实现范围**：`documentMeta`（状态/错误映射、轮询判定）、`format`（字节/日期）、`upload`（XHR 进度 + 401 重试）、知识库列表页、知识库详情页、新 i18n 文案。

## 真实浏览器验证（Chrome DevTools）

```
知识库列表                         → 显示已有「差旅制度」
新建「S5b 验证库」                  → 201，自动进入详情
上传 s5b-notes.md                  → 1 份文档，状态「就绪」，167 B，1 页
上传 s5b-bad.pdf（非法 PDF）        → 「排队中」→「失败 / 解析失败」，出现「重试」按钮
性能面板资源条目                    → 文档列表每 ~2s 轮询一次（排队期间）
删除失败文档（API DELETE）           → 204，剩余 s5b-notes.md（ready）
```

后端日志对应 3 次重试后进入死信：`invalid pdf header` → `parse_failed`。

## Test Specification（4）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 状态 → i18n key 与徽章色；未知状态降级 | `documentMeta.test.ts` | PASS |
| 2 | 仅在有 `uploaded/parsing/embedding` 时轮询 | `documentMeta.test.ts` | PASS |
| 3 | 已知入库错误码有专属文案，未知码回退 | `documentMeta.test.ts` | PASS |
| 4 | 字节格式化（B / KB / MB） | `format.test.ts` | PASS |

i18n 测试同时保证新增的 `knowledge.*` / `documents.*` 中英 key 完全对齐。

## 关键实现

- **上传**：`XMLHttpRequest`（fetch 无上传进度），`upload.onprogress` 驱动进度条；401 时刷新后重试一次。
- **轮询**：`refetchInterval` 由 `shouldPollDocuments` 决定（2s）；全部终态后自动停止。
- **失败原因**：`error_code` → 本地化文案（`too_many_pages`、`empty_document`、`embedding_failed`、`queue_unavailable`、`parse_failed` 等），未知码显示原码。
- **重试/删除**：仅 `failed` 显示重试；删除走确认对话框并失效文档列表。
- **删除知识库**：软删，确认框说明“文档不再参与检索”。
- **权限**：列表/详情读接口使用 JWT；上传/重试/删除按后端要求使用 JWT。

## Known Gaps

- **一次只上传一个文件**：多选会逐个？当前仅取第一个；批量上传留给后续。
- **无客户端上传队列/断点续传**：刷新页面会丢失未完成上传（后端有孤儿清理）。
- **无文档预览**：只能看到文件名、页码与失败原因。
- **知识库列表不显示文档数**：需要后端聚合字段（当前避免 N+1）。
- **无 Playwright**：本次仍为 Chrome DevTools 手工验证。
- **删除失败仅内联提示**：没有 toast 组件。
- **开发环境坑**：5173 上若残留旧 Vite 进程，`/api` 会回落到 SPA HTML（表现为登录“网络异常”）；需结束旧进程后重启。