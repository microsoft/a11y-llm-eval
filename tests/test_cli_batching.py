from pathlib import Path
import json

from typer.testing import CliRunner

from a11y_llm_tests import generator
from a11y_llm_tests.cli import app


def _write_basic_test_case(base_dir, name: str):
    tc_dir = base_dir / "test_cases" / name
    tc_dir.mkdir(parents=True)
    (tc_dir / "prompt.yaml").write_text("base_prompt: |\n  Generate a page\n", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")


def test_cli_uses_batch_generation_by_default(monkeypatch, tmp_path):
    captured = {"calls": 0, "requests": []}

    def fake_generate_html_batch_with_meta(model, requests, temperature=None, seed=None, disable_cache=False, **kwargs):
        captured["calls"] += 1
        captured["requests"].append([req["user_prompt"] for req in requests])
        return [
            {
                "html": f"<html><body><h1>{model}</h1><p>{req['user_prompt']}</p></body></html>",
                "meta": {
                    "cached": False,
                    "latency_s": 0.01,
                    "prompt_hash": f"hash-{idx}",
                    "tokens_in": 1,
                    "tokens_out": 2,
                    "total_tokens": 3,
                    "cost_usd": 0.0001,
                    "seed": seed,
                    "temperature": temperature,
                },
            }
            for idx, req in enumerate(requests)
        ]

    def fake_generate_html_with_meta(*args, **kwargs):
        raise AssertionError("single-request generation should not be used for this batch-enabled group")

    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_batch_with_meta", fake_generate_html_batch_with_meta)
    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", fake_generate_html_with_meta)

    _write_basic_test_case(tmp_path, "case-one")
    _write_basic_test_case(tmp_path, "case-two")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text("models:\n  - name: openai/test-model\n", encoding="utf-8")
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
    assert captured["calls"] == 1
    assert len(captured["requests"][0]) == 2

    latest = sorted((tmp_path / "runs").iterdir())[-1]
    data = json.loads((latest / "results.json").read_text(encoding="utf-8"))
    assert len(data["results"]) == 2
    assert data["meta"]["runtime"]["engine"] == "inspect_ai"
    assert (latest / "inspect_logs").exists()


def test_cli_writes_runtime_log_artifact(monkeypatch, tmp_path):
    def fake_generate_html_with_meta(model, prompt, iteration, temperature=None, seed=None, disable_cache=False, runtime_log_dir=None, **kwargs):
        if runtime_log_dir:
            log_path = tmp_path / "runs-log-observed.txt"
            log_path.write_text(runtime_log_dir, encoding="utf-8")
            artifact = Path(runtime_log_dir) / "generation-test.jsonl"
            artifact.write_text('{"status":"ok"}\n', encoding="utf-8")
        return "<html><body>ok</body></html>", {
            "cached": False,
            "latency_s": 0.01,
            "prompt_hash": "hash-1",
        }

    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", fake_generate_html_with_meta)

    _write_basic_test_case(tmp_path, "case-one")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text("models:\n  - name: openai/test-model\n", encoding="utf-8")
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
    latest = sorted((tmp_path / "runs").iterdir())[-1]
    assert (latest / "inspect_logs" / "generation-test.jsonl").exists()


def test_cli_provider_batch_opt_out_uses_single_generation(monkeypatch, tmp_path):
    captured = {"single_calls": 0}

    def fake_generate_html_batch_with_meta(*args, **kwargs):
        raise AssertionError("batch generation should be disabled for this provider")

    def fake_generate_html_with_meta(model, prompt, iteration, temperature=None, seed=None, disable_cache=False, provider_config=None, **kwargs):
        captured["single_calls"] += 1
        return "<html><body><h1>single</h1></body></html>", {
            "cached": False,
            "latency_s": 0.01,
            "prompt_hash": f"hash-{captured['single_calls']}",
            "tokens_in": 1,
            "tokens_out": 2,
            "total_tokens": 3,
            "cost_usd": 0.0001,
            "seed": seed,
            "temperature": temperature,
        }

    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_batch_with_meta", fake_generate_html_batch_with_meta)
    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", fake_generate_html_with_meta)

    _write_basic_test_case(tmp_path, "case-one")
    _write_basic_test_case(tmp_path, "case-two")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text(
        """
providers:
  openai:
    batch:
      enabled: false
models:
  - name: openai/test-model
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
    assert captured["single_calls"] == 2


def test_cli_instruction_set_variants_bypass_batch_generation(monkeypatch, tmp_path):
    captured = {"batch_calls": 0, "agent_calls": 0, "single_calls": 0}

    def fake_generate_html_batch_with_meta(model, requests, temperature=None, seed=None, disable_cache=False, **kwargs):
        captured["batch_calls"] += 1
        return [
            {
                "html": f"<html><body><h1>{model}</h1><p>{req['user_prompt']}</p></body></html>",
                "meta": {
                    "cached": False,
                    "latency_s": 0.01,
                    "prompt_hash": f"batch-hash-{idx}",
                },
            }
            for idx, req in enumerate(requests)
        ]

    def fake_generate_html_with_meta(model, prompt, iteration, temperature=None, seed=None, disable_cache=False, **kwargs):
        del iteration, temperature, seed, disable_cache, kwargs
        captured["single_calls"] += 1
        return f"<html><body><h1>{model}</h1><p>{prompt}</p></body></html>", {
            "cached": False,
            "latency_s": 0.01,
            "prompt_hash": f"single-hash-{captured['single_calls']}",
        }

    def fake_generate_html_with_agent_meta(
        model,
        prompt,
        iteration,
        temperature=None,
        seed=None,
        disable_cache=False,
        model_display_name=None,
        provider_config=None,
        runtime_log_dir=None,
        agent_config=None,
    ):
        del iteration, temperature, seed, disable_cache, model_display_name, provider_config, runtime_log_dir
        captured["agent_calls"] += 1
        return "<html><body><h1>agent</h1></body></html>", {
            "cached": False,
            "latency_s": 0.2,
            "prompt_hash": f"agent-hash-{captured['agent_calls']}",
            "generation_mode": "inspect_react_agent",
            "agent_sandbox": generator.format_agent_sandbox((agent_config or {}).get("sandbox")),
            "agent_limits": (agent_config or {}).get("limits") or {},
            "agent_limit_error": None,
        }, {
            "messages": [{"role": "assistant", "content": prompt}],
            "events": [],
        }

    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_batch_with_meta", fake_generate_html_batch_with_meta)
    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", fake_generate_html_with_meta)
    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_agent_meta", fake_generate_html_with_agent_meta)

    _write_basic_test_case(tmp_path, "case-one")
    _write_basic_test_case(tmp_path, "case-two")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text("models:\n  - name: openai/test-model\n", encoding="utf-8")
    (config_dir / "prompt_dimensions.yaml").write_text("dimensions: {}\n", encoding="utf-8")
    instr_dir = config_dir / "instructions"
    instr_dir.mkdir()
    (instr_dir / "variant.md").write_text("Refine for accessibility\n", encoding="utf-8")
    (config_dir / "instruction_sets.yaml").write_text(
        """instruction_sets:
  - id: variant
    name: Variant
    system_prompt_append_markdown: instructions/variant.md
    agent:
            sandbox:
                - docker
                - test-sandbox
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, [
        "run",
        "--models-file", str(config_dir / "models.yaml"),
        "--prompt-dimensions-file", str(config_dir / "prompt_dimensions.yaml"),
        "--out", str(tmp_path / "runs"),
        "--test-cases-dir", str(tmp_path / "test_cases"),
        "--samples", "1",
        "--instruction-sets-file", str(config_dir / "instruction_sets.yaml"),
        "--processes", "1",
    ])

    assert result.exit_code == 0, result.output
    assert captured["batch_calls"] == 1
    assert captured["single_calls"] == 0
    assert captured["agent_calls"] == 2


def test_cli_accepts_repo_relative_instruction_sets_path(monkeypatch, tmp_path):
    captured = {"agent_calls": 0}

    def fake_generate_html_with_meta(model, prompt, iteration, temperature=None, seed=None, disable_cache=False, **kwargs):
        del model, prompt, iteration, temperature, seed, disable_cache, kwargs
        return "<html><body><h1>control</h1></body></html>", {
            "cached": False,
            "latency_s": 0.01,
            "prompt_hash": "control-hash",
        }

    def fake_generate_html_with_agent_meta(
        model,
        prompt,
        iteration,
        temperature=None,
        seed=None,
        disable_cache=False,
        model_display_name=None,
        provider_config=None,
        runtime_log_dir=None,
        agent_config=None,
    ):
        del model, prompt, iteration, temperature, seed, disable_cache, model_display_name, provider_config, runtime_log_dir
        captured["agent_calls"] += 1
        return "<html><body><h1>agent</h1></body></html>", {
            "cached": False,
            "latency_s": 0.02,
            "prompt_hash": "agent-hash",
            "generation_mode": "inspect_react_agent",
            "agent_sandbox": generator.format_agent_sandbox((agent_config or {}).get("sandbox")),
            "agent_limits": (agent_config or {}).get("limits") or {},
            "agent_limit_error": None,
            "agent_eval_path": None,
        }, {
            "messages": [{"role": "assistant", "content": "ok"}],
            "events": [],
        }

    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", fake_generate_html_with_meta)
    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_agent_meta", fake_generate_html_with_agent_meta)
    monkeypatch.chdir(tmp_path)

    _write_basic_test_case(tmp_path, "case-one")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text("models:\n  - name: openai/test-model\n", encoding="utf-8")
    (config_dir / "prompt_dimensions.yaml").write_text("dimensions: {}\n", encoding="utf-8")
    instr_dir = config_dir / "instructions"
    instr_dir.mkdir()
    (instr_dir / "variant.md").write_text("Refine for accessibility\n", encoding="utf-8")
    (config_dir / "instruction_sets.yaml").write_text(
        """instruction_sets:
  - id: variant
    name: Variant
    system_prompt_append_markdown: instructions/variant.md
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(app, [
        "run",
        "--models-file", "config/models.yaml",
        "--prompt-dimensions-file", "config/prompt_dimensions.yaml",
        "--out", "runs",
        "--test-cases-dir", "test_cases",
        "--samples", "1",
        "--instruction-sets-file", "config/instruction_sets.yaml",
        "--processes", "1",
    ])

    assert result.exit_code == 0, result.output
    assert captured["agent_calls"] == 1