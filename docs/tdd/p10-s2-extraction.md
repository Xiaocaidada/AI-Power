# P10-S2 自动提取与候选审核

## 触发

- 助手消息 finalize 后，若 `MEMORY_EXTRACTION_ENABLED=true`，投递 Arq
  `run_memory_extraction_job(message_id)`。
- 测试环境默认关闭，避免连接真实队列；提取服务可被直接调用测试。
- 幂等：`memory_extraction_runs(source_type='message', source_id=message_id)`
  唯一；重复任务返回 `already_processed`。
- 用户消息命中“记住/请记住/别忘/remember that…”视为显式保存请求。

## 提取

- 读取：助手消息、上一条用户消息、会话（project/agent/provider/model）、
  用户记忆设置。
- 若记忆中心未开启：跳过。
- 若自动提取关闭且非显式请求：跳过。
- 使用 `ModelCompletion`（source `memory_extraction`），provider/model 优先
  `MEMORY_EXTRACTION_PROVIDER_ID/MODEL`，否则沿用消息/会话模型。
- 输入仅用户+助手文本（受 `MEMORY_EXTRACTION_MAX_CHARS` 限制）、允许分类、
  禁止主题、最近标题；不发送知识库或文档全文。
- 模型返回 JSON 数组：
  `category/title/content/scope_type/confidence/tags/reason`。
- 过滤：非法分类、低置信度、秘密模式、禁止主题、超出候选上限。

## 去重与冲突基础

- 内容哈希相同 → `duplicate`。
- 向量余弦 ≥ 0.92 → `duplicate`。
- 0.75 ≤ 余弦 < 0.92 且同分类 → `update`（target_memory_id）。
- 其余 `create`。
- 候选保存 `source_type/source_id/source_ref`、`extracted_by`、`reason`。

## 保存策略

| 条件 | 行为 |
|---|---|
| duplicate | 候选状态 `duplicate`，不写正式记忆 |
| 显式“记住” | 直接创建/更新正式记忆 |
| `auto_save=true` 且 `require_confirmation=false` 且分类在白名单 | 直接保存 |
| 其他 | 候选 `pending`，等待审核 |

候选审核：

- `GET /memories/candidates?status=pending|duplicate|accepted|rejected|merged`
- `POST /memories/candidates/{id}/accept`（可覆盖标题/内容/分类/作用域/标签）
- `POST /memories/candidates/{id}/reject`
- duplicate 候选接受时复用目标记忆，不重复创建。
- 统计新增 `candidates_pending`。

## 前端

- Memory Hub “待确认”改为候选审核列表：分类/作用域/建议动作/置信度/
  理由/标签 + 接受/拒绝。
- 总览“待确认”卡片合并正式候选计数与待审核候选数。

## 验证

- `tests/test_p10_s2.py`：
  - 提取生成候选并接受为正式记忆。
  - 显式“记住”直接保存。
  - 自动保存策略。
  - 重复检测与同消息幂等。
  - 拒绝候选不产生记忆。
- 全量 `pytest`、`ruff`、前端 typecheck/build、Memory Hub Playwright 通过。

## 边界与后续计划

- 提取以消息为单位；**跨会话/夜间 consolidation 属于 P10-S6 计划**，当前未实现。
- 冲突仅做相似度+分类判断；**语义矛盾判定属于 P10-S6 计划**，当前未实现。
- 项目/Agent 作用域从会话继承 `project_id/custom_agent_id`；若上下文缺失，
  不再静默降级自动保存，而是转 global、标记 `sensitive`、强制待确认，
  reason 写 `scope_unavailable`；接受时缺少项目/Agent 返回
  `scope_context_missing`，需用户修改作用域。
- 个人 Provider 已支持：worker 内用 `build_user_registry` 合并用户私有/共享
  Provider；仍可用 `MEMORY_EXTRACTION_PROVIDER_ID/MODEL` 固定平台 Provider。
- 秘密信息为多模式匹配（密码/API Key/Bearer/JWT/AWS/GitHub/私钥/连接串）
  加模型指令双重拦截；非绝对保证，仍建议用户审核候选。