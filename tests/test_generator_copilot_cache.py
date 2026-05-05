"""Tests for the generator cache layer: hit/miss, invalidation, back-compat
meta keys, and ``extract_html_from_transcript``.
"""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from a11y_llm_tests import generator
from a11y_llm_tests.generator import (
    _cache_artifacts,
    _invalidate_cache_entry,
    _load_cached_agent_generation,
    _meta_path,
    _agent_transcript_cache_path,
    _agent_session_cache_path,
    extract_html_from_transcript,
)
from a11y_llm_tests.utils import write_sha256_sidecar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HTML = "<html><head><title>T</title></head><body><p>hi</p></body></html>"
_TRANSCRIPT = {"events": [{"type": "assistant.message", "data": {"content": _HTML}}]}


def _fake_agent_result(html: str = _HTML):
    from a11y_llm_tests.copilot_runtime import AgentGenerationResult

    return AgentGenerationResult(
        html=html,
        transcript={"format": "copilot_agent_conversation/v1", "events": [], "output_source": "message"},
        usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        elapsed_s=0.5,
        sandbox="docker:test",
        limit_error=None,
        session_log_path=None,
    )


def _seed_cache(cache_file: Path, *, html: str = _HTML, meta_extra: dict | None = None,
                transcript: dict | None = None, session_log: str | None = None,
                include_browser_smoke: bool = True):
    """Write a full, valid cache entry."""
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    html_bytes = html.encode("utf-8")
    cache_file.write_bytes(html_bytes)
    write_sha256_sidecar(cache_file, html_bytes)

    meta = {"generation_mode": "copilot_agent", **(meta_extra or {})}
    if include_browser_smoke:
        meta.setdefault(
            "browser_smoke",
            {
                "rendered": True,
                "reason": None,
                "page_errors": [],
                "request_failures": [],
                "dom_state": {},
            },
        )
    _meta_path(cache_file).write_text(json.dumps(meta), encoding="utf-8")

    t = transcript if transcript is not None else _TRANSCRIPT
    _agent_transcript_cache_path(cache_file).write_text(json.dumps(t), encoding="utf-8")

    if session_log:
        _agent_session_cache_path(cache_file).write_text(session_log, encoding="utf-8")


@pytest.fixture(autouse=True)
def _reset_prompts():
    generator.configure_prompts(None, None)
    yield
    generator.configure_prompts(None, None)


# ---------------------------------------------------------------------------
# extract_html_from_transcript
# ---------------------------------------------------------------------------

class TestExtractHtmlFromTranscript:

    def test_extracts_last_html_from_events(self):
        transcript = {
            "events": [
                {"type": "assistant.message", "data": {"content": "thinking..."}},
                {"type": "assistant.message", "data": {"content": "<html><body>first</body></html>"}},
                {"type": "assistant.message", "data": {"content": "<html><body>second</body></html>"}},
            ]
        }
        assert "second" in extract_html_from_transcript(transcript, "fallback")

    def test_falls_back_to_turns(self):
        transcript = {
            "turns": [
                {
                    "events": [
                        {"type": "assistant.message", "data": {"content": "hello from turn"}}
                    ]
                }
            ]
        }
        result = extract_html_from_transcript(transcript, "fallback")
        assert result == "hello from turn"

    def test_returns_fallback_when_empty(self):
        assert extract_html_from_transcript({}, "fb") == "fb"
        assert extract_html_from_transcript({"events": []}, "fb") == "fb"
        assert extract_html_from_transcript("not-a-dict", "fb") == "fb"


# ---------------------------------------------------------------------------
# Cache hit / miss
# ---------------------------------------------------------------------------

