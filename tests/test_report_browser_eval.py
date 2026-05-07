from __future__ import annotations

import json
import subprocess
from pathlib import Path

import orjson

from a11y_llm_tests import node_bridge
from a11y_llm_tests.report import render_report


REPORT_BROWSER_TEST_PATH = Path(__file__).resolve().parent / "fixtures" / "report_browser_test.js"


def _write_report_fixture(run_dir: Path) -> None:
    conversation_path = run_dir / "sample.agent.json"
    conversation_path.write_bytes(
        orjson.dumps(
            {
                "messages": [
                    {"role": "user", "content": "Build an accessible modal dialog."},
                    {"role": "assistant", "content": "I added a labelled modal with focus management."},
                ],
                "events": [],
            }
        )
    )

    results = {
        "run_id": "2026-05-06_12-00-00",
        "models": ["provider/model-a", "provider/model-b"],
        "tests": ["sample-case"],
        "prompts": {"sample-case": "Generate an accessible modal dialog demo."},
        "meta": {
            "sampling": {"samples_per_case": 1},
            "status": "EVALUATED",
            "prompt_variants": [
                {
                    "id": "instructions-better-labels",
                    "name": "Better Labels",
                    "kind": "instruction_set",
                    "description": "Prefer explicit labeling and helper text.",
                    "url": "https://example.com/instructions/better-labels",
                },
                {
                    "id": "skill-audit-loop",
                    "name": "Audit Loop",
                    "kind": "skill",
                    "description": "Draft, then repair accessibility issues.",
                    "url": "https://example.com/skills/audit-loop",
                    "turns": [
                        {"id": "draft", "name": "Draft"},
                        {"id": "repair", "name": "Repair"},
                    ],
                },
            ],
        },
        "results": [
            {
                "test_name": "sample-case",
                "model_name": "provider/model-a",
                "timestamp": "2026-05-06T12:00:00Z",
                "generation_html_path": "runs/2026-05-06_12-00-00/raw/sample-case/model-a__s0.html",
                "generation_conversation_path": str(conversation_path),
                "screenshot_path": None,
                "test_function": {
                    "status": "pass",
                    "assertions": [
                        {"name": "Modal has accessible name", "status": "pass", "type": "R"},
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
                    "prompt_hash": "control-a",
                    "cached": False,
                    "cost_usd": None,
                },
                "sample_index": 0,
                "prompt_variant_id": "control",
            },
            {
                "test_name": "sample-case",
                "model_name": "provider/model-b",
                "timestamp": "2026-05-06T12:00:01Z",
                "generation_html_path": "runs/2026-05-06_12-00-00/raw/sample-case/model-b__s0.html",
                "screenshot_path": None,
                "test_function": {
                    "status": "fail",
                    "assertions": [
                        {"name": "Modal has accessible name", "status": "fail", "type": "R", "message": "aria-labelledby missing"},
                    ],
                    "total_assertion_failures": 1,
                    "total_assertion_bp_failures": 0,
                    "total_assertion_na": 0,
                    "total_assertion_bp_na": 0,
                },
                "axe": {
                    "failure_count": 1,
                    "failures": [
                        {"id": "aria-dialog-name", "impact": "serious", "description": "Dialogs must have an accessible name", "nodes": [{"html": "<div role=dialog>", "target": ["#dialog"]}]},
                    ],
                    "best_practice_count": 0,
                    "best_practice_failures": [],
                },
                "result": "FAIL",
                "generation": {
                    "latency_s": 0.01,
                    "prompt_hash": "control-b",
                    "cached": False,
                    "cost_usd": None,
                },
                "sample_index": 0,
                "prompt_variant_id": "control",
            },
            {
                "test_name": "sample-case",
                "model_name": "provider/model-a",
                "timestamp": "2026-05-06T12:00:02Z",
                "generation_html_path": "runs/2026-05-06_12-00-00/raw_variants/sample-case/model-a__s0.html",
                "screenshot_path": None,
                "test_function": {
                    "status": "pass",
                    "assertions": [
                        {"name": "Modal has accessible name", "status": "pass", "type": "R"},
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
                    "prompt_hash": "variant-a",
                    "cached": False,
                    "cost_usd": None,
                },
                "sample_index": 0,
                "prompt_variant_id": "instructions-better-labels",
            },
            {
                "test_name": "sample-case",
                "model_name": "provider/model-a",
                "timestamp": "2026-05-06T12:00:03Z",
                "generation_html_path": "runs/2026-05-06_12-00-00/raw_skills/sample-case/model-a__s0_turn0.html",
                "screenshot_path": None,
                "test_function": {
                    "status": "fail",
                    "assertions": [
                        {"name": "Modal has accessible name", "status": "fail", "type": "R", "message": "Initial draft missing title association"},
                    ],
                    "total_assertion_failures": 1,
                    "total_assertion_bp_failures": 0,
                    "total_assertion_na": 0,
                    "total_assertion_bp_na": 0,
                },
                "axe": {
                    "failure_count": 1,
                    "failures": [
                        {"id": "aria-dialog-name", "impact": "serious", "description": "Dialogs must have an accessible name", "nodes": [{"html": "<div role=dialog>", "target": ["#dialog"]}]},
                    ],
                    "best_practice_count": 0,
                    "best_practice_failures": [],
                },
                "result": "FAIL",
                "generation": {
                    "latency_s": 0.01,
                    "prompt_hash": "skill-draft",
                    "cached": False,
                    "cost_usd": None,
                },
                "sample_index": 0,
                "prompt_variant_id": "skill-audit-loop",
                "turn_id": "draft",
                "turn_index": 0,
                "turn_count_total": 2,
            },
            {
                "test_name": "sample-case",
                "model_name": "provider/model-a",
                "timestamp": "2026-05-06T12:00:04Z",
                "generation_html_path": "runs/2026-05-06_12-00-00/raw_skills/sample-case/model-a__s0_turn1.html",
                "screenshot_path": None,
                "test_function": {
                    "status": "pass",
                    "assertions": [
                        {"name": "Modal has accessible name", "status": "pass", "type": "R"},
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
                    "prompt_hash": "skill-repair",
                    "cached": False,
                    "cost_usd": None,
                },
                "sample_index": 0,
                "prompt_variant_id": "skill-audit-loop",
                "turn_id": "repair",
                "turn_index": 1,
                "turn_count_total": 2,
            },
        ],
        "aggregates": [
            {
                "test_name": "sample-case",
                "model_name": "provider/model-a",
                "prompt_variant_id": "control",
                "n_samples": 1,
                "n_applicable": 1,
                "n_not_applicable": 0,
                "n_pass": 1,
                "pass_at_k": {"1": 1.0},
                "k_values": [1],
                "computed_at": "2026-05-06T12:00:05Z",
            },
            {
                "test_name": "sample-case",
                "model_name": "provider/model-b",
                "prompt_variant_id": "control",
                "n_samples": 1,
                "n_applicable": 1,
                "n_not_applicable": 0,
                "n_pass": 0,
                "pass_at_k": {"1": 0.0},
                "k_values": [1],
                "computed_at": "2026-05-06T12:00:05Z",
            },
        ],
    }
    (run_dir / "results.json").write_bytes(orjson.dumps(results))


def _render_report_fixture(tmp_path: Path) -> Path:
    run_dir = tmp_path / "runs" / "2026-05-06_12-00-00"
    run_dir.mkdir(parents=True)
    _write_report_fixture(run_dir)
    render_report(
        run_dir / "results.json",
        run_dir / "index.html",
        {
            "models": [
                {"name": "provider/model-a", "display_name": "Model A"},
                {"name": "provider/model-b", "display_name": "Model B"},
            ]
        },
    )
    return run_dir


def _run_playwright_report_eval(run_dir: Path, target_relative_path: str, tmp_path: Path) -> dict:
    out_json = tmp_path / f"{Path(target_relative_path).stem}.out.json"
    screenshot = tmp_path / f"{Path(target_relative_path).stem}.png"
    server = node_bridge.serve_directory(run_dir, port=0)
    try:
        target_url = f"{server.base_url}/{target_relative_path.lstrip('/')}"
        proc = subprocess.run(
            [
                "node",
                str(node_bridge.PLAYWRIGHT_RUNNER),
                target_url,
                str(REPORT_BROWSER_TEST_PATH),
                str(out_json),
                str(screenshot),
            ],
            capture_output=True,
            text=True,
            cwd=str(run_dir),
        )
    finally:
        server.close()

    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(out_json.read_text(encoding="utf-8"))


def test_report_browser_eval_covers_interactions_and_axe(tmp_path: Path):
    run_dir = _render_report_fixture(tmp_path)

    result = _run_playwright_report_eval(run_dir, "index.html", tmp_path)

    assert result.get("error") is None, json.dumps(result, indent=2)
    assert result.get("testFunctionResult", {}).get("status") == "pass", json.dumps(result, indent=2)

    axe = result.get("axeResult") or {}
    assert axe.get("failure_count") == 0, json.dumps(result, indent=2)
    assert axe.get("best_practice_count") == 0, json.dumps(result, indent=2)
