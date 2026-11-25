# Provider 模型能力推断修复（智谱 GLM 工具调用）

日期：2026-11-25
状态：已修复并部署

## 问题

用户 Provider 同步后，所有模型能力固定为 `chat` + `stream`，包括支持工具调用的智谱 GLM-4.5-Air / GLM-4.x / GLM-5.x。前端因此禁用 Agent 模式，后端切换 Agent 模式也返回 `capability_unsupported`。

根因：

- `sync_models` 对新增模型使用固定 `DEFAULT_CAPABILITIES`。
- Provider `/v1/models` 只返回模型 id，不返回工具能力。
- 前端新增模型固定发送 `["chat","stream"]`。
- 已有同步模型不会在读取或校验时补推断能力。

## 修复

新增 `app/services/model_capabilities.py`：

- 维护已知支持工具调用的模型族前缀。
- `supports_tools_by_name` 支持带供应商前缀的 id，例如 `zhipu/glm-4.5-air`。
- `effective_capabilities` 只对 `source="synced"` 的模型补 `tools`；手动编辑能力（`source="manual"`）优先。

接入点：

- `sync_models`：新增同步模型和已有 synced 默认模型写入推断能力；manual 模型不被覆盖。
- `add_model`：未显式提供能力或仅提供默认能力时，按模型 id 推断。
- `update_model`：显式修改能力后标记 `source="manual"`，后续同步不再覆盖。
- `accessible_models`、`ensure_model_capability`、`resolve_model_capabilities`：读取/校验时使用有效能力，因此已有数据库记录无需重新同步即可生效。
- `/provider-configs/{id}/models` 的列表、创建、修改响应统一返回有效能力。

覆盖的 GLM 前缀：

- `glm-4`（含 GLM-4.5-Air、GLM-4.6、GLM-4.7、GLM-4-Flash、GLM-4-Plus）
- `glm-5`（含 GLM-5、GLM-5.x、GLM-5-Turbo）

同时覆盖常见工具调用模型族：GPT-4/5、o 系列、DeepSeek-Chat、Qwen 2.5/3、Claude、Gemini、Mistral、Command-R。

## 验证

- `tests/test_model_capabilities.py`：GLM-4.5-Air、GLM-4.6、GLM-5.4、`zhipu/` 前缀、未知模型、手动覆盖。
- `tests/test_provider_configs.py`：同步 `glm-4.5-air` 后模型能力包含 `tools`，个人模型接口返回有效能力，会话可切换到 Agent 模式。
- 定向测试：`test_model_capabilities.py`、`test_provider_configs.py`、`test_p12_s1_chat_modes.py` 全部通过。
- 全量后端 `pytest -n auto` 通过（exit 0）。
- 部署后实测：通过 API 新建临时 Provider 并添加 `glm-4.5-air`，模型创建响应、Provider 模型列表和 `/provider-configs/models` 均返回 `["chat","stream","tools"]`；临时配置已删除。

## 边界

- 名称推断只覆盖已知模型族；其他模型仍需手动能力配置。
- 同步接口不提供模型能力元数据，无法对任意模型做协议级探测。
- 现有数据库记录不需要迁移：读取和校验时使用有效能力；下次同步会写回推断结果。
- 未新增前端能力编辑器；如需手动修正非已知模型，可调用 `PATCH /provider-configs/{id}/models/{model_id}`。