class TestCacheHitMiss:

    def test_valid_cache_returns_html_and_meta(self, tmp_path):
        cache_file = tmp_path / "model_abc123_i0_copilot_agent.html"
        _seed_cache(cache_file)

        html, meta, transcript, reason = _load_cached_agent_generation(
            cache_file=cache_file,
            meta_file=_meta_path(cache_file),
            prompt_hash_value="abc123",
            temperature=0.7,
            seed=42,
            model_display_name="Test",
            base_output_format_instructions="fmt",
            custom_instructions=None,
            effective_output_format_instructions="eff",
        )
        assert html is not None
        assert reason is None
        assert meta["cached"] is True
        assert meta["generation_mode"] == "copilot_agent"
        assert transcript is not None

    def test_missing_file_returns_none(self, tmp_path):
        cache_file = tmp_path / "does_not_exist.html"
        html, meta, transcript, reason = _load_cached_agent_generation(
            cache_file=cache_file,
            meta_file=_meta_path(cache_file),
            prompt_hash_value="x",
            temperature=None,
            seed=None,
            model_display_name=None,
            base_output_format_instructions="",
            custom_instructions=None,
            effective_output_format_instructions="",
        )
        assert html is None
        assert reason == "missing"

    def test_checksum_mismatch_invalidates(self, tmp_path):
        cache_file = tmp_path / "model_abc_i0_copilot_agent.html"
        _seed_cache(cache_file)
        # Corrupt the sha256 sidecar
        sha_path = cache_file.with_suffix(cache_file.suffix + ".sha256")
        sha_path.write_text("0000bad", encoding="utf-8")

        html, _, _, reason = _load_cached_agent_generation(
            cache_file=cache_file,
            meta_file=_meta_path(cache_file),
            prompt_hash_value="abc",
            temperature=None,
            seed=None,
            model_display_name=None,
            base_output_format_instructions="",
            custom_instructions=None,
            effective_output_format_instructions="",
        )
        assert html is None
        assert reason == "checksum-mismatch"

    def test_missing_transcript_invalidates(self, tmp_path):
        cache_file = tmp_path / "model_abc_i0_copilot_agent.html"
        _seed_cache(cache_file)
        # Remove the transcript
        _agent_transcript_cache_path(cache_file).unlink()

        html, _, _, reason = _load_cached_agent_generation(
            cache_file=cache_file,
            meta_file=_meta_path(cache_file),
            prompt_hash_value="abc",
            temperature=None,
            seed=None,
            model_display_name=None,
            base_output_format_instructions="",
            custom_instructions=None,
            effective_output_format_instructions="",
        )
        assert html is None
        assert reason == "missing_or_invalid_agent_transcript"

    def test_agent_limit_error_in_cache_invalidates(self, tmp_path):
        cache_file = tmp_path / "model_abc_i0_copilot_agent.html"
        _seed_cache(cache_file, meta_extra={"agent_limit_error": "token_budget_exceeded"})

        html, _, _, reason = _load_cached_agent_generation(
            cache_file=cache_file,
            meta_file=_meta_path(cache_file),
            prompt_hash_value="abc",
            temperature=None,
            seed=None,
            model_display_name=None,
            base_output_format_instructions="",
            custom_instructions=None,
            effective_output_format_instructions="",
        )
        assert html is None
        assert reason == "agent_limit_error_in_cache"

    def test_missing_browser_smoke_is_backfilled_during_cache_validation(self, tmp_path, monkeypatch):
        cache_file = tmp_path / "model_abc_i0_copilot_agent.html"
        _seed_cache(cache_file, meta_extra={"generation_mode": "copilot_agent"}, include_browser_smoke=False)

        monkeypatch.setattr(
            generator.node_bridge,
            "run_browser_smoke_eval",
            lambda html, html_dir=None: {
                "rendered": False,
                "reason": "artifact_failed_to_render",
                "page_errors": ["boom"],
                "request_failures": [],
                "dom_state": {"rootPresent": True},
            },
        )

        html, meta, _, reason = _load_cached_agent_generation(
            cache_file=cache_file,
            meta_file=_meta_path(cache_file),
            prompt_hash_value="abc",
            temperature=None,
            seed=None,
            model_display_name=None,
            base_output_format_instructions="",
            custom_instructions=None,
            effective_output_format_instructions="",
        )
        assert html is None
        assert meta is None
        assert reason == "browser_smoke_render_failed"
        persisted = json.loads(_meta_path(cache_file).read_text(encoding="utf-8"))
        assert persisted["browser_smoke"]["reason"] == "artifact_failed_to_render"

    def test_existing_browser_smoke_render_failed_invalidates(self, tmp_path):
        cache_file = tmp_path / "model_abc_i0_copilot_agent.html"
        _seed_cache(
            cache_file,
            meta_extra={
                "browser_smoke": {
                    "rendered": False,
                    "reason": "artifact_failed_to_render",
                    "page_errors": ["boom"],
                    "request_failures": [],
                    "dom_state": {"rootPresent": True},
                }
            },
        )

        html, meta, _, reason = _load_cached_agent_generation(
            cache_file=cache_file,
            meta_file=_meta_path(cache_file),
            prompt_hash_value="abc",
            temperature=None,
            seed=None,
            model_display_name=None,
            base_output_format_instructions="",
            custom_instructions=None,
            effective_output_format_instructions="",
        )
        assert html is None
        assert meta is None
        assert reason == "browser_smoke_render_failed"


# ---------------------------------------------------------------------------
# Back-compat meta keys
# ---------------------------------------------------------------------------

