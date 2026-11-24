# P11-S4：Agent 配置与工具生态

日期：2026-11-24

## 范围

对应缺口清单 A-P0-1、A-P0-3、A-P1-1、A-P1-2。

1. Agent 基础模型参数（temperature / max_tokens / top_p）配置与生效。
2. 工具目录、单工具测试、MCP 工具发现与绑定。
3. Agent 广场封面、发布者/分类/官方筛选。
4. Agent 工作流模板与从模板创建。

## 后端

### 模型参数

- `app/services/generation.py` 统一归一化 generation settings，非法/越界值按服务端范围截断，非法类型忽略。
- `CustomAgentCreate` / `CustomAgentUpdate` 的 `generation_settings` 在 `validate_agent_values` 中统一归一化。
- 创建自定义 Agent 会话时，若请求未显式提供，则继承 Agent 的 `generation_settings`。
- 工作流 `agent` 节点绑定自定义 Agent 时，把 Agent 参数作为 `generation_opts` 传给 `AgentRunner`。

### 工具与 MCP

- `app/tools/mcp.py` 定义 `mcp:<server_uuid>:<remote_tool_name>` 引用格式。
- `app/services/agent_tools.py`：
  - `validate_agent_tools`：内置工具白名单 + MCP 服务器必须存在且启用。
  - `build_mcp_tool_specs`：把绑定的 MCP 工具适配为 `ToolSpec`，远程 schema 尽力发现并缓存 120 秒；执行复用 `app/services/mcp.py` 的 SSRF 安全客户端。
  - `agent_tool_catalog` / `list_server_mcp_tools`：工具浏览与 MCP 发现。
  - `execute_agent_tool`：单工具测试，复用统一工具注册表与超时/截断策略。
- 会话 Agent 运行时把 MCP 工具加入工具注册表；工作流 `agent` 节点同样支持绑定 Agent 或节点 `tools` 中的 MCP 引用。
- 新增 API：
  - `GET /agent-tools/catalog`
  - `GET /agent-tools/mcp?server_id=`
  - `POST /agents/{id}/tools/test`（仅 Agent 所有者）
- MCP 凭据仍只存在于管理员配置的服务端，工具目录/测试响应不返回凭据。

### 广场

- `custom_agents.cover_url`（迁移 `d3e4f5a6b7c8`），仅允许站内路径或 http(s)。
- `GET /market/agents` 新增 `publisher`、`official` 参数；返回 `cover_url`、`publisher`（脱敏邮箱）、`official`（发布者为管理员）。
- `GET /market/agents/facets` 返回总数、官方/精选数量、分类与发布者计数。
- 发布快照与复制保留封面。

### 模板

- `app/services/agent_templates.py` 提供 `assistant` / `research` / `reviewed` 三个模板。
- `GET /workflows/catalog?kind=agent` 返回模板。
- `POST /agents/from-template` 在一个事务内创建 Agent + 工作流 + 版本，并填充可用模型。

## 前端

- `StudioConfigPanel`：封面 URL、temperature/max_tokens/top_p 表单；保存时归一化并提交。
- `StudioToolsSection`：内置工具勾选、MCP 服务器选择与远程工具发现、已选工具展示、JSON 参数单工具测试。
- `StudioListPage`：模板卡片与“从模板创建”对话框。
- `AgentMarketPage`：封面卡片、分类/发布者/官方/精选筛选、官方徽章。
- `AgentMarketDetailPage`：封面横幅、发布者与官方标识。
- `web/src/lib/agentSettings.ts`：生成参数文本与提交值转换，含单元测试。

## 验证

- `tests/test_p11_s4.py`：
  - Agent 参数归一化、会话继承、跨用户 404。
  - 工具目录、MCP 发现、非法/缺失 MCP 引用 422、内置与 MCP 单工具测试、非所有者拒绝。
  - 自定义 Agent 会话实际调用 MCP 工具，并验证 Agent 参数进入 provider 调用。
  - 模板目录、从模板创建 Agent/工作流/版本、重复名称与未知模板 422。
  - 封面校验、发布者/官方/精选筛选、facets 与脱敏发布者。
- 全量 `ruff check .`、`pytest -n auto`。
- `npm run typecheck`、`npm test`、`npm run build`。

## 边界

- MCP 保存时只校验服务器可用，不强制远程工具当前存在；运行/测试时不可用会返回类型化工具错误。
- MCP 工具 schema 发现为尽力而为并带进程内缓存；发现失败时使用通用对象 schema。
- 公开广场的发布者按脱敏邮箱展示与筛选，同名掩码可能合并计数。
- 模板创建只生成初始画布与 Agent 配置，不自动发布或运行。
- 真实支付、外部数据源、模板市场商业化不在本切片。