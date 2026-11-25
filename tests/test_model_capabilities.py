from app.services.model_capabilities import (
    effective_capabilities,
    supports_tools_by_name,
)


def test_zhipu_glm_models_infer_tool_calling():
    assert supports_tools_by_name("glm-4.5-air")
    assert supports_tools_by_name("GLM-4.6")
    assert supports_tools_by_name("zhipu/glm-4.5-air")
    assert supports_tools_by_name("glm-5.4")
    assert "tools" in effective_capabilities("glm-4.5-air", ["chat", "stream"], "synced")


def test_unknown_models_keep_default_capabilities():
    assert not supports_tools_by_name("some-unknown-model")
    assert effective_capabilities("some-unknown-model", ["chat", "stream"], "synced") == [
        "chat",
        "stream",
    ]


def test_manual_capabilities_override_inference():
    assert effective_capabilities("glm-4.5-air", ["chat", "stream"], "manual") == [
        "chat",
        "stream",
    ]
