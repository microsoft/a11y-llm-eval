import json
from pathlib import Path
from typer.testing import CliRunner
from a11y_llm_tests.cli import app

# We'll monkeypatch generator and node_bridge to avoid real API calls

class DummyResp:
    def __init__(self, content):
        self.choices = [type("c", (), {"message": type("m", (), {"content": content})()})]
        self.usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        self.response_cost = 0.001


def fake_generate_html_with_meta(model, prompt, iteration, temperature=None, seed=None, disable_cache=False):
    # Generate deterministic pass/fail pattern by seed (even seed -> pass, odd -> fail)
    status_comment = f"<!-- seed:{seed} -->" if seed is not None else ""
    html = f"<html><body><h1>Test {model}</h1>{status_comment}</body></html>"
    return html, {
        "cached": False,
        "latency_s": 0.01,
        "prompt_hash": "deadbeef",
        "tokens_in": 5,
        "tokens_out": 7,
        "total_tokens": 12,
        "cost_usd": 0.0005,
        "seed": seed,
        "temperature": temperature,
    }


def fake_run(html, test_js_path, screenshot_path):
    # Extract seed from comment to decide pass/fail
    import re
    m = re.search(r"seed:(\d+)", html)
    seed = int(m.group(1)) if m else 0
    status = "pass" if seed % 2 == 0 else "fail"
    return {
        "testFunctionResult": {
            "status": status,
            "assertions": [
                {"name": "dummy", "status": status, "message": None, "type": "R"},
            ],
            "duration_ms": 5,
        },
        "axeResult": {
            "violation_count": 0,
            "violations": [],
        },
    }


