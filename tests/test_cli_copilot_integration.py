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
    monkeypatch.setattr(
        "a11y_llm_tests.copilot_runtime.cleanup_default_runtime_sync",
        lambda *a, **kw: None,
    )


@pytest.fixture(autouse=True)
def _isolate_test_workspace(tmp_path, monkeypatch):
    """Keep isolated-workspace copies tiny during CLI tests."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COPILOT_WORKSPACE", str(tmp_path))

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


def _write_instruction_set_fixture(root: Path) -> tuple[Path, Path]:
    instructions = root / "instructions.md"
    instructions.write_text("# Repo Instructions\nUse semantic HTML.\n")
    config = root / "instruction_sets.yaml"
    config.write_text(
        "instruction_sets:\n"
        "  - id: concise\n"
        "    name: Concise\n"
        "    url: https://example.com/instructions/concise\n"
        f"    instructions_markdown: {instructions.name}\n"
    )
    return config, instructions


def _write_skill_fixture(root: Path) -> tuple[Path, Path]:
    skill_dir = root / "skills" / "demo-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("# Demo Skill\nFollow the checklist.\n")
    config = root / "skills.yaml"
    config.write_text(
        "skills:\n"
        "  - id: demo-skill\n"
        "    name: Demo Skill\n"
        "    url: https://example.com/skills/demo-skill\n"
        f"    skill_dir: {skill_dir.relative_to(root).as_posix()}\n"
        "    turns:\n"
        "      - id: generate\n"
        "        prompt: \"{{test_case_prompt}}\"\n"
    )
    return config, skill_dir


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


class TestServeCommand:

    def test_serve_prints_urls_and_closes_server(self, tmp_path, monkeypatch):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "index.html").write_text("<html><body>report</body></html>", encoding="utf-8")

        closed = []

        class FakeServer:
            base_url = "http://127.0.0.1:8123"
            index_url = "http://127.0.0.1:8123/index.html"

            def close(self):
                closed.append(True)

        monkeypatch.setattr(cli.node_bridge, "serve_directory", lambda *a, **kw: FakeServer())

        def _stop_immediately():
            raise KeyboardInterrupt()

        monkeypatch.setattr(cli, "_wait_for_serve_interrupt", _stop_immediately)

        result = _runner.invoke(cli.app, ["serve", str(run_dir), "--port", "8123"])

        assert result.exit_code == 0, result.output + (result.stderr or "")
        assert "Serving run directory" in result.output
        assert "Base URL: http://127.0.0.1:8123/" in result.output
        assert "Report URL: http://127.0.0.1:8123/index.html" in result.output
        assert closed == [True]


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


class TestIsolatedWorkspaceCopy:
    """Minimal variant workspace routing for Copilot sessions."""

    def test_run_uses_disposable_workspace_copy(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        tc_dir = workspace / "tc"
        tc_dir.mkdir()
        _write_test_case(tc_dir)
        models = _write_models_yaml(workspace)
        dims = _write_prompt_dimensions(workspace)
        out = workspace / "out"

        preflight_calls = []
        sandbox_workdirs = []

        def _fake_preflight(*args, **kwargs):
            preflight_calls.append(kwargs)

        def _fake_generate_with_leak(model, prompt, iteration, **kwargs):
            sandbox_workdir = Path(kwargs["sandbox_workdir"])
            sandbox_workdirs.append(sandbox_workdir)
            workspace_copy_root = sandbox_workdir.parents[5]
            (workspace_copy_root / "index.html").write_text("leaked", encoding="utf-8")
            html = "<html><head><title>T</title></head><body><p>ok</p></body></html>"
            meta = {
                "latency_s": 0.01,
                "prompt_hash": "abc123",
                "cached": False,
                "generation_mode": "copilot_agent",
            }
            transcript = {"events": [{"type": "assistant.message", "data": {"content": html}}]}
            return html, meta, transcript

        monkeypatch.chdir(workspace)
        monkeypatch.setenv("COPILOT_WORKSPACE", str(workspace))
        monkeypatch.setattr(
            "a11y_llm_tests.copilot_runtime.preflight_default_runtime_sync",
            _fake_preflight,
        )
        monkeypatch.setattr(
            generator, "generate_html_with_agent_meta",
            _fake_generate_with_leak,
        )
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/docker" if cmd == "docker" else None)
        monkeypatch.setattr(generator, "configure_runtime", lambda *a, **kw: None)

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

        run_dir = next(d for d in out.iterdir() if d.is_dir() and not d.is_symlink())
        workspace_root = run_dir / ".copilot_workspaces" / "control"

        assert preflight_calls
        assert preflight_calls[0]["workspace_dir"] == str(workspace_root)
        assert preflight_calls[0]["container_identity_dir"] == str(workspace_root)
        assert preflight_calls[0]["reset"] is True

        assert sandbox_workdirs
        assert str(sandbox_workdirs[0]).startswith(str(workspace_root / "sandbox"))
        assert not (workspace / "index.html").exists()
        assert not (run_dir / ".copilot_workspaces").exists()

    def test_variants_get_minimal_workspace_views(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        tc_dir = workspace / "tc"
        tc_dir.mkdir()
        _write_test_case(tc_dir)
        models = _write_models_yaml(workspace)
        dims = _write_prompt_dimensions(workspace)
        instruction_sets, _ = _write_instruction_set_fixture(workspace)
        skills_file, _ = _write_skill_fixture(workspace)
        out = workspace / "out"

        inspected_workspaces = {}
        agent_workspaces = []
        skill_workspaces = []

        def _fake_preflight(*args, **kwargs):
            workspace_dir = Path(kwargs["workspace_dir"])
            inspected_workspaces[workspace_dir.name] = sorted(
                p.relative_to(workspace_dir).as_posix()
                for p in workspace_dir.rglob("*")
                if p.is_file()
            )

        def _fake_generate_agent(model, prompt, iteration, **kwargs):
            agent_workspaces.append(Path(kwargs["workspace_dir"]))
            html = "<html><head><title>T</title></head><body><p>ok</p></body></html>"
            meta = {
                "latency_s": 0.01,
                "prompt_hash": "abc123",
                "cached": False,
                "generation_mode": "copilot_agent",
            }
            transcript = {"events": [{"type": "assistant.message", "data": {"content": html}}]}
            return html, meta, transcript

        def _fake_generate_skill(model, prompt, iteration, **kwargs):
            skill_workspaces.append(Path(kwargs["workspace_dir"]))
            html = "<html><head><title>T</title></head><body><p>skill</p></body></html>"
            meta = {
                "latency_s": 0.01,
                "prompt_hash": "skill123",
                "cached": False,
                "generation_mode": "copilot_agent",
            }
            return ([{
                "turn_id": "generate",
                "turn_index": 0,
                "turn_name": "generate",
                "html": html,
                "meta": meta,
                "conversation": {"events": []},
                "error": None,
            }], {"events": []})

        monkeypatch.chdir(workspace)
        monkeypatch.setenv("COPILOT_WORKSPACE", str(workspace))
        monkeypatch.setattr(
            "a11y_llm_tests.copilot_runtime.preflight_default_runtime_sync",
            _fake_preflight,
        )
        monkeypatch.setattr(generator, "generate_html_with_agent_meta", _fake_generate_agent)
        monkeypatch.setattr(generator, "generate_html_with_skill_multi_turn", _fake_generate_skill)
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/docker" if cmd == "docker" else None)
        monkeypatch.setattr(generator, "configure_runtime", lambda *a, **kw: None)

        result = _runner.invoke(cli.app, [
            "run",
            "--models-file", str(models),
            "--prompt-dimensions-file", str(dims),
            "--test-cases-dir", str(tc_dir),
            "--instruction-sets-file", str(instruction_sets),
            "--skills-file", str(skills_file),
            "--out", str(out),
            "--samples", "1",
            "--disable-cache",
        ])
        assert result.exit_code == 0, result.output + (result.stderr or "")
        run_dir = next(d for d in out.iterdir() if d.is_dir() and not d.is_symlink())

        assert inspected_workspaces["control"] == []
        assert inspected_workspaces["concise"] == [".github/copilot-instructions.md"]
        assert inspected_workspaces["demo-skill"] == ["skills/demo-skill/SKILL.md"]

        data = json.loads((run_dir / "results.json").read_text())
        variants_by_id = {v["id"]: v for v in data["meta"]["prompt_variants"]}
        assert variants_by_id["concise"]["url"] == "https://example.com/instructions/concise"
        assert variants_by_id["demo-skill"]["url"] == "https://example.com/skills/demo-skill"

        assert agent_workspaces
        assert {p.name for p in agent_workspaces} >= {"control", "concise"}
        assert {p.name for p in skill_workspaces} == {"demo-skill"}

    def test_run_cleans_up_all_variant_sandboxes(self, tmp_path, monkeypatch):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        tc_dir = workspace / "tc"
        tc_dir.mkdir()
        _write_test_case(tc_dir)
        models = _write_models_yaml(workspace)
        dims = _write_prompt_dimensions(workspace)
        instruction_sets, _ = _write_instruction_set_fixture(workspace)
        skills_file, _ = _write_skill_fixture(workspace)
        out = workspace / "out"

        cleaned_workspaces = []

        def _fake_cleanup(*args, **kwargs):
            cleaned_workspaces.append(Path(kwargs["workspace_dir"]).name)

        monkeypatch.chdir(workspace)
        monkeypatch.setenv("COPILOT_WORKSPACE", str(workspace))
        monkeypatch.setattr(
            "a11y_llm_tests.copilot_runtime.cleanup_default_runtime_sync",
            _fake_cleanup,
        )
        monkeypatch.setattr(generator, "generate_html_with_agent_meta", _fake_generate_html_with_agent_meta)
        monkeypatch.setattr(generator, "generate_html_with_skill_multi_turn", lambda *a, **kw: ([{
            "turn_id": "generate",
            "turn_index": 0,
            "turn_name": "generate",
            "html": "<html><body>skill</body></html>",
            "meta": {
                "latency_s": 0.01,
                "prompt_hash": "skill123",
                "cached": False,
                "generation_mode": "copilot_agent",
            },
            "conversation": {"events": []},
            "error": None,
        }], {"events": []}))
        monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/docker" if cmd == "docker" else None)
        monkeypatch.setattr(generator, "configure_runtime", lambda *a, **kw: None)

        result = _runner.invoke(cli.app, [
            "run",
            "--models-file", str(models),
            "--prompt-dimensions-file", str(dims),
            "--test-cases-dir", str(tc_dir),
            "--instruction-sets-file", str(instruction_sets),
            "--skills-file", str(skills_file),
            "--out", str(out),
            "--samples", "1",
            "--disable-cache",
        ])
        assert result.exit_code == 0, result.output + (result.stderr or "")
        assert sorted(cleaned_workspaces) == ["concise", "control", "demo-skill"]


def test_report_command_can_exclude_generated_html_samples(tmp_path, monkeypatch):
    run_dir = tmp_path / "runs" / "2026-05-06_18-00-00"
    run_dir.mkdir(parents=True)
    (run_dir / "results.json").write_text("{}", encoding="utf-8")

    models_file = tmp_path / "models.yaml"
    models_file.write_text("models: []\n", encoding="utf-8")

    captured = {}

    def fake_render_report(run_json_path, out_html, models_cfg, **kwargs):
        captured["run_json_path"] = run_json_path
        captured["out_html"] = out_html
        captured["models_cfg"] = models_cfg
        captured.update(kwargs)

    monkeypatch.setattr(cli, "load_models_config", lambda _path: ({"models": []}, None))
    import a11y_llm_tests.report as report_module
    monkeypatch.setattr(report_module, "render_report", fake_render_report)

    result = _runner.invoke(
        cli.app,
        [
            "report",
            str(run_dir),
            "--models-file",
            str(models_file),
            "--exclude-generated-html-samples",
        ],
    )

    assert result.exit_code == 0, result.output + (result.stderr or "")
    assert captured["run_json_path"] == run_dir / "results.json"
    assert captured["out_html"] == run_dir / "index.html"
    assert captured["include_generated_html_samples"] is False
