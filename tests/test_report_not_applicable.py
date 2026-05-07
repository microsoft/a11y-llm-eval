from pathlib import Path

import orjson

from a11y_llm_tests.report import _prompt_variant_url, _report_relative_display_path, render_report


def test_prompt_variant_url_uses_default_config_fallbacks():
    assert _prompt_variant_url({"id": "accessible_minimal", "url": None}) == "https://github.com/microsoft/a11y-llm-eval/blob/main/config/instructions/accessible-minimal.md"
    assert _prompt_variant_url({"id": "accessible_basic", "url": ""}) == "https://github.com/microsoft/a11y-llm-eval/blob/main/config/instructions/accessible-basic.md"
    assert _prompt_variant_url({"id": "building-accessible-ui"}) == "https://github.com/microsoft/a11y-llm-eval/tree/main/config/skills/building-accessible-ui"
    assert _prompt_variant_url({"id": "custom-skill", "url": "https://example.com/custom"}) == "https://example.com/custom"
    assert _prompt_variant_url({"id": "custom-skill"}) is None


def test_report_relative_display_path_avoids_absolute_paths(tmp_path: Path):
    run_dir = tmp_path / "runs" / "2026-05-07_12-00-00"
    run_dir.mkdir(parents=True)
    skill_dir = tmp_path / "config" / "skills" / "building-accessible-ui"
    assert _report_relative_display_path(str(skill_dir), run_dir) == "../../config/skills/building-accessible-ui"
    assert _report_relative_display_path(f"docker:{skill_dir}", run_dir) == "docker:../../config/skills/building-accessible-ui"
    assert _report_relative_display_path(f"runs/{run_dir.name}/raw/sample/index.html", run_dir) == "raw/sample/index.html"
    assert _report_relative_display_path("config/copilot_sandbox/compose.yaml", run_dir) == "config/copilot_sandbox/compose.yaml"
    assert _report_relative_display_path("https://example.com/path", run_dir) == "https://example.com/path"


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
    assert '<a class="skip-link" href="#overview">Skip to report content</a>' in html
    assert 'href="index.html#overview" data-report-nav="overview"' in html
    assert '<section id="overview-section" data-report-section="overview">' in html
    assert '<h2>Overview</h2>' in html
    assert "const initialKey = keyFromHash() || (sectionByKey.has('overview') ? 'overview' : 'control');" in html
    assert 'Control snapshot' in html
    assert 'browser.__applyExternalFilters = function (filters)' in html
    assert "getExternalFilterValue('data-global-model-filter', '')" in html
    assert 'let syncLoadedReportDetailPanelFilters = function () {};' in html
    assert 'syncLoadedReportDetailPanelFilters(panel);' in html
    assert "<th>Pass rate*</th><th>Avg Total WCAG Failures</th>" in html
    assert "<th>Pass rate*</th><th>Samples</th>" not in html
    assert "Samples: 2 | Passes: 2" in html
    assert 'report_pages/details/sample-case.fragment.html' in html
    detail_fragment = run_dir / "report_pages" / "details" / "sample-case.fragment.html"
    assert detail_fragment.exists()
    detail_html = detail_fragment.read_text(encoding="utf-8")
    assert 'data-assertion-name-filter' in detail_html
    assert 'data-assertion-status-filter' in detail_html
    assert 'data-assertion-status="na"' in detail_html
    assert "Not applicable" in detail_html
    detail_page_html = (run_dir / "report_pages" / "details" / "sample-case.html").read_text(encoding="utf-8")
    assert 'initDetailBrowsers(document);' in detail_page_html
    assert 'browser.__applyExternalFilters = function (filters)' in detail_page_html


