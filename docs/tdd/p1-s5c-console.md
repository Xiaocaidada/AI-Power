# TDD Evidence — P1-S5c: 用量、API Key 与个人资料

- **Date:** 2026-11-21
- **Scope:** 用量图表（Recharts）、API Key 创建/一次性展示/吊销、个人资料与语言设置
- **Source:** [`docs/plan/p1-s5-frontend-ui.md`](../plan/p1-s5-frontend-ui.md) S5c
- **Test runner:** Vitest 3（jsdom）；构建 `tsc --noEmit && vite build`

## User Journeys

1. 作为用户，我能按 7/30/90 天或自定义区间查看请求数与 token。
2. 作为用户，我能按日/Provider/模型分组，图表与明细表一致。
3. 作为用户，我能创建 API Key，且完整 Key 只显示一次。
4. 作为用户，我能吊销 Key，状态立即变为已吊销。
5. 作为用户，我能查看账号信息并在中/英之间切换。

## Task Report

| 阶段 | 命令 | 结果 |
|---|---|---|
| RED | `npm test` | `1 failed`：`Cannot find module './usage'` |
| GREEN | `npm test` | `7 files / 18 tests passed` |
| 类型 | `npm run typecheck` | 通过 |
| 构建 | `npm run build` | 通过；入口 JS `423.35 kB`（gzip `132.54 kB`）+ 懒加载 `UsagePage` gzip `129.78 kB` |

**实现范围**：`usage` 辅助函数、用量页（KPI/图表/明细）、API Key 页（创建/一次性展示/吊销）、个人资料页、`useLogout` 抽取、中英文案。

## 真实浏览器验证（Chrome DevTools）

```
/usage（近 30 天，按日）        → 请求数 6，prompt 463，completion 213，total 676
                                → 柱状图 30 个日期刻度，明细表 2026-11-21 行
切换「按 Provider」             → 横向条形图与明细显示 local-qwen（6 / 463 / 213 / 676）
/usage 自定义日期               → 起止日期输入生效（默认 10-23 ~ 11-21）
/settings/api-keys（空）        → 空状态
创建「S5c 验证 Key」             → 一次性弹窗显示完整 Key（ap_df13d0f6_…）
关闭弹窗                        → 列表显示前缀 ap_df13d0f6、两个 scope、状态「有效」
吊销 + 确认                     → 状态变「已吊销」，吊销按钮消失
/settings/profile               → 邮箱 / 角色 user / 注册时间
切换 English                    → 导航与资料卡切换，日期变为 “Nov 21, 2026”；再切回中文
```

本次验证创建的 Key 已在浏览器中吊销；完整 Key 未写入文档或仓库。

## Test Specification（5）

| # | What is guaranteed | Test | Result |
|---|---|---|---|
| 1 | 默认区间以今天（UTC）结束，7/30 天边界正确 | `usage.test.ts` | PASS |
| 2 | 日期区间转为 UTC 查询边界（00:00:00Z ~ 23:59:59Z） | `usage.test.ts` | PASS |
| 3 | 缺失日期补零且保持顺序 | `usage.test.ts` | PASS |
| 4 | 完全无数据时仍返回完整空区间 | `usage.test.ts` | PASS |
| 5 | 分桶汇总与逐项求和一致 | `usage.test.ts` | PASS |

i18n 测试保证新增 `usage.*`、`apiKeys.*`、`profile.*` 的中英 key 完全对齐。

## 关键实现

- **图表按需加载**：`UsagePage` 使用 `React.lazy`，Recharts 不进入首屏包。
- **按日补零**：`fillDailyBuckets` 用 UTC 逐日迭代；明细表只展示有数据的分组。
- **KPI**：由 buckets 求和，不依赖额外接口；NULL usage 的请求计入请求数、token 记 0，并在图下注明。
- **API Key 安全**：完整 Key 只存在于创建响应与一次性弹窗；关闭需点「我已保存」，Esc/遮罩不可关闭；吊销后列表保留记录。
- **登出**：抽取 `useLogout`，侧栏与个人资料页共用；服务端吊销失败也清理本地状态。

## Known Gaps

- **暗色主题未实现**：仅保留令牌与规划，未加开关。
- **无按 Key 的用量明细**：`usage_events` 未记录 key_id（P2）。
- **无分页**：会话/文档/用量均一次性加载。
- **无自动复制**：一次性弹窗需手动点复制；不主动写入剪贴板。
- **无 Playwright**：仍为 Chrome DevTools 手工验证。
- **图表为客户端聚合展示**：服务端仍用 Python 聚合，数据量大时需改为 SQL 聚合（P2）。
- **自定义日期仅精确到天**：不支持小时级区间。