def test_cli_sampling_multi(monkeypatch, tmp_path):
    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", fake_generate_html_with_meta)
    monkeypatch.setattr("a11y_llm_tests.node_bridge.run", fake_run)

    # Create a minimal test case directory
    tc_dir = tmp_path / "test_cases" / "sample-case"
    tc_dir.mkdir(parents=True)
    (tc_dir / "prompt.yaml").write_text("base_prompt: |\n  Generate a page\n", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")

    # Provide models config
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text("""models:\n  - name: test-model\n""", encoding="utf-8")
    (config_dir / "prompt_dimensions.yaml").write_text("dimensions: {}\n", encoding="utf-8")

    runner = CliRunner()
    # Generation phase only
    gen_result = runner.invoke(app, [
        "run",
        "--models-file", str(config_dir / "models.yaml"),
        "--prompt-dimensions-file", str(config_dir / "prompt_dimensions.yaml"),
        "--out", str(tmp_path / "runs"),
        "--test-cases-dir", str(tmp_path / "test_cases"),
        "--samples", "4",
        "--k", "1,2,4",
        "--base-seed", "100",
        "--processes", "1",
    ])
    assert gen_result.exit_code == 0, gen_result.output
    runs_dir = tmp_path / "runs"
    run_subdirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    assert run_subdirs, "No run directory created"
    latest = run_subdirs[-1]
    # Ensure aggregates are empty pre-evaluation
    pre_data = json.loads((latest / "results.json").read_text(encoding="utf-8"))
    assert pre_data["aggregates"] == []
    # Evaluation phase
    eval_result = runner.invoke(app, [
        "evaluate",
        str(latest),
        "--test-cases-dir", str(tmp_path / "test_cases"),
        "--k", "1,2,4",
        "--processes", "1",
        "--no-generate-report",
        "--processes", "1",
    ])
    assert eval_result.exit_code == 0, eval_result.output
    data = json.loads((latest / "results.json").read_text(encoding="utf-8"))
    aggs = data["aggregates"]
    assert len(aggs) == 1
    agg = aggs[0]
    assert agg["n_samples"] == 4
    assert agg["n_pass"] == 2  # Seeds 100,101,102,103 -> pass,fail,pass,fail
    p1 = agg["pass_at_k"]["1"]
    p2 = agg["pass_at_k"]["2"]
    assert abs(p1 - 0.5) < 1e-6
    assert 0.82 < p2 < 0.85
    assert agg["pass_at_k"]["4"] == 1.0
    sample_indices = sorted(r["sample_index"] for r in data["results"])
    assert sample_indices == [0, 1, 2, 3]
    assert data["results"][0]["base_test_name"] == "sample-case"
    assert data["results"][0]["prompt_case_id"] == "sample-case"


def test_cli_sampling_single(monkeypatch, tmp_path):
    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", fake_generate_html_with_meta)
    monkeypatch.setattr("a11y_llm_tests.node_bridge.run", fake_run)

    tc_dir = tmp_path / "test_cases" / "single"
    tc_dir.mkdir(parents=True)
    (tc_dir / "prompt.yaml").write_text("base_prompt: |\n  Prompt\n", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "models.yaml").write_text("""models:\n  - name: m1\n""", encoding="utf-8")
    (config_dir / "prompt_dimensions.yaml").write_text("dimensions: {}\n", encoding="utf-8")

    runner = CliRunner()
    gen_result = runner.invoke(app, [
        "run",
        "--models-file", str(config_dir / "models.yaml"),
        "--prompt-dimensions-file", str(config_dir / "prompt_dimensions.yaml"),
        "--out", str(tmp_path / "runs"),
        "--test-cases-dir", str(tmp_path / "test_cases"),
        "--samples", "1",
        "--k", "1,5",
        "--base-seed", "5",
        "--processes", "1",
    ])
    assert gen_result.exit_code == 0, gen_result.output
    runs_dir = tmp_path / "runs"
    run_subdirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    latest = run_subdirs[-1]
    pre_data = json.loads((latest / "results.json").read_text(encoding="utf-8"))
    assert pre_data["aggregates"] == []
    eval_result = runner.invoke(app, [
        "evaluate",
        str(latest),
        "--test-cases-dir", str(tmp_path / "test_cases"),
        "--k", "1,5",
        "--processes", "1",
        "--no-generate-report",
        "--processes", "1",
    ])
    assert eval_result.exit_code == 0, eval_result.output
    data = json.loads((latest / "results.json").read_text(encoding="utf-8"))
    agg = data["aggregates"][0]
    assert agg["n_samples"] == 1
    assert agg["n_pass"] == 0  # Seed=5 -> fail (odd)
    assert agg["pass_at_k"]["1"] == 0.0


def test_cli_run_resolves_default_prompt_dimensions_from_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", fake_generate_html_with_meta)
    monkeypatch.chdir(tmp_path)

    tc_dir = tmp_path / "test_cases" / "sample-case"
    tc_dir.mkdir(parents=True)
    (tc_dir / "prompt.yaml").write_text("base_prompt: |\n  Generate a page\n", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "models.yaml").write_text("""models:\n  - name: m1\n""", encoding="utf-8")
    (config_dir / "prompt_dimensions.yaml").write_text("dimensions: {}\n", encoding="utf-8")

    runner = CliRunner()
    gen_result = runner.invoke(
        app,
        [
            "run",
            "--models-file", str(config_dir / "models.yaml"),
            "--out", str(tmp_path / "runs"),
            "--test-cases-dir", str(tmp_path / "test_cases"),
            "--samples", "1",
            "--processes", "1",
        ],
        catch_exceptions=False,
    )

    assert gen_result.exit_code == 0, gen_result.output


def test_bp_failure_not_affect_requirement_pass(monkeypatch, tmp_path):
    # Requirement passes, BP fails => overall should pass
    def gen_html(model, prompt, iteration, temperature=None, seed=None, disable_cache=False):
        return "<html><body><h1>Page</h1></body></html>", {
            "cached": False,
            "latency_s": 0.01,
            "prompt_hash": "hash",
            "cost_usd": 0.0001,
            "seed": 1,
            "temperature": temperature,
        }

    def run(html, test_js_path, screenshot_path):
        return {
            "testFunctionResult": {
                "status": "pass",  # legacy status (will be recomputed logic wise in runner normally)
                "assertions": [
                    {"name": "req-1", "status": "pass", "type": "R"},
                    {"name": "bp-1", "status": "fail", "type": "BP"},
                ],
                "duration_ms": 3,
            },
            "axeResult": {"violation_count": 0, "violations": []},
        }

    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", gen_html)
    monkeypatch.setattr("a11y_llm_tests.node_bridge.run", run)

    tc_dir = tmp_path / "test_cases" / "bp-case"
    tc_dir.mkdir(parents=True)
    (tc_dir / "prompt.yaml").write_text("base_prompt: |\n  Prompt\n", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "models.yaml").write_text("""models:\n  - name: modelX\n""", encoding="utf-8")
    (config_dir / "prompt_dimensions.yaml").write_text("dimensions: {}\n", encoding="utf-8")

    runner_cli = CliRunner()
    gen_result = runner_cli.invoke(app, [
        "run",
        "--models-file", str(config_dir / "models.yaml"),
        "--prompt-dimensions-file", str(config_dir / "prompt_dimensions.yaml"),
        "--out", str(tmp_path / "runs"),
        "--test-cases-dir", str(tmp_path / "test_cases"),
        "--samples", "1",
        "--k", "1",
        "--processes", "1",
    ])
    assert gen_result.exit_code == 0, gen_result.output
    runs_dir = tmp_path / "runs"
    run_subdirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    latest = run_subdirs[-1]
    # Evaluate
    eval_result = runner_cli.invoke(app, [
        "evaluate",
        str(latest),
        "--test-cases-dir", str(tmp_path / "test_cases"),
        "--k", "1",
        "--processes", "1",
        "--no-generate-report",
        "--processes", "1",
    ])
    assert eval_result.exit_code == 0, eval_result.output
    data = json.loads((latest / "results.json").read_text(encoding="utf-8"))
    assert data["results"][0]["result"] == "PASS"


def test_requirement_na_does_not_change_sample_or_aggregate_pass_semantics(monkeypatch, tmp_path):
    def gen_html(model, prompt, iteration, temperature=None, seed=None, disable_cache=False):
        status_comment = f"<!-- seed:{seed} -->" if seed is not None else ""
        return f"<html><body>{status_comment}</body></html>", {
            "cached": False,
            "latency_s": 0.01,
            "prompt_hash": "hash",
            "cost_usd": 0.0001,
            "seed": seed,
            "temperature": temperature,
        }

    def run(html, test_js_path, screenshot_path):
        import re
        m = re.search(r"seed:(\d+)", html)
        seed = int(m.group(1)) if m else 0
        if seed in {200, 201}:
            return {
                "testFunctionResult": {
                    "status": "pass",
                    "assertions": [{"name": "req", "status": "na", "type": "R"}],
                    "duration_ms": 1,
                    "total_assertion_na": 1,
                },
                "axeResult": {"failure_count": 0, "failures": []},
            }
        status = "pass" if seed == 202 else "fail"
        return {
            "testFunctionResult": {
                "status": status,
                "assertions": [{"name": "req", "status": status, "type": "R"}],
                "duration_ms": 1,
            },
            "axeResult": {"failure_count": 0, "failures": []},
        }

    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", gen_html)
    monkeypatch.setattr("a11y_llm_tests.node_bridge.run", run)

    tc_dir = tmp_path / "test_cases" / "na-case"
    tc_dir.mkdir(parents=True)
    (tc_dir / "prompt.yaml").write_text("base_prompt: |\n  Prompt\n", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "models.yaml").write_text("""models:\n  - name: model-na\n""", encoding="utf-8")
    (config_dir / "prompt_dimensions.yaml").write_text("dimensions: {}\n", encoding="utf-8")

    runner_cli = CliRunner()
    gen_result = runner_cli.invoke(app, [
        "run",
        "--models-file", str(config_dir / "models.yaml"),
        "--prompt-dimensions-file", str(config_dir / "prompt_dimensions.yaml"),
        "--out", str(tmp_path / "runs"),
        "--test-cases-dir", str(tmp_path / "test_cases"),
        "--samples", "4",
        "--k", "1,2",
        "--base-seed", "200",
        "--processes", "1",
    ])
    assert gen_result.exit_code == 0, gen_result.output
    latest = sorted((tmp_path / "runs").iterdir())[-1]
    eval_result = runner_cli.invoke(app, [
        "evaluate",
        str(latest),
        "--test-cases-dir", str(tmp_path / "test_cases"),
        "--k", "1,2",
        "--processes", "1",
        "--no-generate-report",
        "--processes", "1",
    ])
    assert eval_result.exit_code == 0, eval_result.output
    data = json.loads((latest / "results.json").read_text(encoding="utf-8"))
    agg = data["aggregates"][0]
    assert agg["n_samples"] == 4
    assert agg["n_applicable"] == 4
    assert agg["n_not_applicable"] == 0
    assert agg["n_pass"] == 3
    assert agg["pass_at_k"]["1"] == 0.75
    assert agg["pass_at_k"]["2"] == 1.0
    na_results = [r for r in data["results"] if r["test_function"].get("total_assertion_na") == 1]
    assert len(na_results) == 2
    assert all(r["result"] == "PASS" for r in na_results)