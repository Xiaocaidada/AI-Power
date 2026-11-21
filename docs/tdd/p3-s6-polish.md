# TDD Evidence — P3-S6: 开放 API 与收口

- **Date:** 2026-11-21
- **Scope:** OpenAPI 元数据与错误响应、quickstart/错误契约、会话/文档/trace 加载更多、429 倒计时、Key 轮换提示、ADR-0012–0015
- **Source:** [`docs/plan/p3-plan.md`](../plan/p3-plan.md) P3-S6（D7 不引入 `/v1`、D9 欠账）

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| 后端全量 | `pytest -q` | **272 passed, 3 skipped** |
| OpenAPI 契约 | `pytest tests/test_app.py` | 3 passed |
| Lint/Format | `ruff check` / `ruff format --check` | 通过 |
| 前端单测 | `npm test` | **22 passed**（新增 2 条分页、2 条主题） |
| 类型/构建 | `npm run typecheck` / `npm run build` | 通过 |
| E2E | `npm run test:e2e` | 1 passed（9.0s） |

## 交付

- **OpenAPI**：应用标题/版本/描述与 13 个 tag 描述；`POST /conversations/{id}/messages` 声明 401/404/429/503，文档上传声明 404/413/415/429/503；新增 `test_openapi_documents_stream_and_admin_contract` 防回归。
- **API 文档**：
  - [`docs/api/quickstart.md`](../api/quickstart.md)：注册/登录、上传、SSE curl 与 Python `httpx`、API Key、成本、Prompt/Agent、分页约定。
  - [`docs/api/errors.md`](../api/errors.md)：错误码分组、SSE 终止语义、配额头、管理端 404 约定。
- **前端分页**：新增 `web/src/lib/pagination.ts`（游标 + 去重合并）及单测；会话侧栏、知识库文档列表改用 `useInfiniteQuery`，支持“加载更多”；用量页新增“最近请求”（`/traces` 每页 10 条）。
- **429 倒计时**：对话页解析 `Retry-After`，显示剩余秒数并在倒计时内禁用发送。
- **Key 轮换提示**：API Key 页提示超过 90 天的有效 Key。
- **ADR**：0012（Agent/工具）、0013（Prompt 版本化）、0014（成本快照）、0015（管理员/审计）。
- **暗色主题**：CSS 变量在 `html.dark` 下切换；侧栏按钮切换并写入 `localStorage.ai_power_theme`；首次访问遵循 `prefers-color-scheme`；Recharts 配色调整为深浅通用。

## Test Specification（新增 5）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | OpenAPI 标题/tag 与消息流、上传错误响应存在 | `test_openapi_documents_stream_and_admin_contract` | PASS |
| 2 | 满页才产生游标，短页结束 | `pageFromItems exposes a cursor only for a full page` | PASS |
| 3 | 多页合并保持顺序并去重 | `mergePages keeps order and drops duplicate ids` | PASS |
| 4 | 切换主题写入 localStorage 并加 `dark` class | `applyTheme stores the theme and toggles the dark class` | PASS |
| 5 | 已保存主题优先于系统偏好 | `storedTheme prefers a saved value` | PASS |

## Known Gaps
- **无独立 trace 列表页**：加载更多放在用量页“最近请求”，不是完整检索/筛选页。
- **分页无总数**：只支持 `limit`/`before`，UI 不显示总条数。
- **Key 轮换仅提示**：需手动创建新 Key 后吊销旧 Key，无自动化轮换接口。
- **OpenAPI 仅有响应说明**：未为每个字段补 example，未生成 SDK。
- **前端未新增 E2E**：分页/429 仅由类型检查、单测与现有冒烟覆盖。