from pathlib import Path

import orjson

from a11y_llm_tests.report import render_report


def test_render_report_handles_not_applicable_samples(tmp_path: Path):
    run_dir = tmp_path / "runs" / "2026-03-27_12-00-00"
    run_dir.mkdir(parents=True)

    run_json_path = run_dir / "results.json"
    run_json_path.write_bytes(
        orjson.dumps(
            {
                "run_id": "2026-03-27_12-00-00",
                "models": ["provider/model-a"],
                "tests": ["sample-case"],
                "prompts": {"sample-case": "Generate a simple form."},
                "meta": {
                    "sampling": {"samples_per_case": 2},
                    "status": "EVALUATED",
                },
                "results": [
                    {
                        "test_name": "sample-case",
                        "model_name": "provider/model-a",
                        "timestamp": "2026-03-27T12:00:00Z",
                        "generation_html_path": "runs/2026-03-27_12-00-00/raw/sample-case/model-a__s0.html",
                        "screenshot_path": None,
                        "test_function": {
                            "status": "pass",
                            "assertions": [
                                {"name": "required fields indicated", "status": "pass", "type": "R"},
                            ],
                            "total_assertion_failures": 0,
                            "total_assertion_bp_failures": 0,
                            "total_assertion_na": 0,
                            "total_assertion_bp_na": 0,
                        },
                        "axe": {
                            "failure_count": 0,
                            "failures": [],
                            "best_practice_count": 0,
                            "best_practice_failures": [],
                        },
                        "result": "PASS",
                        "generation": {
                            "latency_s": 0.01,
                            "prompt_hash": "abc",
                            "cached": False,
                            "cost_usd": None,
                        },
                        "sample_index": 0,
                        "prompt_variant_id": "control",
                    },
                    {
                        "test_name": "sample-case",
                        "model_name": "provider/model-a",
                        "timestamp": "2026-03-27T12:00:01Z",
                        "generation_html_path": "runs/2026-03-27_12-00-00/raw/sample-case/model-a__s1.html",
                        "screenshot_path": None,
                        "test_function": {
                            "status": "pass",
                            "assertions": [
                                {"name": "required fields indicated", "status": "na", "type": "R", "message": "No required fields found."},
                            ],
                            "total_assertion_failures": 0,
                            "total_assertion_bp_failures": 0,
                            "total_assertion_na": 1,
                            "total_assertion_bp_na": 0,
                        },
                        "axe": {
                            "failure_count": 0,
                            "failures": [],
                            "best_practice_count": 0,
                            "best_practice_failures": [],
                        },
                        "result": "PASS",
                        "generation": {
                            "latency_s": 0.01,
                            "prompt_hash": "def",
                            "cached": False,
                            "cost_usd": None,
                        },
                        "sample_index": 1,
                        "prompt_variant_id": "control",
                    },
                ],
                "aggregates": [
                    {
                        "test_name": "sample-case",
                        "model_name": "provider/model-a",
                        "prompt_variant_id": "control",
                        "n_samples": 2,
                        "n_applicable": 2,
                        "n_not_applicable": 0,
                        "n_pass": 2,
                        "pass_at_k": {"1": 1.0},
                        "k_values": [1],
                        "computed_at": "2026-03-27T12:00:02Z",
                    }
                ],
            }
        )
    )

    out_html = run_dir / "index.html"
    render_report(
        run_json_path,
        out_html,
        {"models": [{"name": "provider/model-a", "display_name": "Model A"}]},
    )

    html = out_html.read_text(encoding="utf-8")
    assert "<th>WCAG Pass Rate*</th><th>Avg Total WCAG Failures</th>" in html
    assert "<th>WCAG Pass Rate*</th><th>Samples</th>" not in html
    assert "Samples: 2 | Passes: 2" in html
    assert 'data-assertion-status="na"' in html
    assert "Not applicable" in html