# ADR-0001: P0 技术栈与模型接入

- **Status:** Accepted
- **Date:** 2026-11-21
- **Deciders:** 项目作者
- **Related:** [`PRODUCT-BRIEF.md`](../../PRODUCT-BRIEF.md)、[`docs/product/CAPABILITY.md`](../product/CAPABILITY.md)

## Context

P0 目标是验证学习型作品的最小闭环：登录 + 流式对话 + 单知识库 RAG（带引用）。约束来自 `PRODUCT-BRIEF.md`（FastAPI + React、Postgres + pgvector、SSE、Docker Compose、不做计费/多租户）。

运行环境已有资源：

- 一台虚拟机，已通过 llama 系服务部署了 Qwen 小模型，并注册了 bge-m3 embedding 服务。
- 有可用的 DeepSeek API token。
- 开发机为 Windows，学生个人项目，成本敏感、优先可离线。

需要在写代码前锁定：provider 组合、embedding 维度、重复上传语义、部署位置。

实测（2026-11-21）：两个端点均可访问；`/v1/models` 返回上述 id；chat completion 正常；embeddings 为 1024 维；llama.cpp 返回 `usage`。

## Decision

### 1. Provider：DeepSeek API + 本地 Qwen（VM）

两者都通过 **OpenAI Chat Completions 兼容协议**接入：

| provider id | 类型 | base_url | model |
|---|---|---|---|
| `deepseek` | 远程 API | `https://api.deepseek.com`（env 可覆盖） | `deepseek-chat`（env 可覆盖） |
| `local-qwen` | VM 上的 llama.cpp（实测 `:8083`） | `http://192.168.29.100:8083/v1` | `/home/wq/models/qwen2.5-7b-instruct/qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf`（context 16384） |

实现为一个 `OpenAICompatProvider` 类 + 两套配置实例。业务层只依赖 `LLMProvider` 接口。

### 2. Embedding：本地 bge-m3，1024 维

- VM 地址 `http://192.168.29.100:8000/v1`（vLLM，OpenAI 兼容 `/v1/embeddings`），模型 id `bge-m3`；实测返回 1024 维。
- 数据库使用 `vector(1024)`，pgvector HNSW/IVFFlat 索引。
- 模型名与 base_url 走 env：`EMBEDDING_BASE_URL` / `EMBEDDING_MODEL=bge-m3` / `EMBEDDING_DIM=1024`。

### 3. 重复上传：幂等复用

同一用户、同一 `content_hash`（未删除）的文档直接返回已有记录，不重复解析/向量化。替代方案（新建版本、覆盖替换）推迟到有明确需求时再评估。

### 4. 部署：P0 先本地 Docker Compose

- API、Postgres（含 pgvector）、Redis 通过 Compose 跑在开发机。
- 模型服务留在 VM，通过 env 配置的 base_url 访问。
- 是否把 API 也搬到 VM、以及公网暴露方式，推迟到 P1（见 CAPABILITY Q3/Q5）。

## Consequences

### Positive

- 一套协议覆盖两个 provider，P0 适配器代码最少，能快速跑通 SSE 闭环。
- 本地 Qwen + bge-m3 可离线、无 API 费用；DeepSeek 提供质量对照与兜底。
- `LLMProvider` / `EmbeddingProvider` 边界保留，后续换厂商不改业务层。
- 部署与模型服务解耦，开发机与 VM 可独立演进。

### Negative / Risks

- **多厂商抽象展示偏弱**：两个 provider 共用协议，面试时"多模型抽象"的说服力下降。缓解：P1/P2 增加一个真正不同 SDK 的实现（如 `AnthropicProvider`），并用契约测试证明可插拔。
- **本地 serving 的 `usage` 兼容性**：该 llama.cpp 构建实测返回 `usage`，但仍按可空字段处理（其他 serving 可能不返回）；缺失时存 `NULL`，UI 显示 `n/a`，不伪造估算值。
- **网络与可用性**：VM 不可达、SSH 隧道断开会导致本地 provider 失败；需 fail fast + 明确错误码，不能拖垮纯远程路径。
- **TTFT 受 VM 与网络影响**：实测本地 Qwen2.5-7B Q4 冷启动 prompt 约 160ms/token、解码约 2.8 tok/s；P95 < 1.5s 只对 DeepSeek 有意义。指标必须按 provider 分开统计。
- **bge-m3 的检索质量未验证**：必须先建 50 题评测集，再调分块与 top_k（见 brief 的成功指标）。

### Alternatives Considered

| 方案 | 未采用原因 |
|---|---|
| OpenAI + Anthropic 双 SDK | 学习价值高，但国内访问与费用不可控，P0 阶段风险大于收益 |
| 智谱 + 通义 | 中文与稳定性好，但需两套签名/SDK，且与现有 VM 资源不匹配 |
| OpenAI `text-embedding-3-small` (1536) | 省事，但需外网与费用；本地 bge-m3 已就绪且中文效果足够 |
| 新建版本 / 覆盖替换重复文档 | 增加清理与"当前版本"语义，P0 无收益 |

## Follow-ups

1. Q5/Q6 已解决（地址与模型 id 见上）；剩余 Q3：API 最终部署位置。
2. 用 fake SSE 回放写契约测试，锁定两个 provider 的流式事件与 `finish_reason` 差异。
3. 建立 50 题 RAG 评测集，测 bge-m3 的 Recall@5 与引用命中率，作为调参基线。
4. P1 增加 `AnthropicProvider`（或另一个非同协议厂商），验证抽象的可插拔性。
5. 若 VM 服务鉴权缺失，补访问令牌；密钥只走 env，不进代码与日志。