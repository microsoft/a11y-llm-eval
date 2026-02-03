from typer.testing import CliRunner

from a11y_llm_tests.cli import app
from a11y_llm_tests import generator


def test_cli_exits_fast_on_output_token_limit(monkeypatch, tmp_path):
    def fake_generate_html_with_meta(model, prompt, iteration, **kwargs):
        raise generator.OutputTokenLimitHit(
            model=model,
            max_tokens=8192,
            finish_reason="length",
            stop_reason=None,
            tokens_out=8192,
        )

    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", fake_generate_html_with_meta)

    # Minimal test case directory
    tc_dir = tmp_path / "test_cases" / "sample-case"
    tc_dir.mkdir(parents=True)
    (tc_dir / "prompt.md").write_text("Generate a page", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")

    # Models config
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text("""models:\n  - name: test-model\n""", encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "run",
            "--models-file",
            str(config_dir / "models.yaml"),
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
        ],
    )

    assert res.exit_code == 2
    assert "Output token limit hit" in res.output
