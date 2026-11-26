# 内置模型目录与模型广场 BYOK 激活

日期：2026-11-25
状态：已实现

## 目标

`inner_models/zhipu_models.json` 提供模型元数据（上下文、最大输出、工具调用、多模态、思考等级），用于模型广场展示。平台不内置任何模型密钥：用户选择模型时必须自行填写 Base URL 与 API Key，保存后模型进入「我的模型」，可直接在对话中选择。

## 数据来源

- 目录：`INNER_MODELS_DIR`，默认 `inner_models`（Docker 镜像已包含）。
- 启用文件：`INNER_MODELS_PROVIDERS`，默认 `*`（当前为智谱、阿里云、OpenAI、DeepSeek 四个文件）；逗号分隔，空值关闭内置目录。
- 文件名 `zhipu_models.json` → provider_id `zhipu`；内置 Provider 名与默认 Base URL 见 `app/services/inner_models.py` 的 `PROVIDER_CATALOG`。
- 支持字段：`context_window`/`max_context`、`max_output_tokens`/`max_output`、`tool_calling`、`type`/`model_type`、`thinking`/`effort`/`thinking_mode`、`input_modalities`/`output_modalities`。
- 非对话类型（audio/realtime/image/image_generation/moderation/embedding/reranker/vision_ocr）不进入广场。
- `created` 在 180 天内标记为「新发布」。

派生规则：

- 能力：`chat`、`stream` 固定；`tools` 来自 `tool_calling`；`vision` 来自图片输入；`reasoning` 来自思考支持。
- 分类：多模态 → `multimodal`；代码 → `coding`；思考 → `reasoning`；其余 `general`。
- slug：`{provider}-{model}`（如 `zhipu-glm-5-4`）。
- 确定性 UUID：`uuid5(provider_id, model_id)`，无需持久化即可稳定引用。

## API

- `GET /market/models`：数据库上架模型与内置目录合并；同一 `(provider_id, model_id)` 以数据库记录优先；过滤与排序对两者一致。新增 `catalog=true|false` 只取内置/只取数据库模型，`limit=1..100` 限制首页返回量。
- `GET /market/models/page`：与列表相同的过滤/排序，额外返回 `items`、`total`、`page`、`per_page`（默认 24，最大 100），供模型广场分页。
- `GET /market/providers`：公开的内置 Provider 摘要（名称、模型数、默认 Base URL、文档地址）；当前返回阿里云百炼 159、OpenAI 55、智谱 13、DeepSeek 2。
- `GET /market/models/{slug}`：先查数据库，再回退内置目录。
- `POST /market/models/{slug}/activate`（JWT）：
  - 入参：`base_url`、`api_key`、可选 `provider_name`。
  - 行为：按 Provider 名复用或创建 `provider_configs`（Key 加密保存），并 upsert 一条 `provider_models`，写入能力、上下文、最大输出与 `thinking_config`。
  - 返回：`provider_id`、`model_id`、`name`、`provider_name`；不返回密钥。
  - 同一 Provider 名重复激活不会创建重复配置，可轮换 Key/Base URL。

新增响应字段：`catalog`、`provider_base_url`、`thinking_supported`、`thinking_required`、`thinking_levels`。

## 前端

- 首页：
  - 新增「内置模型提供商」卡片（数量、默认 Base URL，链接到按 Provider 过滤的广场）。
  - 「系统内置模型」改为轮播：每个 Provider 取 2 个模型，共 8 个，4/2/1 列响应式，左右箭头与 5 秒自动轮播，悬停暂停；不再重复展示推荐/最新模型区块。
- `/models` 公共广场：
  - 内置模型显示「配置并体验」；登录后弹窗填写 Base URL（预填默认值）与 API Key。
  - 已配置的模型显示「已配置」并直接进入对话。
  - 新增 Provider 筛选；列表按 24 条分页，显示总数与上一页/下一页。
  - 详情弹窗展示思考等级。
- `/models/:slug`：
  - 已配置或平台可用 → 立即体验；内置未配置 → 配置并体验；其余 → 配置提供商。
  - 概览展示思考等级。
- 激活成功后跳转 `/chat?provider=<配置ID>&model=<模型ID>`，新会话自动选中该模型与思考等级。
- 思考选择器对 `minimal/low/medium/high/xhigh/max` 提供本地化名称。

## 测试

- `tests/test_inner_models.py`：目录归一化、Provider 摘要、`catalog`/`limit` 过滤、分页总数与翻页、公开详情、激活写入个人 Provider、重复激活复用配置、响应不含明文 Key。
- `tests/conftest.py`：默认关闭内置目录，避免影响既有市场用例。
- 前端 `typecheck`、Vitest、生产构建通过。
- 浏览器实测：广场共 229 个模型，Provider 筛选可切到 OpenAI 55 个；分页显示「第 1 / 10 页 · 共 229 个模型」并可翻页；首页展示 4 个 Provider 卡片与 8 个内置模型轮播（箭头可切换、自动轮播）；填写 Base URL/Key 激活 GLM-5.4 后进入对话，模型为 GLM-5.4、思考等级为「低」；再次进入广场显示「已配置 / 立即体验」；详情页展示思考等级与立即体验。

## 边界

- 激活只保存配置，不校验 Key 是否可用；用户可在 `/settings/providers` 测试连接。
- 内置目录只读；管理员对同名 `(provider_id, model_id)` 的数据库记录可覆盖展示。
- 默认只启用 `zhipu`；启用其它文件需设置 `INNER_MODELS_PROVIDERS`。
- 文件声明「支持思考」但 `levels` 为空（如 GLM-4.5）时按原样导入，激活后思考选择器只有「标准」；需要具体等级可在 `/settings/providers` 的模型能力配置中补充。
- 直接访问 `/models/:slug/playground` 仍使用广场 `provider_id`，内置模型应通过激活后的对话入口体验。
- `reasoning_effort` 之外的厂商专有思考参数尚未映射。