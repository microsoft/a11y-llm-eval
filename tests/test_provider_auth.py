import builtins
import sys
import types

import pytest
from typer.testing import CliRunner

from a11y_llm_tests import generator
from a11y_llm_tests.cli import app


@pytest.fixture(autouse=True)
def reset_prompts():
    generator.configure_prompts(None, None)
    yield
    generator.configure_prompts(None, None)


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str):
        self.message = _FakeMessage(content)
        self.finish_reason = None
        self.stop_reason = None


class _FakeResp:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]
        self.usage = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
        self.response_cost = 0.01


def test_generate_html_with_meta_uses_provider_default_azure_credential(monkeypatch, tmp_path):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("AZURE_API_BASE", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_API_VERSION", "2024-10-21")

    captured = {}

    def _completion(**kwargs):
        captured.update(kwargs)
        return _FakeResp("<html><head></head><body>ok</body></html>")

    monkeypatch.setattr(generator.litellm, "completion", _completion)

    fake_azure = types.ModuleType("azure")
    fake_identity = types.ModuleType("azure.identity")

    class _FakeDefaultAzureCredential:
        pass

    def _fake_get_bearer_token_provider(credential, scope):
        captured["credential_type"] = type(credential).__name__
        captured["scope"] = scope
        return "token-provider"

    fake_identity.DefaultAzureCredential = _FakeDefaultAzureCredential
    fake_identity.get_bearer_token_provider = _fake_get_bearer_token_provider
    monkeypatch.setitem(sys.modules, "azure", fake_azure)
    monkeypatch.setitem(sys.modules, "azure.identity", fake_identity)

    generator.generate_html_with_meta(
        model="azure/my-deployment",
        user_prompt="make a page",
        iteration=0,
        disable_cache=True,
        provider_config={
            "auth": {
                "mode": "default_azure_credential",
            }
        },
    )

    assert captured["api_base"] == "https://example.openai.azure.com"
    assert captured["api_version"] == "2024-10-21"
    assert captured["azure_ad_token_provider"] == "token-provider"
    assert captured["credential_type"] == "_FakeDefaultAzureCredential"
    assert captured["scope"] == "https://cognitiveservices.azure.com/.default"


def test_generate_html_with_meta_omits_optional_api_version(monkeypatch, tmp_path):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("AZURE_API_BASE", "https://example.openai.azure.com")
    monkeypatch.delenv("AZURE_API_VERSION", raising=False)

    captured = {}

    def _completion(**kwargs):
        captured.update(kwargs)
        return _FakeResp("<html><head></head><body>ok</body></html>")

    monkeypatch.setattr(generator.litellm, "completion", _completion)

    fake_azure = types.ModuleType("azure")
    fake_identity = types.ModuleType("azure.identity")

    class _FakeDefaultAzureCredential:
        pass

    def _fake_get_bearer_token_provider(credential, scope):
        return "token-provider"

    fake_identity.DefaultAzureCredential = _FakeDefaultAzureCredential
    fake_identity.get_bearer_token_provider = _fake_get_bearer_token_provider
    monkeypatch.setitem(sys.modules, "azure", fake_azure)
    monkeypatch.setitem(sys.modules, "azure.identity", fake_identity)

    generator.generate_html_with_meta(
        model="azure/my-deployment",
        user_prompt="make a page",
        iteration=0,
        disable_cache=True,
        provider_config={
            "auth": {
                "mode": "default_azure_credential",
            }
        },
    )

    assert captured["api_base"] == "https://example.openai.azure.com"
    assert "api_version" not in captured


def test_generate_html_with_meta_raises_when_optional_dependency_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    monkeypatch.delenv("AZURE_API_BASE", raising=False)
    monkeypatch.delenv("AZURE_API_VERSION", raising=False)
    monkeypatch.delitem(sys.modules, "azure.identity", raising=False)
    monkeypatch.delitem(sys.modules, "azure", raising=False)

    original_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "azure.identity":
            raise ImportError("missing optional dependency")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    with pytest.raises(RuntimeError, match="azure-identity is not installed"):
        generator.generate_html_with_meta(
            model="azure/my-deployment",
            user_prompt="make a page",
            iteration=0,
            disable_cache=True,
            provider_config={
                "auth": {
                    "mode": "default_azure_credential",
                }
            },
        )


def test_cli_passes_provider_config_to_generator(monkeypatch, tmp_path):
    captured = {}

    def fake_generate_html_with_meta(model, prompt, iteration, temperature=None, seed=None, disable_cache=False, provider_config=None, **kwargs):
        captured["model"] = model
        captured["provider_config"] = provider_config
        return "<html><body>ok</body></html>", {
            "cached": False,
            "latency_s": 0.01,
            "prompt_hash": "deadbeef",
            "tokens_in": 1,
            "tokens_out": 2,
            "total_tokens": 3,
            "cost_usd": 0.0001,
            "seed": seed,
            "temperature": temperature,
        }

    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", fake_generate_html_with_meta)

    tc_dir = tmp_path / "test_cases" / "sample-case"
    tc_dir.mkdir(parents=True)
    (tc_dir / "prompt.yaml").write_text("base_prompt: |\n  Generate a page\n", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text(
        """
providers:
  azure:
    auth:
      mode: default_azure_credential
models:
  - name: azure/test-deployment
""".strip() + "\n",
        encoding="utf-8",
    )
    (config_dir / "prompt_dimensions.yaml").write_text("dimensions: {}\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, [
        "run",
        "--models-file", str(config_dir / "models.yaml"),
        "--prompt-dimensions-file", str(config_dir / "prompt_dimensions.yaml"),
        "--out", str(tmp_path / "runs"),
        "--test-cases-dir", str(tmp_path / "test_cases"),
        "--samples", "1",
        "--processes", "1",
    ])

    assert result.exit_code == 0, result.output
    assert captured["model"] == "azure/test-deployment"
    assert captured["provider_config"] == {"auth": {"mode": "default_azure_credential"}}