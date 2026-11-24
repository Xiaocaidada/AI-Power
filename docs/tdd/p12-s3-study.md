# P12-S3 学习模式

日期：2026-11-24
状态：已完成（学习模式 MVP）

## 目标

在 `study` 对话模式上提供可恢复的学习会话、结构化测验、自动判分、错题解析与掌握度建议，
同时不把普通聊天自动当作学习记录。

## 实现

### 数据

- `study_sessions`：
  - `workspace_id`、`user_id`、`conversation_id`
  - `topic`、`level`（beginner/intermediate/advanced）
  - `mode`（explain/guided/practice/quiz/review）
  - `goals`、`kb_ids`
  - `status`（active/completed/archived）
  - `mastery` JSON（已答/正确/正确率/薄弱点/建议）
- `study_attempts`：
  - `session_id`、`question` JSON
  - `answer`、`score`、`feedback`、`status`（pending/graded）
  - `created_at`、`graded_at`
- 迁移：`f7a8b9c0d1e2_p12_s3_study.py`。

### API

- `GET/POST /study/sessions`
- `GET/PATCH/DELETE /study/sessions/{id}`
- `POST /study/sessions/{id}/quiz`
- `POST /study/sessions/{id}/attempts/{attempt_id}/answer`

会话按 workspace + user 隔离，跨用户统一 404。

### 测验与判分

- 生成通过 `ModelCompletion`（`usage_events.source='study'`），要求严格 JSON。
- MVP 题型：单选、多选、判断、简答。
- 服务端校验题型、选项、答案，非法题目丢弃；无有效题目返回
  `502 quiz_generation_failed`。
- 待答题响应不暴露 `correct_answer`/`explanation`；判分后才返回。
- 判分：
  - 单选/判断：单个答案精确匹配。
  - 多选：集合完全一致。
  - 简答：规范化后与可接受答案列表精确匹配（不做语义判分）。
- 错误答案反馈包含正确答案与解析；重复提交返回 `409 attempt_already_graded`。
- 每次判分后重算掌握度与复习建议。

### 聊天集成

- `study` 模式要求 `mode_meta.study_session_id`，缺失返回 `422 study_session_required`。
- 会话必须属于当前用户和 workspace，且与当前对话匹配。
- 注入系统提示：主题、难度、学习方式、目标、已答/正确率、薄弱点。
- 学习会话的 `kb_ids` 优先于对话知识库用于检索。
- 普通聊天/其他模式不会创建 `study_attempts`。
- 重新生成沿用同一条用户消息的 `study_session_id`。

### 前端

- 新建学习对话时可在高级设置中选择难度、学习方式和目标；首条消息前创建学习会话。
- 对话页学习模式显示学习面板：
  - 学习会话选择/新建
  - 掌握度、正确率、薄弱点与复习建议
  - 生成 3/5/10 道练习
  - 单选/多选/判断/简答答题与提交
  - 错题解析与历史答题
- 没有学习会话时禁用发送，面板提供创建入口。

## 测试

- `tests/test_p12_s3_study.py`：
  - 会话创建/读取、跨用户 404。
  - study 模式缺会话 422。
  - 聊天系统提示包含主题/难度。
  - 测验生成、待答题隐藏答案、非法 JSON 502。
  - 判分、错题解析、掌握度/建议、重复提交 409。
  - 普通聊天不产生学习记录。
  - 重新生成沿用学习会话。
- 全量：`ruff check .`、`pytest -n auto`、`npm run typecheck`、`npm test -- --run`、`npm run build`。

## 边界

已解决：

- 会话恢复、学习模式上下文注入、结构化题目、自动判分、错题解析与掌握度。
- 普通聊天不会被记为学习答题。
- 待答题不泄露答案/解析。
- 跨用户/跨工作区隔离。

后续切片：

- 简答语义判分 / LLM 判分：需要额外的判分成本与一致性策略。
- 学习会话的班级、作业、课程体系：不做。
- 学习报告导出、间隔复习计划：P12-S4 或后续。
- 题库共享、错题本跨会话聚合：后续增强。

明确不做（真实外部集成）：

- 不接入学校 LMS、班级、作业提交或第三方课程系统。
- 不伪造学习时长、证书或成绩单。

需要用户决策：

- 简答是否启用 LLM 判分及其成本上限。
- 是否允许学习会话共享给工作区其他成员（当前仅本人可见）。