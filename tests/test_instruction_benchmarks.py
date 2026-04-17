import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from a11y_llm_tests import generator
from a11y_llm_tests.cli import app


def test_instruction_benchmarks_variants(monkeypatch, tmp_path: Path):
    # Control stays on direct generation; instruction sets now always use the agent path.
    def fake_generate_html_with_meta(model, prompt, iteration, temperature=None, seed=None, disable_cache=False):
        html = (
            f"<html><body><h1>{model}</h1>"
            "<!-- variant:control -->"
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

    def fake_generate_html_with_agent_meta(
        model,
        prompt,
        iteration,
        temperature=None,
        seed=None,
        disable_cache=False,
        model_display_name=None,
        provider_config=None,
        runtime_log_dir=None,
        agent_config=None,
    ):
        eval_path = str(Path(runtime_log_dir) / f"{model}__concise.eval") if runtime_log_dir else None
        del iteration, temperature, seed, disable_cache, model_display_name, provider_config
        html = (
            f"<html><body><h1>{model}</h1>"
            "<!-- variant:concise -->"
            f"<p>{prompt}</p>"
            f"<p>{(agent_config or {}).get('sandbox')}</p>"
            "</body></html>"
        )
        return html, {
            "cached": False,
            "latency_s": 0.5,
            "prompt_hash": "agent-deadbeef",
            "tokens_in": 11,
            "tokens_out": 13,
            "total_tokens": 24,
            "cost_usd": 0.0105,
            "seed": None,
            "temperature": None,
            "generation_mode": "inspect_react_agent",
            "agent_sandbox": generator.format_agent_sandbox((agent_config or {}).get("sandbox") or ("docker", "default")),
            "agent_limits": (agent_config or {}).get("limits") or {},
            "agent_limit_error": None,
            "agent_eval_path": eval_path,
        }, {
            "format": "inspect_agent_conversation/v1",
            "messages": [
                {"role": "system", "content": "Produce accessible HTML."},
                {"role": "assistant", "content": "I will refine the variant in the sandbox."},
            ],
            "events": [],
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
    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_agent_meta", fake_generate_html_with_agent_meta)
    monkeypatch.setattr("a11y_llm_tests.node_bridge.run", fake_run)

    # Minimal test case
    tc_dir = tmp_path / "test_cases" / "sample-case"
    tc_dir.mkdir(parents=True)
    (tc_dir / "prompt.yaml").write_text("base_prompt: |\n  Generate a page\n", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")

    # Models config
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text("""models:\n  - name: test-model\n""", encoding="utf-8")
    (config_dir / "prompt_dimensions.yaml").write_text("dimensions: {}\n", encoding="utf-8")

    # Instruction sets
    instr_dir = config_dir / "instructions"
    instr_dir.mkdir()
    (instr_dir / "concise.md").write_text("VARIANT_ID=concise\n", encoding="utf-8")
    (config_dir / "instruction_sets.yaml").write_text(
        """instruction_sets:
  - id: concise
    name: Concise
    description: Prefer minimal HTML
    system_prompt_append_markdown: instructions/concise.md
    samples: 3
    agent:
            sandbox:
                - docker
                - test-sandbox
""",
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
            "--prompt-dimensions-file",
            str(config_dir / "prompt_dimensions.yaml"),
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
    conversation_files = sorted((latest / "raw_variants" / "concise" / "sample-case").glob("*.agent.json"))
    assert len(conversation_files) == 3

    # Verify results.json includes prompt_variants metadata
    pre_data = json.loads((latest / "results.json").read_text(encoding="utf-8"))
    pv = pre_data.get("meta", {}).get("prompt_variants")
    assert pv and any(x.get("id") == "control" for x in pv)
    assert any(x.get("id") == "concise" for x in pv)
    concise_variant = next(x for x in pv if x.get("id") == "concise")
    assert concise_variant["generation_mode"] == "inspect_react_agent"
    assert concise_variant["agent_sandbox"] == "docker:test-sandbox"

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
    concise_results = [r for r in data.get("results") if r.get("prompt_variant_id") == "concise"]
    assert concise_results
    assert all(r.get("generation_conversation_path", "").endswith(".agent.json") for r in concise_results)
    assert all(r.get("generation_eval_path", "").endswith(".eval") for r in concise_results)
    assert all((r.get("generation") or {}).get("generation_mode") == "inspect_react_agent" for r in concise_results)

    # Report includes the comparison section
    index_html = (latest / "index.html").read_text(encoding="utf-8")
    assert "Instruction Benchmarks (vs Control)" in index_html
    assert "Summary (ranked by avg WCAG pass rate)" in index_html
    assert "Concise" in index_html
    assert "Agent conversation" in index_html
    assert "Open raw conversation JSON" not in index_html
    # .eval may appear inside href links to Inspect logs, but raw eval
    # content must not leak into the report body.
    assert "Inspect log</a>" in index_html
    import re as _re
    _eval_outside_href = _re.sub(r'href="[^"]*\.eval"', '', index_html)
    assert ".eval" not in _eval_outside_href


def test_instruction_benchmark_agent_variant_persists_conversation(monkeypatch, tmp_path: Path):
    long_agent_note = (
        "I will inspect the files and draft the page. "
        "I will verify the fieldset structure, ensure the help text is connected to the first question, "
        "and keep the final document accessible and polished. END OF LONG NOTE"
    )

    def fake_generate_html_with_meta(model, prompt, iteration, temperature=None, seed=None, disable_cache=False):
        html = f"<html><body><h1>{model}</h1><!-- variant:control --></body></html>"
        return html, {
            "cached": False,
            "latency_s": 0.02,
            "prompt_hash": "control-hash",
            "tokens_in": 4,
            "tokens_out": 6,
            "total_tokens": 10,
            "cost_usd": 0.0002,
            "seed": seed,
            "temperature": temperature,
        }

    def fake_generate_html_with_agent_meta(
        model,
        prompt,
        iteration,
        temperature=None,
        seed=None,
        disable_cache=False,
        model_display_name=None,
        provider_config=None,
        runtime_log_dir=None,
        agent_config=None,
    ):
        eval_path = str(Path(runtime_log_dir) / f"{model}__agent.eval") if runtime_log_dir else None
        del temperature, seed, disable_cache, model_display_name, provider_config
        html = f"<html><body><h1>{model}</h1><!-- variant:agent --><p>{prompt}</p></body></html>"
        meta = {
            "cached": False,
            "latency_s": 1.25,
            "prompt_hash": "agent-hash",
            "tokens_in": 25,
            "tokens_out": 40,
            "total_tokens": 65,
            "cost_usd": 0.1234,
            "seed": None,
            "temperature": None,
            "generation_mode": "inspect_react_agent",
            "agent_sandbox": generator.format_agent_sandbox((agent_config or {}).get("sandbox")),
            "agent_limits": ((agent_config or {}).get("limits") or {}),
            "agent_limit_error": None,
            "agent_eval_path": eval_path,
        }
        transcript = {
            "format": "inspect_agent_conversation/v1",
            "messages": [
                {"role": "system", "content": "Follow accessibility instructions and produce HTML."},
                {"role": "user", "content": prompt},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "reasoning",
                            "summary": "Reviewing the prompt and planning the accessible quiz structure.",
                            "reasoning": "opaque-internal-reasoning",
                        }
                    ],
                },
                {"role": "assistant", "content": long_agent_note},
                {"role": "tool", "function": "bash", "content": "<!DOCTYPE html><html><body>generated page</body></html>"},
            ],
            "events": [
                {
                    "event": "tool",
                    "name": "text_editor",
                    "command": "create",
                    "path": "index.html",
                    "human_readable_result": "File created successfully at: /workspace/index.html",
                    "payload": {"raw": "very large technical payload"},
                }
            ],
            "output": {
                "completion": "<!DOCTYPE html><html><body>generated page</body></html>",
            },
        }
        return html, meta, transcript

    def fake_run(html, test_js_path, screenshot_path):
        status = "pass"
        return {
            "testFunctionResult": {
                "status": status,
                "assertions": [
                    {"name": "dummy", "status": status, "message": None, "type": "R"},
                ],
                "duration_ms": 5,
            },
            "axeResult": {
                "failure_count": 0,
                "failures": [],
                "best_practice_count": 0,
                "best_practice_failures": [],
            },
        }

    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_meta", fake_generate_html_with_meta)
    monkeypatch.setattr("a11y_llm_tests.generator.generate_html_with_agent_meta", fake_generate_html_with_agent_meta)
    monkeypatch.setattr("a11y_llm_tests.node_bridge.run", fake_run)

    tc_dir = tmp_path / "test_cases" / "sample-case"
    tc_dir.mkdir(parents=True)
    (tc_dir / "prompt.yaml").write_text("base_prompt: |\n  Generate an accessible page\n", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text("""models:\n  - name: test-model\n""", encoding="utf-8")
    (config_dir / "prompt_dimensions.yaml").write_text("dimensions: {}\n", encoding="utf-8")

    instr_dir = config_dir / "instructions"
    instr_dir.mkdir()
    (instr_dir / "agent.md").write_text("Use an agent to refine the page.\n", encoding="utf-8")
    (config_dir / "instruction_sets.yaml").write_text(
        """instruction_sets:
  - id: agentic
    name: Agentic
    description: Sandbox agent variant
    system_prompt_append_markdown: instructions/agent.md
    samples: 1
    agent:
      sandbox:
        - docker
        - test-sandbox
      limits:
        message_limit: 12
        token_limit: 3456
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    gen_res = runner.invoke(
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
            "--instruction-sets-file",
            str(config_dir / "instruction_sets.yaml"),
            "--processes",
            "1",
        ],
    )
    assert gen_res.exit_code == 0, gen_res.output

    latest = sorted(p for p in (tmp_path / "runs").iterdir() if p.is_dir())[-1]
    conversation_files = sorted((latest / "raw_variants" / "agentic" / "sample-case").glob("*.agent.json"))
    assert len(conversation_files) == 1
    conversation = json.loads(conversation_files[0].read_text(encoding="utf-8"))
    assert conversation["messages"][0]["role"] == "system"

    pre_data = json.loads((latest / "results.json").read_text(encoding="utf-8"))
    variants = {item["id"]: item for item in pre_data.get("meta", {}).get("prompt_variants", [])}
    assert variants["agentic"]["generation_mode"] == "inspect_react_agent"
    assert variants["agentic"]["agent_sandbox"] == "docker:test-sandbox"
    assert variants["agentic"]["agent_limits"]["message_limit"] == 12

    eval_res = runner.invoke(
        app,
        [
            "evaluate",
            str(latest),
            "--test-cases-dir",
            str(tmp_path / "test_cases"),
            "--k",
            "1",
            "--processes",
            "1",
        ],
    )
    assert eval_res.exit_code == 0, eval_res.output

    data = json.loads((latest / "results.json").read_text(encoding="utf-8"))
    agent_result = next(r for r in data["results"] if r.get("prompt_variant_id") == "agentic")
    assert agent_result["generation_conversation_path"].endswith(".agent.json")
    assert agent_result["generation_eval_path"].endswith(".eval")
    assert agent_result["generation"]["generation_mode"] == "inspect_react_agent"
    assert agent_result["generation"]["agent_sandbox"] == "docker:test-sandbox"
    assert agent_result["generation"]["agent_limits"]["token_limit"] == 3456

    index_html = (latest / "index.html").read_text(encoding="utf-8")
    assert "Agent conversation" in index_html
    assert "Open raw conversation JSON" not in index_html
    assert "Reviewing the prompt and planning the accessible quiz structure." in index_html
    assert long_agent_note in index_html
    assert "END OF LONG NOTE" in index_html
    assert "Used text_editor: create | index.html" in index_html
    assert "File created successfully at: /workspace/index.html" in index_html
    assert "Submitted final HTML document." in index_html
    assert "opaque-internal-reasoning" not in index_html
    assert "very large technical payload" not in index_html
    assert "generated page</body></html>" not in index_html
    # .eval may appear inside href links to Inspect logs, but raw eval
    # content must not leak into the report body.
    assert "Inspect log</a>" in index_html
    import re as _re
    _eval_outside_href = _re.sub(r'href="[^"]*\.eval"', '', index_html)
    assert ".eval" not in _eval_outside_href


def test_instruction_sets_reject_generation_mode_key(tmp_path: Path):
    tc_dir = tmp_path / "test_cases" / "sample-case"
    tc_dir.mkdir(parents=True)
    (tc_dir / "prompt.yaml").write_text("base_prompt: |\n  Generate a page\n", encoding="utf-8")
    (tc_dir / "test.js").write_text("module.exports=()=>{}", encoding="utf-8")

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text("""models:\n  - name: test-model\n""", encoding="utf-8")
    (config_dir / "prompt_dimensions.yaml").write_text("dimensions: {}\n", encoding="utf-8")
    instr_dir = config_dir / "instructions"
    instr_dir.mkdir()
    (instr_dir / "legacy.md").write_text("Legacy config\n", encoding="utf-8")
    (config_dir / "instruction_sets.yaml").write_text(
        """instruction_sets:
  - id: legacy
    name: Legacy
    system_prompt_append_markdown: instructions/legacy.md
    generation_mode: inspect_react_agent
""",
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
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
            "--instruction-sets-file",
            str(config_dir / "instruction_sets.yaml"),
            "--processes",
            "1",
        ],
    )

    assert result.exit_code == 1
    assert "cannot specify generation_mode" in result.output


def test_agent_cost_limit_is_opt_in_even_if_default_is_present():
    limits = generator.normalize_agent_limits({
        "message_limit": 12,
        "cost_limit": None,
    })

    assert limits["message_limit"] == 12
    assert "cost_limit" not in limits



def test_agent_cost_limit_is_preserved_when_explicitly_configured(monkeypatch):
    captured = {}

    def fake_run_agent_generation(**kwargs):
        captured.update(kwargs)
        return type("FakeAgentResult", (), {
            "html": "<html><body>ok</body></html>",
            "transcript": {"messages": [], "events": []},
            "usage": {},
            "elapsed_s": 0.1,
            "sandbox": kwargs["sandbox"],
            "limit_error": None,
            "eval_log_path": "/tmp/inspect/sample.eval",
        })()

    monkeypatch.setattr("a11y_llm_tests.generator.run_agent_generation", fake_run_agent_generation)

    _html, meta, _transcript = generator.generate_html_with_agent_meta(
        "test-model",
        "Build a page",
        iteration=0,
        agent_config={"limits": {"cost_limit": 1.25, "message_limit": 12}},
    )

    assert captured["agent_limits"]["cost_limit"] == 1.25
    assert meta["agent_limits"]["cost_limit"] == 1.25
    assert meta["agent_limits"]["message_limit"] == 12
    assert meta["agent_eval_path"] == "/tmp/inspect/sample.eval"


def test_default_agent_sandbox_uses_structured_inspect_spec(monkeypatch):
    captured = {}

    def fake_run_agent_generation(**kwargs):
        captured.update(kwargs)
        return type("FakeAgentResult", (), {
            "html": "<html><body>ok</body></html>",
            "transcript": {"messages": [], "events": []},
            "usage": {},
            "elapsed_s": 0.1,
            "sandbox": kwargs["sandbox"],
            "limit_error": None,
            "eval_log_path": None,
        })()

    monkeypatch.setattr("a11y_llm_tests.generator.run_agent_generation", fake_run_agent_generation)

    html, meta, transcript = generator.generate_html_with_agent_meta(
        "test-model",
        "Build a page",
        iteration=0,
        agent_config={},
    )

    assert html == "<html><body>ok</body></html>"
    assert transcript == {"messages": [], "events": []}
    assert captured["sandbox"][0] == "docker"
    assert captured["sandbox"][1].endswith("config/inspect_agent_sandbox/compose.yaml")
    assert meta["agent_sandbox"].startswith("docker:")
    assert "cost_limit" not in captured["agent_limits"]
    assert "cost_limit" not in meta["agent_limits"]
    assert meta["agent_eval_path"] is None


def test_agent_generation_uses_cache_across_runs(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Create a real .eval file so the cache can copy it
    fake_eval_file = tmp_path / "inspect_logs_orig" / "first-run.eval"
    fake_eval_file.parent.mkdir(parents=True, exist_ok=True)
    fake_eval_file.write_text('{"eval": "log"}', encoding="utf-8")

    calls = {"count": 0}

    def fake_run_agent_generation(**kwargs):
        calls["count"] += 1
        return type("FakeAgentResult", (), {
            "html": "<html><body><h1>cached agent page</h1></body></html>",
            "transcript": {
                "format": "inspect_agent_conversation/v1",
                "messages": [{"role": "assistant", "content": "Drafted page."}],
                "events": [],
            },
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 18,
                "total_tokens": 30,
                "total_cost": 0.42,
            },
            "elapsed_s": 0.2,
            "sandbox": kwargs["sandbox"],
            "limit_error": None,
            "eval_log_path": str(fake_eval_file),
        })()

    monkeypatch.setattr("a11y_llm_tests.generator.run_agent_generation", fake_run_agent_generation)

    html1, meta1, transcript1 = generator.generate_html_with_agent_meta(
        "test-model",
        "Build an accessible page",
        iteration=0,
        seed=123,
        runtime_log_dir=str(tmp_path / "inspect_logs_a"),
        agent_config={},
    )
    html2, meta2, transcript2 = generator.generate_html_with_agent_meta(
        "test-model",
        "Build an accessible page",
        iteration=0,
        seed=123,
        runtime_log_dir=str(tmp_path / "inspect_logs_b"),
        agent_config={},
    )

    assert calls["count"] == 1
    assert html1 == html2
    assert transcript1 == transcript2
    assert meta1["cached"] is False
    assert meta1["agent_eval_path"] == str(fake_eval_file)
    assert meta2["cached"] is True
    assert meta2["generation_mode"] == "inspect_react_agent"
    assert meta2["agent_sandbox"] == meta1["agent_sandbox"]
    assert meta2["agent_limit_error"] == meta1["agent_limit_error"]
    assert meta2["agent_limits"] == meta1["agent_limits"]
    # Cached run should restore the .eval file into the new run's inspect_logs dir
    assert meta2["agent_eval_path"] is not None
    assert Path(meta2["agent_eval_path"]).exists()
    assert str(tmp_path / "inspect_logs_b") in meta2["agent_eval_path"]
    assert meta2["tokens_in"] == 12
    assert meta2["tokens_out"] == 18
    assert meta2["total_tokens"] == 30
    assert meta2["cost_usd"] == 0.42


def test_agent_cache_does_not_invalidate_direct_cache(monkeypatch, tmp_path: Path):
    """Agent and direct generation use different cache files so loading an
    agent entry that misses the transcript sidecar never deletes a valid
    direct-generation cache entry."""
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    html = "<html><body><h1>direct cached page</h1></body></html>"

    _, direct_cache, direct_meta = generator._cache_artifacts(
        "test-model", "Build an accessible page", 0, None
    )
    _, agent_cache, agent_meta = generator._cache_artifacts(
        "test-model", "Build an accessible page", 0, None, generation_mode="agent"
    )
    # The two cache files must be different paths
    assert direct_cache != agent_cache

    # Seed the direct cache
    direct_cache.write_text(html, encoding="utf-8")
    direct_meta.write_text(json.dumps({"cached": True}), encoding="utf-8")

    # Agent cache miss should NOT touch the direct cache files
    assert not agent_cache.exists()
    assert direct_cache.exists()
    assert direct_meta.exists()


def test_cached_agent_transcript_is_repaired_when_it_contains_truncated_submit_preview(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    html = "<html><body><h1>cached agent page</h1></body></html>"
    truncated = (
        "The output of your call to submit was too long to be displayed.\n"
        "Here is a truncated version:\n<START_TOOL_OUTPUT>"
    )
    prompt_hash_value, cache_file, meta_file = generator._cache_artifacts(
        "test-model", "Build an accessible page", 0, 123, generation_mode="agent"
    )
    transcript_file = cache_file.with_suffix(cache_file.suffix + ".agent.json")

    cache_file.write_text(html, encoding="utf-8")
    meta_file.write_text(
        json.dumps({
            "generation_mode": "inspect_react_agent",
            "tokens_in": 12,
            "tokens_out": 18,
            "total_tokens": 30,
            "cost_usd": 0.42,
        }),
        encoding="utf-8",
    )
    transcript_file.write_text(
        json.dumps({
            "format": "inspect_agent_conversation/v1",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "draft commentary"},
                        {"type": "text", "text": truncated},
                    ],
                }
            ],
            "output": {"completion": truncated},
            "events": [],
        }),
        encoding="utf-8",
    )

    html_loaded, meta, transcript = generator.generate_html_with_agent_meta(
        "test-model",
        "Build an accessible page",
        iteration=0,
        seed=123,
        agent_config={},
    )

    assert prompt_hash_value
    assert html_loaded == html
    assert meta["cached"] is True
    assert transcript["output"]["completion"] == html
    assert transcript["messages"][0]["content"][1]["text"] == html


def test_cached_agent_html_is_repaired_from_submit_answer_when_html_file_is_corrupted(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    broken_html = "<html><head><style>.x{filter: blur(0, and lifestyle text</style></head><body><h1>bad</h1></body></html>"
    good_html = "<html><head><title>ok</title></head><body><h1>cached agent page</h1></body></html>"
    _prompt_hash_value, cache_file, meta_file = generator._cache_artifacts(
        "test-model", "Build an accessible page", 0, 123, generation_mode="agent"
    )
    transcript_file = cache_file.with_suffix(cache_file.suffix + ".agent.json")

    cache_file.write_text(broken_html, encoding="utf-8")
    meta_file.write_text(
        json.dumps({"generation_mode": "inspect_react_agent"}),
        encoding="utf-8",
    )
    transcript_file.write_text(
        json.dumps({
            "format": "inspect_agent_conversation/v1",
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "function": "submit",
                            "arguments": {"answer": good_html},
                        }
                    ],
                    "content": [
                        {"type": "text", "text": "commentary"},
                        {"type": "text", "text": "The output of your call to submit was too long to be displayed."},
                    ],
                }
            ],
            "output": {"completion": "The output of your call to submit was too long to be displayed."},
            "events": [],
        }),
        encoding="utf-8",
    )

    html_loaded, meta, transcript = generator.generate_html_with_agent_meta(
        "test-model",
        "Build an accessible page",
        iteration=0,
        seed=123,
        agent_config={},
    )

    assert meta["cached"] is True
    assert html_loaded == good_html
    assert cache_file.read_text(encoding="utf-8") == good_html
    assert transcript["output"]["completion"] == good_html


def test_agent_generation_retries_once_on_incomplete_html_and_caches_repaired_output(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    calls = {"count": 0}
    bad_html = "<html><head><title>bad</title></head><div>missing body</div></html>"
    good_html = "<html><head><title>ok</title></head><body><h1>cached agent page</h1></body></html>"

    def fake_run_agent_generation(**kwargs):
        calls["count"] += 1
        html = bad_html if calls["count"] == 1 else good_html
        transcript = {
            "format": "inspect_agent_conversation/v1",
            "messages": [{"role": "assistant", "content": f"attempt {calls['count']}"}],
            "events": [],
        }
        return type("FakeAgentResult", (), {
            "html": html,
            "transcript": transcript,
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 18,
                "total_tokens": 30,
                "total_cost": 0.42,
            },
            "elapsed_s": 0.2,
            "sandbox": kwargs["sandbox"],
            "limit_error": None,
            "eval_log_path": f"/tmp/inspect/attempt-{calls['count']}.eval",
        })()

    monkeypatch.setattr("a11y_llm_tests.generator.run_agent_generation", fake_run_agent_generation)

    html1, meta1, transcript1 = generator.generate_html_with_agent_meta(
        "test-model",
        "Build an accessible page",
        iteration=0,
        agent_config={},
    )
    html2, meta2, transcript2 = generator.generate_html_with_agent_meta(
        "test-model",
        "Build an accessible page",
        iteration=0,
        agent_config={},
    )

    assert calls["count"] == 2
    assert html1 == good_html
    assert meta1["cached"] is False
    assert meta1["agent_eval_path"] == "/tmp/inspect/attempt-2.eval"
    assert transcript1["messages"][0]["content"] == "attempt 2"
    assert html2 == good_html
    assert meta2["cached"] is True
    assert meta2["agent_eval_path"] is None
    assert transcript2 == transcript1


def test_agent_generation_does_not_cache_persistently_incomplete_html(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    calls = {"count": 0}
    bad_html = "<html><head><title>bad</title></head><div>missing body</div></html>"

    def fake_run_agent_generation(**kwargs):
        calls["count"] += 1
        return type("FakeAgentResult", (), {
            "html": bad_html,
            "transcript": {
                "format": "inspect_agent_conversation/v1",
                "messages": [{"role": "assistant", "content": f"attempt {calls['count']}"}],
                "events": [],
            },
            "usage": {},
            "elapsed_s": 0.2,
            "sandbox": kwargs["sandbox"],
            "limit_error": None,
            "eval_log_path": None,
        })()

    monkeypatch.setattr("a11y_llm_tests.generator.run_agent_generation", fake_run_agent_generation)

    html1, meta1, transcript1 = generator.generate_html_with_agent_meta(
        "test-model",
        "Build an accessible page",
        iteration=0,
        agent_config={},
    )
    html2, meta2, transcript2 = generator.generate_html_with_agent_meta(
        "test-model",
        "Build an accessible page",
        iteration=0,
        agent_config={},
    )

    h, cache_file, _meta_file = generator._cache_artifacts("test-model", "Build an accessible page", 0, None, generation_mode="agent")

    assert h
    assert calls["count"] == 4
    assert meta1["cached"] is False
    assert meta2["cached"] is False
    assert html1 == bad_html
    assert html2 == bad_html
    assert transcript1["messages"][0]["content"] == "attempt 2"
    assert transcript2["messages"][0]["content"] == "attempt 4"
    assert not cache_file.exists()
    assert not cache_file.with_suffix(cache_file.suffix + ".meta.json").exists()
    assert not cache_file.with_suffix(cache_file.suffix + ".agent.json").exists()


def test_agent_generation_prefers_transcript_submit_html_over_corrupted_result_html(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(generator, "CACHE_DIR", tmp_path / "generations")
    generator.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    good_html = (
        "<!DOCTYPE html>\n"
        "<html><head><title>ok</title></head><body><h1>canonical agent page</h1></body></html>"
    )
    bad_html = (
        "<!DOCTYPE html>\n"
        "<html><head><title>ok</title><style>.product-n></style></head>"
        "<body><h1>corrupted agent page</h1></body></html>"
    )

    def fake_run_agent_generation(**kwargs):
        transcript = {
            "format": "inspect_agent_conversation/v1",
            "messages": [
                {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "commentary"},
                    ],
                }
            ],
            "events": [
                {
                    "event": "tool",
                    "function": "submit",
                    "arguments": {"answer": good_html},
                }
            ],
            "output": {
                "completion": (
                    "The output of your call to submit was too long to be displayed.\n"
                    "Here is a truncated version:\n<START_TOOL_OUTPUT>"
                ),
            },
        }
        return type("FakeAgentResult", (), {
            "html": bad_html,
            "transcript": transcript,
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 18,
                "total_tokens": 30,
                "total_cost": 0.42,
            },
            "elapsed_s": 0.2,
            "sandbox": kwargs["sandbox"],
            "limit_error": None,
            "eval_log_path": "/tmp/inspect/canonical.eval",
        })()

    monkeypatch.setattr("a11y_llm_tests.generator.run_agent_generation", fake_run_agent_generation)

    html, meta, transcript = generator.generate_html_with_agent_meta(
        "test-model",
        "Build an accessible page",
        iteration=0,
        agent_config={},
    )

    _, cache_file, _meta_file = generator._cache_artifacts("test-model", "Build an accessible page", 0, None, generation_mode="agent")

    assert meta["cached"] is False
    assert html == good_html
    assert ".product-n>" not in html
    assert transcript["output"]["completion"] == good_html
    assert cache_file.read_text(encoding="utf-8") == good_html
