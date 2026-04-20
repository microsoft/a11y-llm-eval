from a11y_llm_tests.model_config import get_model_provider, normalize_models_config


def test_normalize_models_config_builds_lookup_maps():
    normalized = normalize_models_config(
        {
            "providers": {
                "openai": {"batch": {"enabled": False}},
                "azure": {"auth": {"mode": "default_azure_credential"}},
            },
            "models": [
                {"name": "openai/gpt-4o", "display_name": "GPT-4o"},
                {"name": "azure/my-deployment"},
            ],
        }
    )

    assert normalized["model_names"] == ["openai/gpt-4o", "azure/my-deployment"]
    assert normalized["model_display_lookup"]["openai/gpt-4o"] == "GPT-4o"
    assert normalized["model_display_lookup"]["azure/my-deployment"] == "my-deployment"
    assert normalized["model_provider_lookup"]["openai/gpt-4o"] == {"batch": {"enabled": False}}
    assert normalized["model_provider_lookup"]["azure/my-deployment"] == {
        "auth": {"mode": "default_azure_credential"}
    }
    assert normalized["models"][0]["inspect_model"] == "openai/gpt-4o"


def test_get_model_provider_handles_provider_prefix():
    assert get_model_provider("openai/gpt-4o") == "openai"
    assert get_model_provider("openai/azure/gpt-5.4-mini") == "azure"
    assert get_model_provider("claude-sonnet-4-20250514") == "unknown"