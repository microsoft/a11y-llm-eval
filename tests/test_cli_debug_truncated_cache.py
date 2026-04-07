import json
from typer.testing import CliRunner

from a11y_llm_tests.cli import app


def test_cli_debug_truncated_cache_prints_list(monkeypatch, tmp_path):
    # Stub generator to simulate detection of a truncated cache entry.
    def fake_generate_html_with_meta(model, prompt, iteration, temperature=None, seed=None, disable_cache=False, **kwargs):
        html = "<html><body><h1>OK</h1></body></html>"
        return html, {
            "cached": False,
            "latency_s": 0.01,
            "prompt_hash": "deadbeef",
            "tokens_in": 1,
            "tokens_out": 1,
            "total_tokens": 2,
            "cost_usd": 0.0,
            "seed": seed,
            "temperature": temperature,
            "truncated_cache_files": [".cache/generations/bad_file.html"],
        }

    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", fake_generate_html_with_meta)

    # Minimal test case directory
    tc_dir = tmp_path / "test_cases" / "sample-case"
    tc_dir.mkdir(parents=True)
    (tc_dir / "prompt.yaml").write_text("base_prompt: |\n  Generate a page\n", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")

    # Models config
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text("""models:\n  - name: test-model\n""", encoding="utf-8")
    (config_dir / "prompt_dimensions.yaml").write_text("dimensions: {}\n", encoding="utf-8")

    runner = CliRunner()
    gen_result = runner.invoke(
        app,
        [
            "run",
            "--models-file",
            str(config_dir / "models.yaml"),
            "--prompt-dimensions-file",
            str(config_dir / "prompt_dimensions.yaml"),
            "--out",
            str(tmp_path / "runs"),
            "--test-cases-dir",
            str(tmp_path / "test_cases"),
            "--samples",
            "1",
            "--k",
            "1",
            "--processes",
            "1",
            "--debug-truncated-cache",
        ],
    )

    assert gen_result.exit_code == 0, gen_result.output
    assert "Truncated/corrupted cached HTML files detected" in gen_result.output
    assert ".cache/generations/bad_file.html" in gen_result.output

    # Ensure run artifacts were still produced.
    runs_dir = tmp_path / "runs"
    run_subdirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    assert run_subdirs
    latest = run_subdirs[-1]
    data = json.loads((latest / "results.json").read_text(encoding="utf-8"))
    assert data["meta"]["status"] == "GENERATED_ONLY"
