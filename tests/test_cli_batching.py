import json

from typer.testing import CliRunner

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