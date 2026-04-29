"""Integration tests for the CLI ``run`` command with the Copilot SDK runtime.

These tests monkeypatch the generation entry points so no Docker container
or Copilot CLI is needed. They exercise the CLI's wiring — task routing,
results.json schema, concurrency flag handling, deprecation shims, and the
early Docker check.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import typer.testing

from a11y_llm_tests import cli, generator

_runner = typer.testing.CliRunner()

# ---------------------------------------------------------------------------
# Helpers: minimal test-case fixture + models config on disk
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _stub_preflight(monkeypatch):
    """Prevent every test from hitting Docker compose / container auth."""
    monkeypatch.setattr(
        "a11y_llm_tests.copilot_runtime.preflight_default_runtime_sync",
        lambda *a, **kw: None,
    )

# ---------------------------------------------------------------------------
# Helpers: minimal test-case fixture + models config on disk
# ---------------------------------------------------------------------------

def _write_test_case(root: Path, name: str = "tiny-form") -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "prompt.yaml").write_text(
        "name: Tiny Form\n"
        "base_prompt: |\n"
        "  Build a tiny form.\n"
    )
    (d / "test.js").write_text("module.exports = async () => ({ assertions: [] });\n")
    return d


def _write_models_yaml(root: Path, model: str = "test-model") -> Path:
    f = root / "models.yaml"
    f.write_text(
        f"models:\n"
        f"  - name: {model}\n"
        f"    display_name: Test Model\n"
    )
    return f


def _write_prompt_dimensions(root: Path) -> Path:
    f = root / "prompt_dimensions.yaml"
    f.write_text("dimensions: {}\n")
    return f


def _fake_generate_html_with_agent_meta(
    model, prompt, iteration, **kwargs,
):
    """Return a minimal (html, meta, transcript) triple."""
    html = "<html><head><title>T</title></head><body><p>ok</p></body></html>"
    meta = {
        "latency_s": 0.01,
        "prompt_hash": "abc123",
        "cached": False,
        "generation_mode": "copilot_agent",
    }
    transcript = {"events": [{"type": "assistant.message", "data": {"content": html}}]}
    return html, meta, transcript


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunBasic:
    """``run`` → results.json with expected fields."""

    def test_basic_run_produces_results_json(self, tmp_path, monkeypatch):
        tc_dir = tmp_path / "tc"
        tc_dir.mkdir()
        _write_test_case(tc_dir)
        models = _write_models_yaml(tmp_path)
        dims = _write_prompt_dimensions(tmp_path)

        monkeypatch.setattr(
            generator, "generate_html_with_agent_meta",
            _fake_generate_html_with_agent_meta,
        )
        # Stub Docker check
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/docker" if cmd == "docker" else None)
        # Stub configure_runtime (no real log dir)
        monkeypatch.setattr(generator, "configure_runtime", lambda *a, **kw: None)

        out = tmp_path / "out"
        result = _runner.invoke(cli.app, [
            "run",
            "--models-file", str(models),
            "--prompt-dimensions-file", str(dims),
            "--test-cases-dir", str(tc_dir),
            "--out", str(out),
            "--samples", "1",
            "--disable-cache",
        ])
        assert result.exit_code == 0, result.output + (result.stderr or "")

        # Find the run directory
        run_dirs = [d for d in out.iterdir() if d.is_dir() and not d.is_symlink()]
        assert len(run_dirs) == 1
        run_dir = run_dirs[0]

        results_file = run_dir / "results.json"
        assert results_file.exists()
        data = json.loads(results_file.read_text())

        # Top-level keys
        assert "run_id" in data
        assert "models" in data
        assert "results" in data
        assert "meta" in data

        # Meta fields
        assert data["meta"]["status"] == "GENERATED_ONLY"
        assert data["meta"]["runtime"]["engine"] == "copilot_sdk"
        assert data["meta"]["sampling"]["samples_per_case"] == 1

        # At least one result record
        assert len(data["results"]) >= 1
        rec = data["results"][0]
        assert rec["model_name"] == "test-model"
        assert rec["result"] == "PENDING"
        assert rec["prompt_variant_id"] == "control"
        assert rec["generation"]["generation_mode"] == "copilot_agent"

    def test_html_and_agent_json_written(self, tmp_path, monkeypatch):
        tc_dir = tmp_path / "tc"
        tc_dir.mkdir()
        _write_test_case(tc_dir)
        models = _write_models_yaml(tmp_path)
        dims = _write_prompt_dimensions(tmp_path)

        monkeypatch.setattr(
            generator, "generate_html_with_agent_meta",
            _fake_generate_html_with_agent_meta,
        )
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/docker" if cmd == "docker" else None)
        monkeypatch.setattr(generator, "configure_runtime", lambda *a, **kw: None)

        out = tmp_path / "out"
        result = _runner.invoke(cli.app, [
            "run",
            "--models-file", str(models),
            "--prompt-dimensions-file", str(dims),
            "--test-cases-dir", str(tc_dir),
            "--out", str(out),
            "--samples", "1",
            "--disable-cache",
        ])
        assert result.exit_code == 0, result.output + (result.stderr or "")
        run_dir = next(out.iterdir())

        # raw HTML written
        html_files = list((run_dir / "raw").rglob("*.html"))
        assert len(html_files) >= 1

        # .agent.json sidecar written
        agent_files = list((run_dir / "raw").rglob("*.agent.json"))
        assert len(agent_files) >= 1
        transcript = json.loads(agent_files[0].read_text())
        assert "events" in transcript


class TestConcurrency:
    """Concurrency flag wiring."""

    def test_concurrency_flag(self, tmp_path, monkeypatch):
        tc_dir = tmp_path / "tc"
        tc_dir.mkdir()
        _write_test_case(tc_dir)
        models = _write_models_yaml(tmp_path)
        dims = _write_prompt_dimensions(tmp_path)

        monkeypatch.setattr(
            generator, "generate_html_with_agent_meta",
            _fake_generate_html_with_agent_meta,
        )
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/docker" if cmd == "docker" else None)
        monkeypatch.setattr(generator, "configure_runtime", lambda *a, **kw: None)

        out = tmp_path / "out"
        result = _runner.invoke(cli.app, [
            "run",
            "--models-file", str(models),
            "--prompt-dimensions-file", str(dims),
            "--test-cases-dir", str(tc_dir),
            "--out", str(out),
            "--concurrency", "2",
            "--disable-cache",
        ])
        assert result.exit_code == 0, result.output + (result.stderr or "")
        run_dir = next(out.iterdir())
        data = json.loads((run_dir / "results.json").read_text())
        assert data["meta"]["sampling"]["concurrency_generation"] == 2

    def test_processes_deprecated_maps_to_concurrency(self, tmp_path, monkeypatch):
        tc_dir = tmp_path / "tc"
        tc_dir.mkdir()
        _write_test_case(tc_dir)
        models = _write_models_yaml(tmp_path)
        dims = _write_prompt_dimensions(tmp_path)

        monkeypatch.setattr(
            generator, "generate_html_with_agent_meta",
            _fake_generate_html_with_agent_meta,
        )
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/docker" if cmd == "docker" else None)
        monkeypatch.setattr(generator, "configure_runtime", lambda *a, **kw: None)

        out = tmp_path / "out"
        result = _runner.invoke(cli.app, [
            "run",
            "--models-file", str(models),
            "--prompt-dimensions-file", str(dims),
            "--test-cases-dir", str(tc_dir),
            "--out", str(out),
            "--processes", "3",
            "--disable-cache",
        ])
        assert result.exit_code == 0, result.output + (result.stderr or "")
        # Deprecation warning emitted
        assert "deprecated" in (result.stderr or "").lower() or "deprecated" in result.output.lower()
        run_dir = next(out.iterdir())
        data = json.loads((run_dir / "results.json").read_text())
        assert data["meta"]["sampling"]["concurrency_generation"] == 3


class TestDockerCheck:
    """Early Docker fail-fast."""

    def test_missing_docker_exits_with_error(self, tmp_path, monkeypatch):
        tc_dir = tmp_path / "tc"
        tc_dir.mkdir()
        _write_test_case(tc_dir)
        models = _write_models_yaml(tmp_path)
        dims = _write_prompt_dimensions(tmp_path)

        # shutil.which returns None for everything → Docker not found
        monkeypatch.setattr("shutil.which", lambda cmd: None)

        out = tmp_path / "out"
        result = _runner.invoke(cli.app, [
            "run",
            "--models-file", str(models),
            "--prompt-dimensions-file", str(dims),
            "--test-cases-dir", str(tc_dir),
            "--out", str(out),
        ])
        assert result.exit_code == 1
        assert "docker" in (result.stderr or "").lower() or "docker" in result.output.lower()


class TestVariantRouting:
    """Control vs instruction-set variant routing."""

    def test_control_variant_written_to_raw(self, tmp_path, monkeypatch):
        tc_dir = tmp_path / "tc"
        tc_dir.mkdir()
        _write_test_case(tc_dir)
        models = _write_models_yaml(tmp_path)
        dims = _write_prompt_dimensions(tmp_path)

        monkeypatch.setattr(
            generator, "generate_html_with_agent_meta",
            _fake_generate_html_with_agent_meta,
        )
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/docker" if cmd == "docker" else None)
        monkeypatch.setattr(generator, "configure_runtime", lambda *a, **kw: None)

        out = tmp_path / "out"
        result = _runner.invoke(cli.app, [
            "run",
            "--models-file", str(models),
            "--prompt-dimensions-file", str(dims),
            "--test-cases-dir", str(tc_dir),
            "--out", str(out),
            "--disable-cache",
        ])
        assert result.exit_code == 0, result.output + (result.stderr or "")
        run_dir = next(out.iterdir())

        # Control HTML under raw/<prompt_case_id>/
        raw_htmls = list((run_dir / "raw").rglob("*.html"))
        assert len(raw_htmls) >= 1

        data = json.loads((run_dir / "results.json").read_text())
        # All results should be control variant
        for rec in data["results"]:
            assert rec["prompt_variant_id"] == "control"
            assert rec["prompt_variant_kind"] in (None, "control")