class TestBackCompatMetaKeys:

    def test_legacy_system_prompt_aliases(self, tmp_path):
        cache_file = tmp_path / "model_abc_i0_copilot_agent.html"
        _seed_cache(cache_file, meta_extra={
            "system_prompt": "old-format-instructions",
            "effective_system_prompt": "old-effective-instructions",
        })

        # When base_output_format_instructions/effective_output_format_instructions
        # are passed as None, _build_generation_meta sets the keys to None and the
        # legacy aliases can fill them in.
        html, meta, _, reason = _load_cached_agent_generation(
            cache_file=cache_file,
            meta_file=_meta_path(cache_file),
            prompt_hash_value="abc",
            temperature=None,
            seed=None,
            model_display_name=None,
            base_output_format_instructions=None,
            custom_instructions=None,
            effective_output_format_instructions=None,
        )
        assert html is not None
        assert reason is None
        # Legacy keys mapped to new names
        assert meta["output_format_instructions"] == "old-format-instructions"
        assert meta["effective_output_format_instructions"] == "old-effective-instructions"

    def test_new_keys_take_precedence_over_legacy(self, tmp_path):
        cache_file = tmp_path / "model_abc_i0_copilot_agent.html"
        _seed_cache(cache_file, meta_extra={
            "output_format_instructions": "new-fmt",
            "system_prompt": "old-fmt",
            "effective_output_format_instructions": "new-eff",
            "effective_system_prompt": "old-eff",
        })

        _, meta, _, _ = _load_cached_agent_generation(
            cache_file=cache_file,
            meta_file=_meta_path(cache_file),
            prompt_hash_value="abc",
            temperature=None,
            seed=None,
            model_display_name=None,
            base_output_format_instructions="",
            custom_instructions=None,
            effective_output_format_instructions="",
        )
        # New keys win
        assert meta["output_format_instructions"] == "new-fmt"
        assert meta["effective_output_format_instructions"] == "new-eff"


# ---------------------------------------------------------------------------
# _invalidate_cache_entry
# ---------------------------------------------------------------------------

class TestInvalidateCacheEntry:

    def test_removes_all_cache_files(self, tmp_path):
        cache_file = tmp_path / "model_abc_i0_copilot_agent.html"
        _seed_cache(cache_file, session_log='{"log": true}')

        expected_files = [
            cache_file,
            cache_file.with_suffix(cache_file.suffix + ".sha256"),
            _meta_path(cache_file),
            _agent_transcript_cache_path(cache_file),
            _agent_session_cache_path(cache_file),
        ]
        for f in expected_files:
            assert f.exists(), f"{f.name} should exist before invalidation"

        _invalidate_cache_entry(cache_file)

        for f in expected_files:
            assert not f.exists(), f"{f.name} should be removed after invalidation"

    def test_invalidate_missing_files_is_noop(self, tmp_path):
        cache_file = tmp_path / "nonexistent.html"
        # Should not raise
        _invalidate_cache_entry(cache_file)


# ---------------------------------------------------------------------------
# _cache_artifacts path computation
# ---------------------------------------------------------------------------

class TestCacheArtifacts:

    def test_deterministic_paths(self):
        generator.configure_prompts("fmt", None)
        h1, f1, m1 = _cache_artifacts("gpt-4", "hello", 0, None)
        h2, f2, m2 = _cache_artifacts("gpt-4", "hello", 0, None)
        assert h1 == h2
        assert f1 == f2

    def test_seed_changes_path(self):
        generator.configure_prompts("fmt", None)
        _, f1, _ = _cache_artifacts("m", "p", 0, None)
        _, f2, _ = _cache_artifacts("m", "p", 0, 42)
        assert f1 != f2
        assert "_s42_" in f2.name

    def test_iteration_in_filename(self):
        generator.configure_prompts("fmt", None)
        _, f, _ = _cache_artifacts("m", "p", 3, None)
        assert "_i3_" in f.name


def test_fresh_generation_records_browser_smoke(monkeypatch):
    smoke = {
        "rendered": True,
        "reason": None,
        "page_errors": [],
        "request_failures": [],
        "dom_state": {"interactiveCount": 1},
    }
    monkeypatch.setattr(generator.node_bridge, "run_browser_smoke_eval", lambda html, html_dir=None: smoke)

    with patch.object(generator, "run_agent_generation_sync", return_value=_fake_agent_result()):
        html, meta, _ = generator.generate_html_with_agent_meta(
            "test-model",
            "prompt",
            0,
            disable_cache=True,
        )

    assert html == _HTML
    assert meta["browser_smoke"] == smoke


def test_fresh_generation_with_failed_browser_smoke_is_not_cached(monkeypatch, tmp_path):
    smoke = {
        "rendered": False,
        "reason": "artifact_failed_to_render",
        "page_errors": ["boom"],
        "request_failures": [],
        "dom_state": {"rootPresent": True},
    }
    monkeypatch.setattr(generator.node_bridge, "run_browser_smoke_eval", lambda html, html_dir=None: smoke)
    cache_file = tmp_path / "test-model_prompt_i0_copilot_agent.html"
    monkeypatch.setattr(
        generator,
        "_cache_artifacts",
        lambda *args, **kwargs: ("prompt-hash", cache_file, _meta_path(cache_file)),
    )

    with patch.object(generator, "run_agent_generation_sync", return_value=_fake_agent_result()), \
         patch.object(generator, "_write_agent_generation_cache") as write_cache:
        html, meta, _ = generator.generate_html_with_agent_meta(
            "test-model",
            "prompt",
            0,
            disable_cache=False,
        )

    assert html == _HTML
    assert meta["browser_smoke"] == smoke
    write_cache.assert_not_called()
