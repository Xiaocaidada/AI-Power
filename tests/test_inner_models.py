import json
from pathlib import Path

from app.config import get_settings
from app.services.inner_models import load_inner_models

CATALOG = {
    "object": "list",
    "data": [
        {
            "id": "glm-4.5",
            "object": "model",
            "created": 1753632000,
            "owned_by": "z-ai",
            "context_window": 128000,
            "max_output_tokens": 96000,
            "tool_calling": True,
            "type": "text",
            "thinking": {"supported": True, "required": False, "levels": []},
        },
        {
            "id": "glm-5.4",
            "object": "model",
            "created": 1795406400,
            "owned_by": "z-ai",
            "context_window": 1000000,
            "max_output_tokens": 128000,
            "tool_calling": True,
            "type": "multimodal",
            "thinking": {
                "supported": True,
                "required": True,
                "levels": ["low", "high", "max"],
            },
        },
    ],
}


def _catalog_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "inner_models"
    directory.mkdir()
    (directory / "zhipu_models.json").write_text(
        json.dumps(CATALOG, ensure_ascii=False), encoding="utf-8"
    )
    return directory


def _configure(monkeypatch, directory: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "inner_models_dir", str(directory))
    monkeypatch.setattr(settings, "inner_models_providers", "zhipu")


def test_loader_normalizes_zhipu_metadata(monkeypatch, tmp_path):
    _configure(monkeypatch, _catalog_dir(tmp_path))

    models = load_inner_models()

    assert [model.model_id for model in models] == ["glm-4.5", "glm-5.4"]
    first = models[0]
    assert first.name == "GLM-4.5"
    assert first.provider_id == "zhipu"
    assert first.provider_name == "智谱 AI"
    assert first.slug == "zhipu-glm-4-5"
    assert first.context_window == 128000
    assert first.max_output == 96000
    assert "tools" in first.capabilities
    assert "reasoning" in first.capabilities
    assert first.thinking_supported is True
    assert first.thinking_levels == []
    assert first.provider_base_url == "https://open.bigmodel.cn/api/paas/v4"

    multimodal = models[1]
    assert multimodal.name == "GLM-5.4"
    assert multimodal.category == "multimodal"
    assert multimodal.input_types == ["image", "text"]
    assert multimodal.thinking_required is True
    assert multimodal.thinking_levels == ["low", "high", "max"]
    assert "vision" in multimodal.capabilities


async def test_public_market_lists_builtin_models(monkeypatch, tmp_path, client):
    _configure(monkeypatch, _catalog_dir(tmp_path))

    response = await client.get("/market/models?provider_id=zhipu")

    assert response.status_code == 200
    body = response.json()
    assert [item["model_id"] for item in body] == ["glm-4.5", "glm-5.4"]
    model = body[1]
    assert model["catalog"] is True
    assert model["available"] is False
    assert model["provider_base_url"] == "https://open.bigmodel.cn/api/paas/v4"
    assert model["thinking_levels"] == ["low", "high", "max"]
    assert model["capabilities"] == [
        "chat",
        "stream",
        "tools",
        "vision",
        "reasoning",
    ]

    detail = await client.get("/market/models/zhipu-glm-5-4")
    assert detail.status_code == 200
    assert detail.json()["name"] == "GLM-5.4"


def _write_provider(directory: Path, name: str, entries: list[dict]) -> None:
    (directory / f"{name}_models.json").write_text(
        json.dumps({"object": "list", "data": entries}, ensure_ascii=False),
        encoding="utf-8",
    )


async def test_provider_catalog_and_catalog_filters(monkeypatch, tmp_path, client):
    directory = _catalog_dir(tmp_path)
    _write_provider(
        directory,
        "openai",
        [
            {
                "id": "gpt-4o-2024-11-20",
                "model_type": "multimodal",
                "tool_calling": True,
                "thinking_mode": False,
            },
            {"id": "whisper-1", "model_type": "audio"},
        ],
    )
    _write_provider(
        directory,
        "aliyun",
        [
            {
                "id": "qwen3-coder-flash-2025-07-28",
                "model_type": "code",
                "tool_calling": True,
                "thinking_mode": "支持思考",
            }
        ],
    )
    settings = get_settings()
    monkeypatch.setattr(settings, "inner_models_dir", str(directory))
    monkeypatch.setattr(settings, "inner_models_providers", "*")

    providers = await client.get("/market/providers")
    assert providers.status_code == 200
    counts = {item["provider_id"]: item["model_count"] for item in providers.json()}
    assert counts == {"zhipu": 2, "openai": 1, "aliyun": 1}

    openai = await client.get("/market/models?catalog=true&provider_id=openai")
    assert openai.status_code == 200
    assert [item["name"] for item in openai.json()] == ["GPT-4o (2024-11-20)"]

    aliyun = await client.get("/market/models?catalog=true&provider_id=aliyun")
    assert aliyun.json()[0]["name"] == "Qwen3 Coder Flash (2025-07-28)"
    assert aliyun.json()[0]["category"] == "coding"

    limited = await client.get("/market/models?catalog=true&limit=1")
    assert len(limited.json()) == 1

    first_page = await client.get("/market/models/page?catalog=true&per_page=2&page=1")
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 4
    assert first_page.json()["page"] == 1
    assert len(first_page.json()["items"]) == 2
    second_page = await client.get("/market/models/page?catalog=true&per_page=2&page=2")
    assert len(second_page.json()["items"]) == 2
    assert (
        first_page.json()["items"][0]["id"] != second_page.json()["items"][0]["id"]
    )

    empty = await client.get("/market/models?catalog=false")
    assert empty.status_code == 200
    assert empty.json() == []


async def test_activate_builtin_model_with_user_credentials(
    monkeypatch, tmp_path, client, api
):
    _configure(monkeypatch, _catalog_dir(tmp_path))
    headers = await api.headers("inner-models@example.com")
    payload = {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key": "sk-user-secret-1234",
    }

    response = await client.post(
        "/market/models/zhipu-glm-5-4/activate", json=payload, headers=headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model_id"] == "glm-5.4"
    assert body["provider_name"] == "智谱 AI"
    assert "sk-user-secret-1234" not in response.text

    configs = await client.get("/provider-configs", headers=headers)
    assert configs.status_code == 200
    assert len(configs.json()) == 1
    config = configs.json()[0]
    assert config["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
    assert config["api_key_hint"].endswith("1234")
    assert "sk-user-secret-1234" not in configs.text

    models = await client.get("/provider-configs/models", headers=headers)
    assert models.status_code == 200
    model = models.json()[0]
    assert model["model_id"] == "glm-5.4"
    assert model["context_window"] == 1000000
    assert model["max_output"] == 128000
    assert model["capabilities"] == ["chat", "reasoning", "stream", "tools", "vision"]
    assert model["reasoning_levels"] == ["low", "high", "max"]
    assert [item["id"] for item in model["thinking_config"]] == ["low", "high", "max"]

    again = await client.post(
        "/market/models/zhipu-glm-5-4/activate",
        json={**payload, "api_key": "sk-rotated-5678"},
        headers=headers,
    )
    assert again.status_code == 200
    assert len((await client.get("/provider-configs", headers=headers)).json()) == 1