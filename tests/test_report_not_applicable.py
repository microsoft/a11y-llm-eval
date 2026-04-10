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


def test_render_report_formats_assertion_messages_as_sublists(tmp_path: Path):
    run_dir = tmp_path / "runs" / "2026-04-09_18-26-19"
    run_dir.mkdir(parents=True)

    run_json_path = run_dir / "results.json"
    run_json_path.write_bytes(
        orjson.dumps(
            {
                "run_id": "2026-04-09_18-26-19",
                "models": ["provider/model-a"],
                "tests": ["sample-case"],
                "prompts": {"sample-case": "Generate a set of radio buttons."},
                "meta": {
                    "sampling": {"samples_per_case": 1},
                    "status": "EVALUATED",
                },
                "results": [
                    {
                        "test_name": "sample-case",
                        "model_name": "provider/model-a",
                        "timestamp": "2026-04-09T18:30:00Z",
                        "generation_html_path": "runs/2026-04-09_18-26-19/raw/sample-case/model-a.html",
                        "screenshot_path": None,
                        "test_function": {
                            "status": "fail",
                            "assertions": [
                                {
                                    "name": "Visible label is included in accessible name",
                                    "status": "fail",
                                    "type": "R",
                                    "message": "Visible label mismatch: text input \"PythonA valid language or technology in this context.\" has visible label \"PythonA valid language or technology in this context.\" but accessible name \"Python\", text input \"JavaScriptA valid language or technology in this context.\" has visible label \"JavaScriptA valid language or technology in this context.\" but accessible name \"JavaScript\", and 8 more",
                                }
                            ],
                            "total_assertion_failures": 1,
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
                        "result": "FAIL",
                        "generation": {
                            "latency_s": 0.01,
                            "prompt_hash": "abc",
                            "cached": False,
                            "cost_usd": None,
                        },
                        "sample_index": 0,
                        "prompt_variant_id": "control",
                    }
                ],
                "aggregates": [
                    {
                        "test_name": "sample-case",
                        "model_name": "provider/model-a",
                        "prompt_variant_id": "control",
                        "n_samples": 1,
                        "n_applicable": 1,
                        "n_not_applicable": 0,
                        "n_pass": 0,
                        "pass_at_k": {"1": 0.0},
                        "k_values": [1],
                        "computed_at": "2026-04-09T18:30:02Z",
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
    assert 'class="assertion-message-list"' in html
    assert "Visible label mismatch:" in html
    assert "text input &#34;PythonA valid language or technology in this context.&#34; has visible label &#34;PythonA valid language or technology in this context.&#34; but accessible name &#34;Python&#34;" in html
    assert "text input &#34;JavaScriptA valid language or technology in this context.&#34; has visible label &#34;JavaScriptA valid language or technology in this context.&#34; but accessible name &#34;JavaScript&#34;" in html
    assert '<li>8 more</li>' in html


def test_render_report_formats_repeated_helper_text_messages_as_sublists(tmp_path: Path):
    run_dir = tmp_path / "runs" / "2026-04-09_18-40-00"
    run_dir.mkdir(parents=True)

    run_json_path = run_dir / "results.json"
    run_json_path.write_bytes(
        orjson.dumps(
            {
                "run_id": "2026-04-09_18-40-00",
                "models": ["provider/model-a"],
                "tests": ["sample-case"],
                "prompts": {"sample-case": "Generate a quiz form."},
                "meta": {
                    "sampling": {"samples_per_case": 1},
                    "status": "EVALUATED",
                },
                "results": [
                    {
                        "test_name": "sample-case",
                        "model_name": "provider/model-a",
                        "timestamp": "2026-04-09T18:40:00Z",
                        "generation_html_path": "runs/2026-04-09_18-40-00/raw/sample-case/model-a.html",
                        "screenshot_path": None,
                        "test_function": {
                            "status": "fail",
                            "assertions": [
                                {
                                    "name": "Helper text is programmatically associated",
                                    "status": "fail",
                                    "type": "R",
                                    "message": "text input \"PythonA valid language or technology in this context.\" has helper text \"1. Which of the following are programming languages?\" that is not programmatically associated text input \"JavaScriptA valid language or technology in this context.\" has helper text \"1. Which of the following are programming languages?\" that is not programmatically associated",
                                }
                            ],
                            "total_assertion_failures": 1,
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
                        "result": "FAIL",
                        "generation": {
                            "latency_s": 0.01,
                            "prompt_hash": "def",
                            "cached": False,
                            "cost_usd": None,
                        },
                        "sample_index": 0,
                        "prompt_variant_id": "control",
                    }
                ],
                "aggregates": [
                    {
                        "test_name": "sample-case",
                        "model_name": "provider/model-a",
                        "prompt_variant_id": "control",
                        "n_samples": 1,
                        "n_applicable": 1,
                        "n_not_applicable": 0,
                        "n_pass": 0,
                        "pass_at_k": {"1": 0.0},
                        "k_values": [1],
                        "computed_at": "2026-04-09T18:40:02Z",
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
    assert 'class="assertion-message-list"' in html
    assert "Helper text is programmatically associated" in html
    assert "text input &#34;PythonA valid language or technology in this context.&#34; has helper text &#34;1. Which of the following are programming languages?&#34; that is not programmatically associated" in html
    assert "text input &#34;JavaScriptA valid language or technology in this context.&#34; has helper text &#34;1. Which of the following are programming languages?&#34; that is not programmatically associated" in html