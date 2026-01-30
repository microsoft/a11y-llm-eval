import json
from pathlib import Path

from typer.testing import CliRunner

from a11y_llm_tests.cli import app


def test_instruction_benchmarks_variants(monkeypatch, tmp_path: Path):
    # Fake generator that embeds current custom instructions into HTML so the fake
    # runner can behave differently for control vs variants.
    def fake_generate_html_with_meta(model, prompt, iteration, temperature=None, seed=None, disable_cache=False):
        from a11y_llm_tests import generator as gen

        instr = gen.get_custom_instructions()
        variant = "control" if not instr else ("concise" if "VARIANT_ID=concise" in instr else "other")
        html = (
            f"<html><body><h1>{model}</h1>"
            f"<!-- variant:{variant} -->"
            f"<!-- seed:{seed} -->"
            f"</body></html>"
        )
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

    # Fake node runner: control passes, variants fail.
    def fake_run(html, test_js_path, screenshot_path):
        import re

        m = re.search(r"variant:([^\s-]+)", html)
        variant = m.group(1) if m else "control"
        status = "pass" if variant == "control" else "fail"
        return {
            "testFunctionResult": {
                "status": status,
                "assertions": [
                    {"name": "dummy", "status": status, "message": None, "type": "R"},
                ],
                "duration_ms": 5,
            },
            # Keep legacy-ish fields; evaluator treats missing failure_count as 0.
            "axeResult": {
                "violation_count": 0,
                "violations": [],
            },
        }

    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", fake_generate_html_with_meta)
    monkeypatch.setattr("a11y_llm_tests.node_bridge.run", fake_run)

    # Minimal test case
    tc_dir = tmp_path / "test_cases" / "sample-case"
    tc_dir.mkdir(parents=True)
    (tc_dir / "prompt.md").write_text("Generate a page", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")

    # Models config
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text("""models:\n  - name: test-model\n""", encoding="utf-8")

    # Instruction sets
    instr_dir = config_dir / "instructions"
    instr_dir.mkdir()
    (instr_dir / "concise.md").write_text("VARIANT_ID=concise\n", encoding="utf-8")
    (config_dir / "instruction_sets.yaml").write_text(
        """instruction_sets:\n  - id: concise\n    name: Concise\n    description: Prefer minimal HTML\n    system_prompt_append_markdown: instructions/concise.md\n    samples: 3\n""",
        encoding="utf-8",
    )

    runner = CliRunner()

    # Generate control + variant
    gen_res = runner.invoke(
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
            "2",
            "--instruction-sets-file",
            str(config_dir / "instruction_sets.yaml"),
            "--processes",
            "1",
            "--base-seed",
            "100",
        ],
    )
    assert gen_res.exit_code == 0, gen_res.output

    runs_dir = tmp_path / "runs"
    run_subdirs = sorted(p for p in runs_dir.iterdir() if p.is_dir())
    latest = run_subdirs[-1]

    # Verify artifacts: control raw + variants raw_variants
    control_files = sorted((latest / "raw" / "sample-case").glob("*.html"))
    assert len(control_files) == 2
    variant_files = sorted((latest / "raw_variants" / "concise" / "sample-case").glob("*.html"))
    assert len(variant_files) == 3

    # Verify results.json includes prompt_variants metadata
    pre_data = json.loads((latest / "results.json").read_text(encoding="utf-8"))
    pv = pre_data.get("meta", {}).get("prompt_variants")
    assert pv and any(x.get("id") == "control" for x in pv)
    assert any(x.get("id") == "concise" for x in pv)

    # Evaluate + report
    eval_res = runner.invoke(
        app,
        [
            "evaluate",
            str(latest),
            "--test-cases-dir",
            str(tmp_path / "test_cases"),
            "--k",
            "1,3",
            "--processes",
            "1",
        ],
    )
    assert eval_res.exit_code == 0, eval_res.output

    data = json.loads((latest / "results.json").read_text(encoding="utf-8"))

    # Aggregates exist for both control and variant
    aggs = data.get("aggregates") or []
    assert len(aggs) == 2
    by_variant = {a.get("prompt_variant_id"): a for a in aggs}
    assert by_variant["control"]["n_samples"] == 2
    assert by_variant["concise"]["n_samples"] == 3

    # Evaluated results include prompt_variant_id
    variants = sorted({r.get("prompt_variant_id") for r in data.get("results")})
    assert variants == ["concise", "control"]

    # Report includes the comparison section
    index_html = (latest / "index.html").read_text(encoding="utf-8")
    assert "Instruction Benchmarks (vs Control)" in index_html
    assert "Concise" in index_html