def test_render_report_can_omit_generated_html_links(tmp_path: Path):
    run_dir = tmp_path / "runs" / "2026-05-06_10-00-00"
    run_dir.mkdir(parents=True)

    run_json_path = run_dir / "results.json"
    run_json_path.write_bytes(
        orjson.dumps(
            {
                "run_id": "2026-05-06_10-00-00",
                "models": ["provider/model-a"],
                "tests": ["sample-case"],
                "prompts": {"sample-case": "Generate a simple form."},
                "meta": {
                    "sampling": {"samples_per_case": 1},
                    "status": "EVALUATED",
                },
                "results": [
                    {
                        "test_name": "sample-case",
                        "model_name": "provider/model-a",
                        "timestamp": "2026-05-06T10:00:00Z",
                        "generation_html_path": "runs/2026-05-06_10-00-00/raw/sample-case/model-a__s0.html",
                        "screenshot_path": "runs/2026-05-06_10-00-00/screenshots/sample-case/model-a__s0.png",
                        "test_function": {
                            "status": "pass",
                            "assertions": [],
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
                        "n_pass": 1,
                        "pass_at_k": {"1": 1.0},
                        "k_values": [1],
                        "computed_at": "2026-05-06T10:00:01Z",
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
        include_generated_html_samples=False,
    )

    html = out_html.read_text(encoding="utf-8")
    assert 'Sample 0 (Model A)</a>' not in html
    assert 'Open standalone detail page' not in html
    assert 'raw/sample-case/model-a__s0.html' not in html
    assert 'available upon request' in html
    assert 'href="mailto:mfairchild@microsoft.com"' in html

    detail_fragment = run_dir / "report_pages" / "details" / "sample-case.fragment.html"
    detail_html = detail_fragment.read_text(encoding="utf-8")
    assert 'Sample 0 (Model A)' in detail_html
    assert 'screenshots/sample-case/model-a__s0.png' in detail_html


def test_render_report_writes_lazy_loaded_conversation_fragment(tmp_path: Path):
    run_dir = tmp_path / "runs" / "2026-05-06_11-00-00"
    run_dir.mkdir(parents=True)

    conversation_path = run_dir / "sample.agent.json"
    conversation_path.write_bytes(
        orjson.dumps(
            {
                "messages": [
                    {"role": "user", "content": "Build an accessible form."},
                    {"role": "assistant", "content": "I added labels and validation."},
                ],
                "events": [],
            }
        )
    )

    run_json_path = run_dir / "results.json"
    run_json_path.write_bytes(
        orjson.dumps(
            {
                "run_id": "2026-05-06_11-00-00",
                "models": ["provider/model-a"],
                "tests": ["sample-case"],
                "prompts": {"sample-case": "Generate a simple form."},
                "meta": {
                    "sampling": {"samples_per_case": 1},
                    "status": "EVALUATED",
                },
                "results": [
                    {
                        "test_name": "sample-case",
                        "model_name": "provider/model-a",
                        "timestamp": "2026-05-06T11:00:00Z",
                        "generation_html_path": "runs/2026-05-06_11-00-00/raw/sample-case/model-a__s0.html",
                        "generation_conversation_path": str(conversation_path),
                        "screenshot_path": None,
                        "test_function": {
                            "status": "pass",
                            "assertions": [],
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
                        "n_pass": 1,
                        "pass_at_k": {"1": 1.0},
                        "k_values": [1],
                        "computed_at": "2026-05-06T11:00:01Z",
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
    assert "Build an accessible form." not in html
    assert "I added labels and validation." not in html
    detail_html = (run_dir / "report_pages" / "details" / "sample-case.fragment.html").read_text(encoding="utf-8")
    assert 'data-conversation-src="report_pages/conversations/' in detail_html

    conversation_files = list((run_dir / "report_pages" / "conversations").glob("*.html"))
    assert len(conversation_files) == 1
    conversation_html = conversation_files[0].read_text(encoding="utf-8")
    assert "Build an accessible form." in conversation_html
    assert "I added labels and validation." in conversation_html


def test_render_report_overview_summarizes_instruction_sets_and_skills(tmp_path: Path):
    run_dir = tmp_path / "runs" / "2026-05-05_18-00-00"
    run_dir.mkdir(parents=True)
    instructions_path = tmp_path / "config" / "instructions" / "better-labels.md"
    skill_path = tmp_path / "config" / "skills" / "audit-loop"

    run_json_path = run_dir / "results.json"
    run_json_path.write_bytes(
        orjson.dumps(
            {
                "run_id": "2026-05-05_18-00-00",
                "models": ["provider/model-a"],
                "tests": ["sample-case"],
                "prompts": {"sample-case": "Generate an accessible widget."},
                "meta": {
                    "sampling": {"samples_per_case": 1},
                    "status": "EVALUATED",
                    "prompting": {
                        "custom_instructions": "Always include labels.",
                        "custom_instructions_path": str(instructions_path),
                    },
                    "prompt_variants": [
                        {
                            "id": "instructions-better-labels",
                            "name": "Better Labels",
                            "kind": "instruction_set",
                            "description": "Emphasize explicit labels.",
                            "url": "https://example.com/instructions/better-labels",
                            "agent_sandbox": f"docker:{tmp_path / 'config' / 'copilot_sandbox' / 'compose.yaml'}",
                        },
                        {
                            "id": "skill-audit-loop",
                            "name": "Audit Loop",
                            "kind": "skill",
                            "description": "Review and repair accessibility issues.",
                            "url": "https://example.com/skills/audit-loop",
                            "agent_sandbox": f"docker:{tmp_path / 'config' / 'copilot_sandbox' / 'compose.yaml'}",
                            "skill_path": str(skill_path),
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
                        "timestamp": "2026-05-05T18:00:00Z",
                        "generation_html_path": "runs/2026-05-05_18-00-00/raw/sample-case/model-a__s0.html",
                        "screenshot_path": None,
                        "test_function": {
                            "status": "fail",
                            "assertions": [],
                            "total_assertion_failures": 1,
                            "total_assertion_bp_failures": 0,
                            "total_assertion_na": 0,
                            "total_assertion_bp_na": 0,
                        },
                        "axe": {
                            "failure_count": 1,
                            "failures": [{"id": "label", "impact": "serious", "description": "Elements must have labels"}],
                            "best_practice_count": 0,
                            "best_practice_failures": [],
                        },
                        "result": "FAIL",
                        "generation": {
                            "latency_s": 0.01,
                            "prompt_hash": "control",
                            "cached": False,
                            "cost_usd": None,
                        },
                        "sample_index": 0,
                        "prompt_variant_id": "control",
                    },
                    {
                        "test_name": "sample-case",
                        "model_name": "provider/model-a",
                        "timestamp": "2026-05-05T18:00:01Z",
                        "generation_html_path": "runs/2026-05-05_18-00-00/raw_variants/sample-case/model-a__s0.html",
                        "screenshot_path": None,
                        "test_function": {
                            "status": "pass",
                            "assertions": [],
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
                            "prompt_hash": "variant",
                            "cached": False,
                            "cost_usd": None,
                        },
                        "sample_index": 0,
                        "prompt_variant_id": "instructions-better-labels",
                    },
                    {
                        "test_name": "sample-case",
                        "model_name": "provider/model-a",
                        "timestamp": "2026-05-05T18:00:02Z",
                        "generation_html_path": "runs/2026-05-05_18-00-00/raw_skills/sample-case/model-a__s0_turn0.html",
                        "screenshot_path": None,
                        "test_function": {
                            "status": "fail",
                            "assertions": [],
                            "total_assertion_failures": 1,
                            "total_assertion_bp_failures": 0,
                            "total_assertion_na": 0,
                            "total_assertion_bp_na": 0,
                        },
                        "axe": {
                            "failure_count": 1,
                            "failures": [],
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
                        "timestamp": "2026-05-05T18:00:03Z",
                        "generation_html_path": "runs/2026-05-05_18-00-00/raw_skills/sample-case/model-a__s0_turn1.html",
                        "screenshot_path": None,
                        "test_function": {
                            "status": "pass",
                            "assertions": [],
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
                        "n_pass": 0,
                        "pass_at_k": {"1": 0.0},
                        "k_values": [1],
                        "computed_at": "2026-05-05T18:00:04Z",
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
    assert 'Run scope: 1 models | 1 prompt cases | 1 control samples | 1 instruction sets | 1 skills' in html
    assert 'Control baseline' in html
    assert 'Overall control pass rate*; best model Model A at 0%' in html
    assert 'Hardest case' in html
    assert '0% pass rate*, 2.00 avg WCAG failures' in html
    assert 'Best instruction lift' in html
    assert 'Instruction-set snapshot' in html
    assert 'Better Labels' in html
    assert '<th><a href="https://example.com/instructions/better-labels">Better Labels</a></th>' in html
    assert '<a href="https://example.com/instructions/better-labels">Full instruction set</a>' in html
    assert 'Best skill lift' in html
    assert 'Skill snapshot' in html
    assert 'Audit Loop' in html
    assert '<th><a href="https://example.com/skills/audit-loop">Audit Loop</a></th>' in html
    assert '<a href="https://example.com/skills/audit-loop">Full skill</a>' in html
    assert str(tmp_path) not in html
    assert '../../config/instructions/better-labels.md' in html
    assert '../../config/skills/audit-loop' in html
    assert 'docker:../../config/copilot_sandbox/compose.yaml' in html
    assert 'Best final-turn delta +100.0pp vs control' in html
    assert '+100.0pp vs turn 1' in html
    assert '<option value="instructions-better-labels">Better Labels</option>' in html
    assert '<option value="skill-audit-loop">Audit Loop</option>' in html


def test_render_report_includes_detectable_difference_methodology_note(tmp_path: Path):
    run_dir = tmp_path / "runs" / "2026-05-05_12-00-00"
    run_dir.mkdir(parents=True)

    prompt_cases = [f"sample-case-{index}" for index in range(32)]
    run_json_path = run_dir / "results.json"
    run_json_path.write_bytes(
        orjson.dumps(
            {
                "run_id": "2026-05-05_12-00-00",
                "models": ["provider/model-a"],
                "tests": prompt_cases,
                "prompts": {prompt_case: f"Prompt for {prompt_case}" for prompt_case in prompt_cases},
                "meta": {
                    "sampling": {"samples_per_case": 10},
                    "status": "EVALUATED",
                },
                "results": [
                    {
                        "test_name": prompt_cases[0],
                        "model_name": "provider/model-a",
                        "timestamp": "2026-05-05T12:00:00Z",
                        "generation_html_path": "runs/2026-05-05_12-00-00/raw/sample-case-0/model-a__s0.html",
                        "screenshot_path": None,
                        "test_function": {
                            "status": "pass",
                            "assertions": [],
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
                    }
                ],
                "aggregates": [
                    {
                        "test_name": prompt_cases[0],
                        "model_name": "provider/model-a",
                        "prompt_variant_id": "control",
                        "n_samples": 10,
                        "n_applicable": 10,
                        "n_not_applicable": 0,
                        "n_pass": 7,
                        "pass_at_k": {"1": 0.7},
                        "k_values": [1],
                        "computed_at": "2026-05-05T12:00:02Z",
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
    assert "This report is not used for model training" in html
    assert "the testing is not comprehensive" in html
    assert "Based on 32 prompt cases and 10 samples per case" in html
    assert "320 samples per model" in html
    assert "11.1" in html
    assert "two-model comparison" in html


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

    html = (run_dir / "report_pages" / "details" / "sample-case.fragment.html").read_text(encoding="utf-8")
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

    html = (run_dir / "report_pages" / "details" / "sample-case.fragment.html").read_text(encoding="utf-8")
    assert 'class="assertion-message-list"' in html
    assert "Helper text is programmatically associated" in html
    assert "text input &#34;PythonA valid language or technology in this context.&#34; has helper text &#34;1. Which of the following are programming languages?&#34; that is not programmatically associated" in html
    assert "text input &#34;JavaScriptA valid language or technology in this context.&#34; has helper text &#34;1. Which of the following are programming languages?&#34; that is not programmatically associated" in html


def test_render_report_does_not_split_on_colon_inside_quoted_helper_text(tmp_path: Path):
    run_dir = tmp_path / "runs" / "2026-04-13_19-19-24"
    run_dir.mkdir(parents=True)

    run_json_path = run_dir / "results.json"
    run_json_path.write_bytes(
        orjson.dumps(
            {
                "run_id": "2026-04-13_19-19-24",
                "models": ["provider/model-a"],
                "tests": ["sample-case"],
                "prompts": {"sample-case": "Generate a checkbox quiz."},
                "meta": {
                    "sampling": {"samples_per_case": 1},
                    "status": "EVALUATED",
                },
                "results": [
                    {
                        "test_name": "sample-case",
                        "model_name": "provider/model-a",
                        "timestamp": "2026-04-13T19:30:00Z",
                        "generation_html_path": "runs/2026-04-13_19-19-24/raw/sample-case/model-a.html",
                        "screenshot_path": None,
                        "test_function": {
                            "status": "fail",
                            "assertions": [
                                {
                                    "name": "Helper text is programmatically associated",
                                    "status": "fail",
                                    "type": "R",
                                    "message": 'checkbox group "1 . Which of the following are statically typed languages?" has helper text "Hint: These languages typically require you to declare the data type of a variable before using it." that is not programmatically associated',
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
                            "prompt_hash": "ghi",
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
                        "computed_at": "2026-04-13T19:30:02Z",
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

    html = (run_dir / "report_pages" / "details" / "sample-case.fragment.html").read_text(encoding="utf-8")
    assert 'Hint: These languages typically require you to declare the data type of a variable before using it.' in html
    assert 'class="assertion-message-list"' not in html
    assert '<div class="assertion-message-block">' not in html