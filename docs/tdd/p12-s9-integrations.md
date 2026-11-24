# P12-S9 多模态外部依赖（BYOK 子集）

日期：2026-11-24
状态：图片生成、STT、TTS 已完成；实时语音未实现

## 决策

按讨论结论执行：

- 用户自带 API Key（BYOK），平台不提供兜底 Key。
- 首批只承诺 OpenAI-compatible 协议；其他厂商后续加适配器。
- 实时语音需要 WebRTC/临时令牌/音频代理，单独立项，不在本切片承诺。

## 实现

### 集成配置

`integration_configs`（迁移 `b2c3d4e5f6a7`）：

- `kind`: `image_generation|stt|tts|github`
- `provider`: `openai_compatible|github`
- `base_url`、`model`、`options`
- `credentials_encrypted` + `credential_hint`（Fernet，永不返回明文）
- `shared`、`enabled`、`is_default`、`status/last_error/last_tested_at`

API `/integrations`：

- CRUD（仅 owner 可改/删/测试/设默认；共享成员可读可用）
- `POST /integrations/{id}/test`
- `GET /integrations/calls`

### 图片生成

- `POST /images/generations`：用户选择集成或默认集成，后端代理 `/images/generations`。
- 支持 `b64_json` 和返回 `url` 两种响应；响应大小、图片大小、数量、提示词长度均有上限。
- 生成图片写入 `UPLOAD_DIR/media`，记录 `media_assets`。
- `GET /media`、`GET /media/{id}`（JWT，工作区隔离，路径限制在 `UPLOAD_DIR`）、`DELETE /media/{id}`。
- 每日 03:45 worker 按 `INTEGRATION_MEDIA_RETENTION_DAYS` 清理过期媒体与文件。

### STT / TTS

- `POST /audio/transcriptions`：multipart，扩展名/大小校验，代理 `/audio/transcriptions`，返回文本。
- `POST /audio/speech`：JSON，代理 `/audio/speech`，直接返回音频字节与 MIME，不落盘。
- 语音默认模型：`whisper-1` / `tts-1`；可在集成中覆盖。

### 调用账本

`external_calls` 只追加：

- 记录 kind/provider/operation/status/error_code/duration_ms/units。
- 成功和失败都记录；不记录凭证或完整响应。
- 前端集成页展示最近调用。

### 前端

- `/settings/integrations`：图片/STT/TTS/GitHub 配置、测试、默认、删除、最近调用。
- `/media`：图片生成与画廊、STT 转写、TTS 播放。
- 认证媒体通过 `apiBlob` 拉取，再用 object URL 渲染，避免把 JWT 放进 `<img>` URL。

## 测试

`tests/test_p12_s9_integrations.py`：

- 配置 CRUD、凭证加密/掩码、跨用户 404。
- GitHub 必须提供 PAT。
- 图片生成存储媒体、下载、删除、外部调用账本。
- 未配置集成返回 `integration_not_configured`。
- STT/TTS 代理、调用账本、非法音频类型 415。
- GitHub 只读仓库/Issues 与跨用户 404。

## 边界

已解决：

- 未配置/未启用时不发外部请求，返回类型化错误。
- Key 加密且不回传；外部调用可追溯。
- 生成图片有存储、大小限制、保留期和删除。
- 失败不伪造成功。

后续/未实现：

- 实时语音（WebRTC、临时令牌、打断、TURN）未实现。
- 非 OpenAI-compatible 厂商适配器（Azure/ElevenLabs/Google）未实现。
- 图片编辑、多图参考、内容审核策略未实现。
- 媒体配额未接入 workspace 计划配额；当前只有大小/保留期限制。
- 生成图片未自动进入聊天消息或知识库。

明确不做：

- 平台代付第三方费用。
- 未配置时使用平台默认 Key 偷偷调用。
- 把长期 Key 下发前端或写入日志。