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


def fake_generate_html_with_meta(model, prompt, temperature=None, seed=None, disable_cache=False):
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
    (tc_dir / "prompt.md").write_text("Generate a page", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")

    # Provide models config
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text("""models:\n  - name: test-model\n""", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, [
        "run",
        "--models-file", str(config_dir / "models.yaml"),
        "--out", str(tmp_path / "runs"),
        "--test-cases-dir", str(tmp_path / "test_cases"),
        "--samples", "4",
        "--k", "1,2,4",
        "--base-seed", "100",
    ])
    assert result.exit_code == 0, result.output

    # Find newest run dir
    runs_dir = tmp_path / "runs"
    run_subdirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    assert run_subdirs, "No run directory created"
    latest = run_subdirs[-1]
    data = json.loads((latest / "results.json").read_text(encoding="utf-8"))

    # Validate aggregates
    aggs = data["aggregates"]
    assert len(aggs) == 1
    agg = aggs[0]
    assert agg["n_samples"] == 4
    # Seeds 100,101,102,103 -> pass,fail,pass,fail => 2 passes
    assert agg["n_pass"] == 2
    # pass@1 should be 0.5 (2/4). pass@2 using formula: 1 - ( (2C2)/(4C2) ) = 1 - (1/6)=0.8333
    p1 = agg["pass_at_k"]["1"]
    p2 = agg["pass_at_k"]["2"]
    assert abs(p1 - 0.5) < 1e-6
    assert 0.82 < p2 < 0.85
    # pass@4 should be 1.0 since at least one pass among all samples
    assert agg["pass_at_k"]["4"] == 1.0

    # Ensure sample_index recorded
    sample_indices = sorted(r["sample_index"] for r in data["results"])
    assert sample_indices == [0,1,2,3]


def test_cli_sampling_single(monkeypatch, tmp_path):
    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", fake_generate_html_with_meta)
    monkeypatch.setattr("a11y_llm_tests.node_bridge.run", fake_run)

    tc_dir = tmp_path / "test_cases" / "single"
    tc_dir.mkdir(parents=True)
    (tc_dir / "prompt.md").write_text("Prompt", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "models.yaml").write_text("""models:\n  - name: m1\n""", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, [
        "run",
        "--models-file", str(config_dir / "models.yaml"),
        "--out", str(tmp_path / "runs"),
        "--test-cases-dir", str(tmp_path / "test_cases"),
        "--samples", "1",
        "--k", "1,5",
        "--base-seed", "5",
    ])
    assert result.exit_code == 0, result.output

    runs_dir = tmp_path / "runs"
    run_subdirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    latest = run_subdirs[-1]
    data = json.loads((latest / "results.json").read_text(encoding="utf-8"))
    agg = data["aggregates"][0]
    assert agg["n_samples"] == 1
    # pass@k for single sample equals pass probability = 1 if pass else 0
    # Seed=5 -> fail (odd)
    assert agg["n_pass"] == 0
    assert agg["pass_at_k"]["1"] == 0.0


def test_bp_failure_not_affect_requirement_pass(monkeypatch, tmp_path):
    # Requirement passes, BP fails => overall should pass
    def gen_html(model, prompt, temperature=None, seed=None, disable_cache=False):
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
    (tc_dir / "prompt.md").write_text("Prompt", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "models.yaml").write_text("""models:\n  - name: modelX\n""", encoding="utf-8")

    runner_cli = CliRunner()
    result = runner_cli.invoke(app, [
        "run",
        "--models-file", str(config_dir / "models.yaml"),
        "--out", str(tmp_path / "runs"),
        "--test-cases-dir", str(tmp_path / "test_cases"),
        "--samples", "1",
        "--k", "1",
    ])
    assert result.exit_code == 0, result.output
    runs_dir = tmp_path / "runs"
    run_subdirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    latest = run_subdirs[-1]
    data = json.loads((latest / "results.json").read_text(encoding="utf-8"))
    # Should still be recorded as pass (since requirement passed and BP ignored for pass/fail)
    assert data["results"][0]["result"] == "PASS"