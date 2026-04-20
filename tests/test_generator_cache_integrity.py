import pytest

from a11y_llm_tests import generator
from a11y_llm_tests.utils import sha256_hex


@pytest.fixture(autouse=True)
def reset_prompts():
    generator.configure_prompts(None, None)
    yield
    generator.configure_prompts(None, None)


class _FakeMessage:
    def __init__(self, content: str):
        self.content = content


class _FakeChoice:
    def __init__(self, content: str, finish_reason: str | None = None, stop_reason: str | None = None):
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason
        self.stop_reason = stop_reason


class _FakeResp:
    def __init__(self, content: str, finish_reason: str | None = None, stop_reason: str | None = None):
        self.choices = [_FakeChoice(content, finish_reason=finish_reason, stop_reason=stop_reason)]
        self.usage = {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3}
        self.response_cost = 0.01


def _cache_path(tmp_path, model: str, prompt: str, iteration: int, seed=None):
    h = generator.compute_prompt_hash(prompt)
    seed_part = f"_s{seed}" if seed is not None else ""
    return tmp_path / "generations" / f"{model}_{h}{seed_part}_i{iteration}.html"


def test_corrupted_cached_html_is_detected_and_regenerated(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    model = "fake-model"
    prompt = "make a page"
    iteration = 0

    cache_file = _cache_path(tmp_path, model, prompt, iteration)
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    # Write a truncated HTML file (missing closing tags)
    cache_file.write_text("<html><body><h1>cut off", encoding="utf-8")

    good_html = (
        "<html><head><title>x</title></head><body>"
        + ("hello " * 20)
        + "</body></html>"
    )

    monkeypatch.setattr(generator.generation_runtime, "completion", lambda **kwargs: _FakeResp(good_html))

    html, meta = generator.generate_html_with_meta(
        model=model,
        user_prompt=prompt,
        iteration=iteration,
        temperature=None,
        seed=None,
        disable_cache=False,
    )

    assert meta["cached"] is False
    assert "</html>" in html.lower()

    # Cache should now be repaired and include checksum sidecar
    repaired = cache_file.read_text(encoding="utf-8")
    assert repaired == html
    checksum_path = cache_file.with_suffix(cache_file.suffix + ".sha256")
    assert checksum_path.exists()
    assert checksum_path.read_text(encoding="utf-8").strip() == sha256_hex(repaired.encode("utf-8"))


def test_retry_once_on_truncation(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    model = "fake-model"
    prompt = "make a page"
    iteration = 0

    truncated = "<html><body>oops"  # missing closing tags
    good_html = (
        "<html><head><title>x</title></head><body>"
        + ("ok " * 30)
        + "</body></html>"
    )

    calls = {"n": 0}

    def _completion(**kwargs):
        calls["n"] += 1
        return _FakeResp(truncated if calls["n"] == 1 else good_html)

    monkeypatch.setattr(generator.generation_runtime, "completion", _completion)

    html, meta = generator.generate_html_with_meta(
        model=model,
        user_prompt=prompt,
        iteration=iteration,
        temperature=None,
        seed=None,
        disable_cache=True,
    )

    assert calls["n"] == 2
    assert meta["cached"] is False
    assert "</html>" in html.lower()


def test_checksum_mismatch_invalidates_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    model = "fake-model"
    prompt = "make a page"
    iteration = 0

    cache_file = _cache_path(tmp_path, model, prompt, iteration)
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    original_html = (
        "<html><head><title>orig</title></head><body>"
        + ("orig " * 30)
        + "</body></html>"
    )
    cache_file.write_text(original_html, encoding="utf-8")

    # Wrong checksum
    checksum_path = cache_file.with_suffix(cache_file.suffix + ".sha256")
    checksum_path.write_text("deadbeef\n", encoding="utf-8")

    regenerated_html = (
        "<html><head><title>new</title></head><body>"
        + ("new " * 30)
        + "</body></html>"
    )
    monkeypatch.setattr(generator.generation_runtime, "completion", lambda **kwargs: _FakeResp(regenerated_html))

    html, meta = generator.generate_html_with_meta(
        model=model,
        user_prompt=prompt,
        iteration=iteration,
        temperature=None,
        seed=None,
        disable_cache=False,
    )

    assert meta["cached"] is False
    assert html == regenerated_html
    assert cache_file.read_text(encoding="utf-8") == regenerated_html
    assert checksum_path.read_text(encoding="utf-8").strip() == sha256_hex(regenerated_html.encode("utf-8"))


def test_valid_cache_hit_skips_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    model = "fake-model"
    prompt = "make a page"
    iteration = 0

    cache_file = _cache_path(tmp_path, model, prompt, iteration)
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    cached_html = (
        "<html><head><title>cached</title></head><body>"
        + ("cached " * 30)
        + "</body></html>"
    )
    cache_file.write_text(cached_html, encoding="utf-8")

    checksum_path = cache_file.with_suffix(cache_file.suffix + ".sha256")
    checksum_path.write_text(sha256_hex(cached_html.encode("utf-8")) + "\n", encoding="utf-8")

    def _boom(**kwargs):
        raise AssertionError("generation runtime should not be called on cache hit")

    monkeypatch.setattr(generator.generation_runtime, "completion", _boom)

    html, meta = generator.generate_html_with_meta(
        model=model,
        user_prompt=prompt,
        iteration=iteration,
        temperature=None,
        seed=None,
        disable_cache=False,
    )

    assert meta["cached"] is True
    assert html == cached_html


def test_finish_reason_length_exits_fast_no_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    model = "fake-model"
    prompt = "make a big page"

    calls = {"n": 0}

    def _completion(**kwargs):
        calls["n"] += 1
        # Provider indicates output was cut due to length.
        return _FakeResp("<html><body>cut", finish_reason="length")

    monkeypatch.setattr(generator.generation_runtime, "completion", _completion)

    with pytest.raises(generator.OutputTokenLimitHit):
        generator.generate_html_with_meta(
            model=model,
            user_prompt=prompt,
            iteration=0,
            disable_cache=True,
        )

    # Ensure we didn't waste tokens on the truncation retry path.
    assert calls["n"] == 1


def test_debug_truncated_cache_preserves_file_and_reports(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    model = "fake-model"
    prompt = "make a page"
    iteration = 0

    cache_file = _cache_path(tmp_path, model, prompt, iteration)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("<html><body><h1>cut off", encoding="utf-8")

    good_html = (
        "<html><head><title>x</title></head><body>"
        + ("hello " * 20)
        + "</body></html>"
    )
    monkeypatch.setattr(generator.generation_runtime, "completion", lambda **kwargs: _FakeResp(good_html))

    html, meta = generator.generate_html_with_meta(
        model=model,
        user_prompt=prompt,
        iteration=iteration,
        temperature=None,
        seed=None,
        disable_cache=False,
        debug_truncated_cache=True,
    )

    assert meta["cached"] is False
    assert meta.get("truncated_cache_files") == [str(cache_file)]
    # Preserve truncated cache entry for inspection (do not overwrite)


def test_clean_generation_preserves_leading_doctype():
    raw = "preface\n<!DOCTYPE html>\n<html><head><title>x</title></head><body>ok</body></html>\ntrailer"

    cleaned = generator.clean_generation(raw)

    assert cleaned.startswith("<!DOCTYPE html>")
    assert cleaned.endswith("</html>")


def test_batch_generation_skips_cache_hits(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    model = "fake-model"
    cached_prompt = "cached prompt"
    miss_prompt = "miss prompt"

    cached_file = _cache_path(tmp_path, model, cached_prompt, 0)
    cached_file.parent.mkdir(parents=True, exist_ok=True)
    cached_html = (
        "<html><head><title>cached</title></head><body>"
        + ("cached " * 30)
        + "</body></html>"
    )
    cached_file.write_text(cached_html, encoding="utf-8")
    cached_checksum = cached_file.with_suffix(cached_file.suffix + ".sha256")
    cached_checksum.write_text(sha256_hex(cached_html.encode("utf-8")) + "\n", encoding="utf-8")

    captured = {}
    generated_html = (
        "<html><head><title>fresh</title></head><body>"
        + ("fresh " * 30)
        + "</body></html>"
    )

    def _batch_completion(**kwargs):
        captured.update(kwargs)
        return [_FakeResp(generated_html)]

    def _boom(**kwargs):
        raise AssertionError("single-request generation should not be called when batch succeeds")

    monkeypatch.setattr(generator.generation_runtime, "batch_completion", _batch_completion)
    monkeypatch.setattr(generator.generation_runtime, "completion", _boom)

    results = generator.generate_html_batch_with_meta(
        model=model,
        requests=[
            {"user_prompt": cached_prompt, "iteration": 0},
            {"user_prompt": miss_prompt, "iteration": 1},
        ],
        disable_cache=False,
    )

    assert len(results) == 2
    assert results[0]["meta"]["cached"] is True
    assert results[0]["html"] == cached_html
    assert results[1]["meta"]["cached"] is False
    assert results[1]["html"] == generated_html
    assert len(captured["messages"]) == 1
    assert captured["messages"][0][1]["content"] == miss_prompt


def test_batch_generation_falls_back_to_single_on_item_error(tmp_path, monkeypatch):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    model = "fake-model"
    prompt = "make a page"
    calls = {"single": 0, "batch": 0}
    fallback_html = (
        "<html><head><title>fallback</title></head><body>"
        + ("fallback " * 30)
        + "</body></html>"
    )

    def _batch_completion(**kwargs):
        calls["batch"] += 1
        return [RuntimeError("batch item failed")]

    def _completion(**kwargs):
        calls["single"] += 1
        return _FakeResp(fallback_html)

    monkeypatch.setattr(generator.generation_runtime, "batch_completion", _batch_completion)
    monkeypatch.setattr(generator.generation_runtime, "completion", _completion)

    results = generator.generate_html_batch_with_meta(
        model=model,
        requests=[{"user_prompt": prompt, "iteration": 0}],
        disable_cache=True,
    )

    assert len(results) == 1
    assert calls == {"single": 1, "batch": 1}
    assert results[0]["meta"]["cached"] is False
    assert results[0]["html"] == fallback_html
