import pytest

from a11y_llm_tests import generator


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


def test_temperature_omitted_for_codex_models(monkeypatch, tmp_path):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    captured = {}

    def _completion(**kwargs):
        captured.update(kwargs)
        return _FakeResp("<html><head></head><body>ok</body></html>")

    monkeypatch.setattr(generator.generation_runtime, "completion", _completion)

    html, meta = generator.generate_html_with_meta(
        model="azure/gpt-5.2-codex",
        user_prompt="make a page",
        iteration=0,
        temperature=0.2,
        seed=None,
        disable_cache=True,
    )

    assert "temperature" not in captured
    assert "</html>" in html.lower()
    assert meta["temperature"] == 0.2


def test_temperature_omitted_when_none_for_non_codex_models(monkeypatch, tmp_path):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    captured = {}

    def _completion(**kwargs):
        captured.update(kwargs)
        return _FakeResp("<html><head></head><body>ok</body></html>")

    monkeypatch.setattr(generator.generation_runtime, "completion", _completion)

    generator.generate_html_with_meta(
        model="azure/gpt-5.2",
        user_prompt="make a page",
        iteration=0,
        temperature=None,
        seed=None,
        disable_cache=True,
    )

    assert "temperature" not in captured


def test_temperature_sent_for_non_codex_models_when_set(monkeypatch, tmp_path):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    captured = {}

    def _completion(**kwargs):
        captured.update(kwargs)
        return _FakeResp("<html><head></head><body>ok</body></html>")

    monkeypatch.setattr(generator.generation_runtime, "completion", _completion)

    generator.generate_html_with_meta(
        model="azure/gpt-5.2",
        user_prompt="make a page",
        iteration=0,
        temperature=0.2,
        seed=None,
        disable_cache=True,
    )

    assert captured.get("temperature") == 0.2


def test_retry_log_includes_model_display_name_and_provider_env_status(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(generator, "RETRY_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(generator.random, "uniform", lambda a, b: 0.0)
    monkeypatch.setattr(generator.time, "sleep", lambda _: None)

    monkeypatch.setenv("AZURE_AI_API_BASE", "https://example.services.ai.azure.com/models")
    monkeypatch.delenv("AZURE_AI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_AI_API_VERSION", raising=False)

    calls = {"n": 0}

    def _completion(**kwargs):
        calls["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(generator.generation_runtime, "completion", _completion)

    with pytest.raises(RuntimeError, match="boom"):
        generator.generate_html_with_meta(
            model="azure_ai/DeepSeek-V3.2",
            model_display_name="DeepSeek V3.2",
            user_prompt="make a page",
            iteration=0,
            disable_cache=True,
        )

    assert calls["n"] == 2
    captured = capsys.readouterr()
    assert "model=DeepSeek V3.2 [azure_ai/DeepSeek-V3.2]" in captured.out
    assert "provider=azure_ai" in captured.out
    assert "AZURE_AI_API_BASE=set" in captured.out
    assert "AZURE_AI_API_KEY=missing" in captured.out
