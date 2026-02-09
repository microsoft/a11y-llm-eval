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

    monkeypatch.setattr(generator.litellm, "completion", _completion)

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


def test_temperature_sent_for_non_codex_models(monkeypatch, tmp_path):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    captured = {}

    def _completion(**kwargs):
        captured.update(kwargs)
        return _FakeResp("<html><head></head><body>ok</body></html>")

    monkeypatch.setattr(generator.litellm, "completion", _completion)

    generator.generate_html_with_meta(
        model="azure/gpt-5.2",
        user_prompt="make a page",
        iteration=0,
        temperature=0.2,
        seed=None,
        disable_cache=True,
    )

    assert captured.get("temperature") == 0.2
