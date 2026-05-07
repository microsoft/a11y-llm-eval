"""Typer CLI for running evaluations and generating reports."""
import asyncio
import hashlib
import json
import multiprocessing
import shutil
import threading
from datetime import datetime
from pathlib import Path
import typer
import yaml
from typing import Any, Dict, List, Tuple

from . import generator, node_bridge
from .model_config import get_model_provider, load_models_config, normalize_models_config
from .prompt_specs import load_prompt_specs
from .schema import (
    ResultRecord,
    TestFunctionResult,
    AxeResult,
    GenerationMeta,
    AggregateRecord,
    PromptCase,
    PromptVariant,
)
from .metrics import compute_pass_at_k, format_pass_at_k
from .utils import atomic_write_text

# importing os module for environment variables
import os
# importing necessary functions from dotenv library
from dotenv import load_dotenv
# loading variables from .env file
load_dotenv() 

app = typer.Typer(add_completion=False)

# Tracks the last rendered progress tuple per prefix so we can dedupe updates
# and avoid re-printing the same percent twice.  Keyed by the prefix string.
_PROGRESS_LAST: Dict[str, Tuple[int, int, int]] = {}
_WORKSPACE_VIEWS_DIRNAME = ".copilot_workspaces"
_WORKSPACE_INSTRUCTIONS_REL_PATH = Path(".github") / "copilot-instructions.md"


def _wait_for_serve_interrupt() -> None:
    while True:
        threading.Event().wait(86400)


def _render_progress(prefix: str, done: int, total: int) -> None:
    """Render a progress indicator.

    Prints a new line each time percent or done/total changes.  We intentionally
    avoid the ``\\r``-overwrite trick: the Copilot SDK and tool subprocesses
    write their own lines to stdout/stderr during a run, which would push an in-place progress line up and leave visible gaps.  A
    deduped newline-per-change approach stays readable when interleaved and
    bounds total output to ~100 lines regardless of ``total``.
    """
    if total <= 0:
        return
    done = max(0, min(done, total))
    pct = int((done / total) * 100)
    last = _PROGRESS_LAST.get(prefix)
    # Only emit when the visible state changes (percent, done, or total).  The
    # final update (done == total) is always emitted so callers see completion.
    if last == (pct, done, total) and done < total:
        return
    _PROGRESS_LAST[prefix] = (pct, done, total)
    typer.echo(f"{prefix}: {pct}% ({done}/{total})")
    if done >= total:
        # Reset so a subsequent phase with the same prefix starts clean.
        _PROGRESS_LAST.pop(prefix, None)


def _print_generation_summary(results: List[Dict[str, Any]], gen_tasks: List[Dict[str, Any]]) -> None:
    """Echo a post-run summary highlighting errors, limit hits, and cache stats.

    ``results`` is the in-memory list of ResultRecord dicts accumulated during
    generation; ``gen_tasks`` is the list of planned tasks.  The summary is
    advisory only and must not alter any artifact on disk.
    """
    total_planned = len(gen_tasks)
    total_produced = len(results)
    cached = 0
    live = 0
    agent_limit_hits: List[Tuple[str, str, str]] = []  # (variant, model, limit_error)
    for r in results:
        gen = r.get("generation") or {}
        if gen.get("cached"):
            cached += 1
        else:
            live += 1
        lim = gen.get("agent_limit_error")
        if lim:
            agent_limit_hits.append(
                (
                    str(r.get("prompt_variant_id") or "control"),
                    str(r.get("model_name") or "?"),
                    str(lim),
                )
            )

    typer.echo("")
    typer.secho("Run summary", fg=typer.colors.CYAN, bold=True)
    typer.echo(f"  Samples produced: {total_produced} (planned: {total_planned})")
    typer.echo(f"  Cache hits: {cached} | Fresh generations: {live}")

    if agent_limit_hits:
        typer.secho(
            f"  Agent limits hit: {len(agent_limit_hits)}",
            fg=typer.colors.YELLOW,
            bold=True,
        )
        # Group by (variant, model, limit_error) for a concise view.
        from collections import Counter

        grouped = Counter(agent_limit_hits)
        for (variant, model, lim), count in grouped.most_common():
            typer.secho(
                f"    - {count}x {variant} / {model}: {lim}",
                fg=typer.colors.YELLOW,
            )
    else:
        typer.echo("  Agent limits hit: 0")

    missing = total_planned - total_produced
    if missing > 0:
        typer.secho(
            f"  Missing samples: {missing} (tasks planned but no result recorded)",
            fg=typer.colors.RED,
            bold=True,
        )


def _evaluate_worker(args_tuple):
    """Top-level worker; runs synchronously and is dispatched via asyncio.to_thread."""
    html_path = args_tuple["html_path"]
    test_js_path = args_tuple["test_js_path"]
    screenshot_path = args_tuple["screenshot_path"]
    test_name = args_tuple["test_name"]
    base_test_name = args_tuple.get("base_test_name")
    prompt_case_id = args_tuple.get("prompt_case_id")
    prompt_dimensions = args_tuple.get("prompt_dimensions") or []
    model = args_tuple["model"]
    sample_index = args_tuple["sample_index"]
    gen_meta = args_tuple.get("gen_meta") or {}
    prompt_text = args_tuple.get("prompt_text") or ""
    prompt_variant_id = args_tuple.get("prompt_variant_id")
    prompt_variant_kind = args_tuple.get("prompt_variant_kind")
    turn_id = args_tuple.get("turn_id")
    turn_index = args_tuple.get("turn_index")
    turn_count_total = args_tuple.get("turn_count_total")
    generation_conversation_path = args_tuple.get("generation_conversation_path")
    generation_eval_path = args_tuple.get("generation_eval_path")
    html = Path(html_path).read_text(encoding="utf-8")
    sp = Path(screenshot_path)
    sp.parent.mkdir(parents=True, exist_ok=True)
    # Pass the directory containing the HTML so the runner can serve relative
    # CSS/JS references over a localhost HTTP URL.
    html_dir = str(Path(html_path).parent)
    node_res = node_bridge.run(html, test_js_path, screenshot_path, html_dir=html_dir)
    tf = node_res.get("testFunctionResult", {})
    assertions_raw = tf.get("assertions", [])
    norm_assertions = []
    for a in assertions_raw:
        if not isinstance(a, dict):
            continue
        atype = (a.get("type") or "R").upper()
        if atype not in {"R", "BP"}:
            atype = "R"
        status = str(a.get("status", "fail") or "fail").lower()
        if status in {"n/a", "not_applicable", "not-applicable", "not applicable"}:
            status = "na"
        if status not in {"pass", "fail", "na"}:
            status = "fail"
        norm_assertions.append({
            "name": a.get("name", "unknown"),
            "status": status,
            "message": a.get("message"),
            "type": atype,
        })
    total_assertion_na = tf.get("total_assertion_na")
    if total_assertion_na is None:
        total_assertion_na = sum(1 for a in norm_assertions if a["type"] == "R" and a["status"] == "na")
    total_assertion_bp_na = tf.get("total_assertion_bp_na")
    if total_assertion_bp_na is None:
        total_assertion_bp_na = sum(1 for a in norm_assertions if a["type"] == "BP" and a["status"] == "na")
    test_result = TestFunctionResult(
        status=tf.get("status", "error"),
        assertions=norm_assertions,
        error=tf.get("error"),
        duration_ms=tf.get("duration_ms"),
        total_assertion_failures=tf.get("total_assertion_failures", 0),
        total_assertion_bp_failures=tf.get("total_assertion_bp_failures", 0),
        total_assertion_na=total_assertion_na,
        total_assertion_bp_na=total_assertion_bp_na,
    )
    axe_data = node_res.get("axeResult") or node_res.get("axe_result") or node_res.get("axe")
    axe_obj = None
    if axe_data and isinstance(axe_data, dict):
        axe_obj = AxeResult(
            failure_count=axe_data.get("failure_count", 0),
            failures=axe_data.get("failures", []),
            best_practice_count=axe_data.get("best_practice_count", 0),
            best_practice_failures=axe_data.get("best_practice_failures", []),
        )
    result_pass = bool(axe_obj) and (test_result.status == "pass" and axe_obj.failure_count == 0)
    rec = ResultRecord(
        test_name=test_name,
        base_test_name=base_test_name,
        prompt_case_id=prompt_case_id,
        prompt_dimensions=prompt_dimensions,
        model_name=model,
        timestamp=datetime.utcnow(),
        generation_html_path=html_path,
        generation_conversation_path=generation_conversation_path,
        generation_eval_path=generation_eval_path,
        screenshot_path=screenshot_path,
        test_function=test_result,
        axe=axe_obj,
        result="PASS" if result_pass else "FAIL",
        generation=GenerationMeta(
            latency_s=gen_meta.get("latency_s", 0.0),
            prompt_hash=gen_meta.get("prompt_hash", generator.compute_prompt_hash(prompt_text)),
            cached=gen_meta.get("cached", False),
            tokens_in=gen_meta.get("tokens_in"),
            tokens_out=gen_meta.get("tokens_out"),
            total_tokens=gen_meta.get("total_tokens"),
            cost_usd=gen_meta.get("cost_usd"),
            seed=gen_meta.get("seed"),
            temperature=gen_meta.get("temperature"),
            output_format_instructions=gen_meta.get(
                "output_format_instructions",
                generator.get_base_output_format_instructions(),
            ),
            custom_instructions=gen_meta.get("custom_instructions", generator.get_custom_instructions()),
            effective_output_format_instructions=gen_meta.get(
                "effective_output_format_instructions",
                generator.get_effective_output_format_instructions(),
            ),
            generation_mode=gen_meta.get("generation_mode"),
            agent_sandbox=gen_meta.get("agent_sandbox"),
            agent_limit_error=gen_meta.get("agent_limit_error"),
            agent_limits=gen_meta.get("agent_limits"),
            browser_smoke=gen_meta.get("browser_smoke"),
        ),
        sample_index=sample_index,
        prompt_variant_id=prompt_variant_id,
        prompt_variant_kind=prompt_variant_kind,
        turn_id=turn_id,
        turn_index=turn_index,
        turn_count_total=turn_count_total,
    )
    return json.loads(rec.model_dump_json())


def _copy_sandbox_siblings(sandbox_workdir: str | None, dest_dir: Path) -> None:
    """Copy non-HTML files from the agent sandbox into *dest_dir*.

    This lets the runner resolve relative ``<link>`` / ``<script>`` references
    when loading ``index.html`` via ``file://``.  ``index.html`` itself is NOT
    copied — the harness writes it separately from the canonical HTML string.
    """
    if not sandbox_workdir:
        return
    src = Path(sandbox_workdir)
    if not src.is_dir():
        return
    for item in src.iterdir():
        # Skip index.html (the harness writes its own canonical copy) and any
        # hidden directories (.github, etc.) that were placed for SDK config.
        if item.name == "index.html" or item.name.startswith("."):
            continue
        dest = dest_dir / item.name
        try:
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        except OSError:
            pass  # best-effort; don't fail the run


def _generate_worker(task):
    """Generation worker. Runs synchronously inside a thread for asyncio.gather."""
    test_name = task["test_name"]
    base_test_name = task["base_test_name"]
    prompt_case_id = task["prompt_case_id"]
    prompt_dimensions = task.get("prompt_dimensions") or []
    model = task["model"]
    sample_index = task["sample_index"]
    prompt_text = task["prompt_text"]
    seed = task.get("seed")
    temperature = task.get("temperature")
    disable_cache = task.get("disable_cache", False)
    output_format_override = task.get("output_format_override")
    custom_instructions_text = task.get("custom_instructions_text")
    prompt_variant_id = task.get("prompt_variant_id")
    prompt_variant_kind = task.get("prompt_variant_kind")
    html_out_path = task.get("html_out_path")
    conversation_out_path = task.get("conversation_out_path")
    model_display_name = task.get("model_display_name")
    provider_config = task.get("provider_config")
    runtime_log_dir = task.get("runtime_log_dir")
    sandbox_workdir = task.get("sandbox_workdir")
    workspace_dir = task.get("workspace_dir")
    container_identity_dir = task.get("container_identity_dir")
    agent_config = task.get("agent_config") or {}

    # Resolve per-task prompt config. Passed explicitly to generation
    # functions so concurrent workers don't race on module globals.
    resolved_output_format = output_format_override or generator.DEFAULT_OUTPUT_FORMAT_INSTRUCTIONS
    resolved_custom_instructions = custom_instructions_text  # may be None
    generator.configure_runtime(runtime_log_dir)

    # Skill variants: multi-turn. Emit one record per turn.
    if prompt_variant_kind == "skill":
        skill_config = task["skill_config"]
        html_out_path_stub = task["html_out_path_stub"]
        turn_records, aggregate_conversation = generator.generate_html_with_skill_multi_turn(
            model,
            prompt_text,
            sample_index,
            temperature=temperature,
            seed=seed,
            disable_cache=disable_cache,
            model_display_name=model_display_name,
            provider_config=provider_config,
            runtime_log_dir=runtime_log_dir,
            agent_config=agent_config,
            skill_config=skill_config,
            sandbox_workdir=sandbox_workdir,
            workspace_dir=workspace_dir,
            container_identity_dir=container_identity_dir,
            output_format_instructions=resolved_output_format,
            custom_instructions_override=resolved_custom_instructions,
        )

        conversation_path = None
        if conversation_out_path:
            conversation_target = Path(conversation_out_path)
            conversation_target.parent.mkdir(exist_ok=True, parents=True)
            atomic_write_text(conversation_target, json.dumps(aggregate_conversation, indent=2), encoding="utf-8")
            conversation_path = str(conversation_target)

        skill_turn_records = []
        total_turns = len(turn_records)
        for tr in turn_records:
            t_idx = tr["turn_index"]
            # Each turn gets its own subdirectory so sibling files from
            # different samples/turns never collide.
            turn_dir = Path(f"{html_out_path_stub}__t{t_idx}")
            turn_dir.mkdir(exist_ok=True, parents=True)
            html_path = turn_dir / "index.html"
            atomic_write_text(html_path, tr["html"] or "", encoding="utf-8")
            _copy_sandbox_siblings(sandbox_workdir, turn_dir)
            meta = tr.get("meta") or {}
            skill_turn_records.append({
                "test_name": test_name,
                "base_test_name": base_test_name,
                "prompt_case_id": prompt_case_id,
                "prompt_dimensions": prompt_dimensions,
                "model": model,
                "sample_index": sample_index,
                "prompt_text": prompt_text,
                "meta": meta,
                "html_path": str(html_path),
                "conversation_path": conversation_path,
                "eval_path": meta.get("agent_session_log_path"),
                "prompt_variant_id": prompt_variant_id,
                "prompt_variant_kind": "skill",
                "turn_id": tr["turn_id"],
                "turn_index": t_idx,
                "turn_count_total": total_turns,
                "turn_error": tr.get("error"),
            })
        return {"skill_turn_records": skill_turn_records}

    html, meta, conversation_payload = generator.generate_html_with_agent_meta(
        model,
        prompt_text,
        sample_index,
        temperature=temperature,
        seed=seed,
        disable_cache=disable_cache,
        model_display_name=model_display_name,
        provider_config=provider_config,
        runtime_log_dir=runtime_log_dir,
        agent_config=agent_config,
        sandbox_workdir=sandbox_workdir,
        workspace_dir=workspace_dir,
        container_identity_dir=container_identity_dir,
        output_format_instructions=resolved_output_format,
        custom_instructions_override=resolved_custom_instructions,
    )

    out_path = Path(html_out_path)
    out_path.parent.mkdir(exist_ok=True, parents=True)
    atomic_write_text(out_path, html, encoding="utf-8")

    # Copy any sibling files the agent created in the sandbox (CSS, JS, images)
    # into the same directory as the output HTML so relative references resolve
    # when the runner loads the page via file://.
    _copy_sandbox_siblings(sandbox_workdir, out_path.parent)

    conversation_path = None
    if conversation_payload is not None and conversation_out_path:
        conversation_target = Path(conversation_out_path)
        conversation_target.parent.mkdir(exist_ok=True, parents=True)
        atomic_write_text(conversation_target, json.dumps(conversation_payload, indent=2), encoding="utf-8")
        conversation_path = str(conversation_target)

    return {
        "test_name": test_name,
        "base_test_name": base_test_name,
        "prompt_case_id": prompt_case_id,
        "prompt_dimensions": prompt_dimensions,
        "model": model,
        "sample_index": sample_index,
        "prompt_text": prompt_text,
        "meta": meta,
        "html_path": str(out_path),
        "conversation_path": conversation_path,
        "eval_path": meta.get("agent_session_log_path"),
        "prompt_variant_id": prompt_variant_id,
        "prompt_variant_kind": prompt_variant_kind,
    }


def _default_screenshot_path(
    run_dir: Path,
    prompt_case_id: str | None,
    test_name: str,
    model: str,
    sample_index: int | None,
    prompt_variant_id: str,
    *,
    prompt_variant_kind: str | None = None,
    turn_index: int | None = None,
) -> Path:
    file_stem = prompt_case_id or test_name
    turn_suffix = f"__t{turn_index}" if turn_index is not None else ""
    if sample_index is not None:
        file_name = f"{file_stem}__{model}__s{sample_index}{turn_suffix}.png"
    else:
        file_name = f"{file_stem}__{model}{turn_suffix}.png"
    if prompt_variant_kind == "skill" or (turn_index is not None and prompt_variant_id not in {None, "control"}):
        return run_dir / "screenshots_skills" / prompt_variant_id / file_name
    if prompt_variant_id == "control":
        return run_dir / "screenshots" / file_name
    return run_dir / "screenshots_variants" / prompt_variant_id / file_name


def _legacy_prompt_map(test_cases_dir: Path) -> dict[str, str]:
    prompts_map = {}
    for test_dir in sorted(p for p in test_cases_dir.iterdir() if p.is_dir()):
        prompt_file = test_dir / "prompt.md"
        if prompt_file.exists():
            prompts_map[test_dir.name] = prompt_file.read_text(encoding="utf-8")
    return prompts_map


def _write_workspace_instructions(workspace_root: Path, instructions_text: str) -> Path:
    target = workspace_root / _WORKSPACE_INSTRUCTIONS_REL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, instructions_text.rstrip("\n") + "\n", encoding="utf-8")
    return target


def _workspace_relative_path(path_value: str, source_root: Path) -> Path:
    resolved = Path(path_value).expanduser().resolve()
    try:
        return resolved.relative_to(source_root.resolve())
    except ValueError as exc:
        raise RuntimeError(
            f"Path {resolved} is outside the workspace source {source_root.resolve()}"
        ) from exc


def _prepare_variant_workspace(source_root: Path, run_dir: Path, variant: dict) -> dict:
    workspace_root = run_dir / _WORKSPACE_VIEWS_DIRNAME / variant["id"]
    workspace_root.mkdir(parents=True, exist_ok=True)

    installed_skill_path = None
    if variant.get("custom_instructions_text"):
        _write_workspace_instructions(workspace_root, variant["custom_instructions_text"])

    if variant.get("kind") == "skill":
        rel_skill_path = _workspace_relative_path(variant["skill_dir_abs_path"], source_root)
        installed_skill_path = workspace_root / rel_skill_path
        shutil.copytree(variant["skill_dir_abs_path"], installed_skill_path, dirs_exist_ok=True)

    return {
        "workspace_root": workspace_root,
        "sandbox_root": workspace_root / "sandbox",
        "skill_dir_workspace_path": installed_skill_path,
    }


def _resolve_cli_path(path_value: str, base_dir: Path) -> Path:
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate

    workspace_candidate = Path.cwd() / candidate
    if workspace_candidate.exists():
        return workspace_candidate

    return base_dir / candidate


def _load_instruction_sets(instruction_sets_file: str, base_dir: Path) -> list[dict]:
    """Load instruction sets YAML.

    Expected format:
      instruction_sets:
        - id: concise
          name: Concise
          description: ...
          url: https://example.com/full-instructions
          instructions_markdown: path/to/file.md
          samples: 10

    The legacy key ``system_prompt_append_markdown`` is still accepted as an
    alias for ``instructions_markdown`` for back-compat with older configs.
    """
    path = Path(instruction_sets_file)
    if not path.is_absolute():
        cwd_path = path.resolve()
        if cwd_path.exists():
            path = cwd_path
        else:
            path = (base_dir / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Instruction sets file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sets = data.get("instruction_sets") or []
    if not isinstance(sets, list):
        raise ValueError("instruction_sets must be a list")
    out = []
    for s in sets:
        if not isinstance(s, dict):
            continue
        sid = (s.get("id") or "").strip()
        if not sid:
            raise ValueError("Each instruction set must include a non-empty 'id'")
        if sid.lower() == "control":
            raise ValueError("'control' is reserved; choose a different instruction set id")
        if "generation_mode" in s:
            raise ValueError(
                f"Instruction set '{sid}' cannot specify generation_mode; instruction sets always use the copilot_agent path"
            )
        md_path = s.get("instructions_markdown") or s.get("system_prompt_append_markdown")
        if not md_path:
            raise ValueError(f"Instruction set '{sid}' must include instructions_markdown")
        mdp = Path(md_path)
        if not mdp.is_absolute():
            mdp = (base_dir / mdp).resolve()
        if not mdp.exists():
            raise FileNotFoundError(f"Instruction markdown not found for '{sid}': {mdp}")
        out.append({
            "id": sid,
            "name": (s.get("name") or sid).strip(),
            "description": (s.get("description") or "").strip() or None,
            "url": (s.get("url") or "").strip() or None,
            "markdown_path": str(mdp),
            "markdown_text": mdp.read_text(encoding="utf-8"),
            "samples": s.get("samples"),
            "generation_mode": "copilot_agent",
            "agent": s.get("agent") if isinstance(s.get("agent"), dict) else {},
        })
    return out


# Exactly one turn per skill must reference this token. Earlier turns that produce
# HTML the evaluator will score must embed the user's test case prompt.
SKILL_TOKEN_TEST_CASE_PROMPT = "{{test_case_prompt}}"


def _hash_skill_files(skill_dir: Path) -> str:
    """Compute a stable digest over every file under the skill directory."""
    sha = hashlib.sha256()
    for rel in sorted(p.relative_to(skill_dir).as_posix() for p in skill_dir.rglob("*") if p.is_file()):
        sha.update(rel.encode("utf-8"))
        sha.update(b"\0")
        sha.update((skill_dir / rel).read_bytes())
        sha.update(b"\0")
    return sha.hexdigest()[:16]


def _merge_agent_timeout(agent_config: dict, cli_timeout: int | None) -> dict:
    """Merge the CLI --agent-timeout into an agent_config dict.

    The CLI value acts as a fallback: it is only applied when the YAML does
    not already specify ``agent.limits.timeout_s``.  Returns a (shallow-)
    copied dict so callers don't mutate the variant's original data.
    """
    if cli_timeout is None:
        return agent_config
    cfg = dict(agent_config)
    limits = dict(cfg.get("limits") or {})
    if "timeout_s" not in limits:
        limits["timeout_s"] = cli_timeout
        cfg["limits"] = limits
    return cfg


def _load_skills(skills_file: str, base_dir: Path, existing_ids: set[str] | None = None) -> list[dict]:
    """Load a skills YAML file.

    Expected format::

        skills:
          - id: a11y-reviewer
            name: Accessibility Reviewer
            description: ...
            url: https://example.com/full-skill
            skill_dir: skills/a11y-reviewer   # relative to base_dir or absolute
            samples: 10                       # optional
            agent:                            # optional; same shape as instruction sets
              sandbox: [docker, path/to/compose.yaml]
              limits: {...}
            turns:
              - id: generate
                name: Generate
                prompt: "{{test_case_prompt}}"
              - id: review
                name: Review & remediate
                prompt: "Review using {{skill_path}}/SKILL.md ..."
    """
    reserved = set(existing_ids or set())
    path = Path(skills_file)
    if not path.is_absolute():
        cwd_path = path.resolve()
        if cwd_path.exists():
            path = cwd_path
        else:
            path = (base_dir / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Skills file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("skills") or []
    if not isinstance(raw, list):
        raise ValueError("skills must be a list")
    out: list[dict] = []
    seen_ids: set[str] = set()
    for s in raw:
        if not isinstance(s, dict):
            continue
        sid = (s.get("id") or "").strip()
        if not sid:
            raise ValueError("Each skill must include a non-empty 'id'")
        if sid.lower() == "control":
            raise ValueError("'control' is reserved; choose a different skill id")
        if sid in seen_ids or sid in reserved:
            raise ValueError(f"Duplicate variant id '{sid}' (skills and instruction sets share a namespace)")
        seen_ids.add(sid)
        if "generation_mode" in s:
            raise ValueError(
                f"Skill '{sid}' cannot specify generation_mode; skills always use the copilot_agent path"
            )
        skill_dir_raw = s.get("skill_dir")
        if not skill_dir_raw:
            raise ValueError(f"Skill '{sid}' must include skill_dir")
        sdp = Path(skill_dir_raw)
        if not sdp.is_absolute():
            sdp = (base_dir / sdp).resolve()
        if not sdp.exists() or not sdp.is_dir():
            raise FileNotFoundError(f"Skill directory not found for '{sid}': {sdp}")
        if not (sdp / "SKILL.md").exists():
            raise FileNotFoundError(f"Skill '{sid}' is missing SKILL.md at {sdp / 'SKILL.md'}")

        turns_raw = s.get("turns")
        if not isinstance(turns_raw, list) or not turns_raw:
            raise ValueError(f"Skill '{sid}' must include a non-empty 'turns' list")
        turns: list[dict] = []
        turn_ids: set[str] = set()
        test_case_token_count = 0
        for i, t in enumerate(turns_raw):
            if not isinstance(t, dict):
                raise ValueError(f"Skill '{sid}' turn #{i} must be a mapping")
            tid = (t.get("id") or "").strip()
            if not tid:
                raise ValueError(f"Skill '{sid}' turn #{i} must include a non-empty 'id'")
            if tid in turn_ids:
                raise ValueError(f"Skill '{sid}' has duplicate turn id '{tid}'")
            turn_ids.add(tid)
            prompt_tmpl = t.get("prompt")
            if not isinstance(prompt_tmpl, str) or not prompt_tmpl.strip():
                raise ValueError(f"Skill '{sid}' turn '{tid}' must include a non-empty 'prompt'")
            if SKILL_TOKEN_TEST_CASE_PROMPT in prompt_tmpl:
                test_case_token_count += 1
            turns.append({
                "id": tid,
                "name": (t.get("name") or tid).strip(),
                "prompt": prompt_tmpl,
            })
        if test_case_token_count != 1:
            raise ValueError(
                f"Skill '{sid}' must reference {SKILL_TOKEN_TEST_CASE_PROMPT} in exactly one turn "
                f"(found {test_case_token_count})."
            )

        name = (s.get("name") or sid).strip()
        files_hash = _hash_skill_files(sdp)
        out.append({
            "id": sid,
            "name": name,
            "description": (s.get("description") or "").strip() or None,
            "url": (s.get("url") or "").strip() or None,
            "skill_dir_abs_path": str(sdp),
            "skill_files_hash": files_hash,
            "turns": turns,
            "samples": s.get("samples"),
            "generation_mode": "copilot_agent",
            "agent": s.get("agent") if isinstance(s.get("agent"), dict) else {},
        })
    return out


@app.command()
def run(
    models_file: str = typer.Option("config/models.yaml", help="Models config YAML"),
    prompt_dimensions_file: str = typer.Option("config/prompt_dimensions.yaml", help="Global prompt dimensions config YAML."),
    out: str = typer.Option("runs", help="Output directory"),
    samples: int = typer.Option(1, min=1, help="Number of samples per (test,model)."),
    k: str = typer.Option("1,5,10", help="Comma-separated k values for pass@k metrics (stored for later evaluation)."),
    base_seed: int = typer.Option(None, help="Base seed for reproducibility; each sample adds its index."),
    temperature: float = typer.Option(None, help="Override model temperature (if supported)."),
    disable_cache: bool = typer.Option(False, help="Disable generation cache (always re-generate)."),
    instruction_sets_file: str = typer.Option(None, help="Optional YAML defining custom instruction sets to benchmark vs control."),
    instruction_samples: int = typer.Option(None, min=1, help="Default samples per instruction set (if not specified in instruction sets file)."),
    skills_file: str = typer.Option(None, help="Optional YAML defining skills (multi-turn sandbox-mounted packages) to benchmark vs control."),
    skills_samples: int = typer.Option(None, min=1, help="Default samples per skill (if not specified in the skills file)."),
    test_cases_dir: str = typer.Option("test_cases", help="Directory containing test case folders."),
    test_cases: str = typer.Option(None, "--test-cases", help="Comma-separated base test case names to include (e.g. single-checkbox,modal-dialog). Defaults to all."),
    concurrency: int = typer.Option(None, "--concurrency", "-c", help="Maximum number of concurrent Copilot sessions for generation (defaults to 4)."),
    processes: int = typer.Option(None, "--processes", "-p", hidden=True, help="Deprecated: use --concurrency instead."),
    keep_sandbox: bool = typer.Option(
        False,
        "--keep-sandbox",
        help="Preserve per-sample agent sandbox directories under <run_dir>/sandbox/. By default the sandbox tree is deleted after generation since the only artifact the harness needs (index.html) has already been copied to <run_dir>/raw[_variants|_skills]/.",
    ),
    agent_timeout: int = typer.Option(
        None,
        "--agent-timeout",
        help="Per-session agent timeout in seconds. Overrides the default (600s) for all variants. Per-variant agent.limits.timeout_s in YAML takes precedence.",
    ),
):
    """Generate HTML samples ONLY (no evaluation). A later 'evaluate' command will run tests & build report."""
    if processes is not None:
        typer.secho(
            "Warning: --processes/-p is deprecated; use --concurrency/-c instead.",
            fg=typer.colors.YELLOW, err=True,
        )
        if concurrency is None:
            concurrency = processes
    # Fail fast if Docker is not installed — the Copilot sandbox container
    # is a hard dependency for all generation paths.
    if not shutil.which("docker"):
        typer.secho(
            "Error: Docker is required but not found on PATH. Install Docker Desktop "
            "(or Docker Engine + Compose v2) before running.",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=1)

    run_id = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    out_dir = Path(out) / run_id
    (out_dir / "raw").mkdir(parents=True, exist_ok=True)
    # Prepare screenshots directory (will be populated during evaluation phase)
    (out_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    copilot_logs_dir = out_dir / "copilot_logs"
    copilot_logs_dir.mkdir(parents=True, exist_ok=True)
    sandbox_root = out_dir / "sandbox"
    sandbox_root.mkdir(parents=True, exist_ok=True)
    source_workspace_root = Path(os.environ.get("COPILOT_WORKSPACE") or os.getcwd()).expanduser().resolve()

    models_cfg, models_file_path = load_models_config(models_file)
    normalized_models = normalize_models_config(models_cfg)
    defaults_cfg = normalized_models["defaults"]
    config_dir = models_file_path.parent
    # Accept both the new ``defaults.output_format_instructions`` key and the
    # legacy ``defaults.system_prompt`` key as an alias.
    output_format_override = (
        defaults_cfg.get("output_format_instructions")
        or defaults_cfg.get("system_prompt")
    )

    # Temperature precedence:
    # 1) CLI --temperature
    # 2) config/models.yaml defaults.temperature
    # 3) otherwise omit temperature (provider/model default)
    config_temperature = defaults_cfg.get("temperature")
    effective_temperature = temperature
    if effective_temperature is None and config_temperature is not None:
        try:
            effective_temperature = float(config_temperature)
        except Exception:
            typer.secho(f"Invalid defaults.temperature in models config: {config_temperature}", err=True)
            raise typer.Exit(code=1)

    # Control behavior:
    # - When benchmarking instruction sets or skills, control must be the base system
    #   prompt with no custom instructions.
    # - Otherwise, keep existing behavior (defaults.custom_instructions_markdown applies).
    instructions_cfg = defaults_cfg.get("custom_instructions_markdown")
    custom_instructions_text = None
    custom_instructions_path = None
    variants_active = bool(instruction_sets_file) or bool(skills_file)
    if not variants_active and instructions_cfg:
        instructions_path = Path(instructions_cfg)
        if not instructions_path.is_absolute():
            instructions_path = config_dir / instructions_path
        instructions_path = instructions_path.resolve()
        if not instructions_path.exists():
            typer.secho(f"Custom instructions file not found: {instructions_path}", err=True)
            raise typer.Exit(code=1)
        try:
            custom_instructions_text = instructions_path.read_text(encoding="utf-8")
        except OSError as exc:
            typer.secho(f"Failed to read custom instructions file '{instructions_path}': {exc}", err=True)
            raise typer.Exit(code=1)
        custom_instructions_path = str(instructions_path)
    generator.configure_prompts(output_format_override, custom_instructions_text)
    # Capture prompting meta *now* before any worker mutates module state.
    base_prompting_output_format_instructions = generator.get_base_output_format_instructions()
    base_prompting_effective_output_format_instructions = generator.get_effective_output_format_instructions()
    base_prompting_custom_instructions = generator.get_custom_instructions()
    model_names = normalized_models["model_names"]
    model_display_lookup = normalized_models["model_display_lookup"]
    model_provider_lookup = normalized_models["model_provider_lookup"]
    models_info = normalized_models["models_info"]
    tcd = Path(test_cases_dir)
    test_case_filter = [name.strip() for name in test_cases.split(",") if name.strip()] if test_cases else None
    prompt_dimensions_path = _resolve_cli_path(prompt_dimensions_file, config_dir)
    try:
        prompt_spec_set = load_prompt_specs(tcd, prompt_dimensions_path.resolve(), test_case_filter=test_case_filter)
    except Exception as exc:
        typer.secho(f"Failed to load prompt specs: {exc}", err=True)
        raise typer.Exit(code=1)

    test_dirs = prompt_spec_set.test_dirs
    prompt_cases = prompt_spec_set.prompt_cases
    prompts_map = prompt_spec_set.prompts_map

    # Prompt variants: always include control
    prompt_variants: list[dict] = []
    prompt_variants.append({
        "id": "control",
        "name": "Control",
        "description": "Base system prompt; no custom instructions" if variants_active else "Base prompt configuration",
        "custom_instructions_path": (None if variants_active else custom_instructions_path),
        "custom_instructions_text": (None if variants_active else custom_instructions_text),
        "n_samples_requested": samples,
        "generation_mode": "copilot_agent",
        "agent": {},
        "kind": "control",
    })

    if instruction_sets_file:
        try:
            sets = _load_instruction_sets(instruction_sets_file, config_dir)
        except Exception as exc:
            typer.secho(f"Failed to load instruction sets: {exc}", err=True)
            raise typer.Exit(code=1)
        for s in sets:
            n = s.get("samples")
            if n is None:
                n = instruction_samples if instruction_samples is not None else samples
            try:
                n_int = int(n)
            except Exception:
                typer.secho(f"Invalid samples for instruction set '{s.get('id')}': {n}", err=True)
                raise typer.Exit(code=1)
            if n_int < 1:
                typer.secho(f"Invalid samples for instruction set '{s.get('id')}': {n_int}", err=True)
                raise typer.Exit(code=1)
            prompt_variants.append({
                "id": s["id"],
                "name": s.get("name") or s["id"],
                "description": s.get("description"),
                "url": s.get("url"),
                "custom_instructions_path": s.get("markdown_path"),
                "custom_instructions_text": s.get("markdown_text"),
                "n_samples_requested": n_int,
                "generation_mode": "copilot_agent",
                "agent": s.get("agent") or {},
                "kind": "instruction_set",
            })

    if skills_file:
        existing_ids = {v["id"] for v in prompt_variants}
        try:
            skills = _load_skills(skills_file, config_dir, existing_ids=existing_ids)
        except Exception as exc:
            typer.secho(f"Failed to load skills: {exc}", err=True)
            raise typer.Exit(code=1)
        for sk in skills:
            n = sk.get("samples")
            if n is None:
                n = skills_samples if skills_samples is not None else samples
            try:
                n_int = int(n)
            except Exception:
                typer.secho(f"Invalid samples for skill '{sk.get('id')}': {n}", err=True)
                raise typer.Exit(code=1)
            if n_int < 1:
                typer.secho(f"Invalid samples for skill '{sk.get('id')}': {n_int}", err=True)
                raise typer.Exit(code=1)
            prompt_variants.append({
                "id": sk["id"],
                "name": sk.get("name") or sk["id"],
                "description": sk.get("description"),
                "url": sk.get("url"),
                # Skills no longer inject a system-prompt preamble: the SDK
                # exposes the skill directory directly via skill_directories
                # and the model auto-loads its SKILL.md.
                "custom_instructions_path": None,
                "custom_instructions_text": None,
                "n_samples_requested": n_int,
                "generation_mode": "copilot_agent",
                "agent": sk.get("agent") or {},
                "kind": "skill",
                "skill_id": sk["id"],
                "skill_dir_abs_path": sk["skill_dir_abs_path"],
                "skill_files_hash": sk["skill_files_hash"],
                "turns": sk["turns"],
            })

    typer.echo("Preparing isolated Copilot workspaces...")
    workspace_views: dict[str, dict] = {}
    try:
        try:
            for variant in prompt_variants:
                workspace_views[variant["id"]] = _prepare_variant_workspace(
                    source_workspace_root,
                    out_dir,
                    variant,
                )
        except (OSError, RuntimeError) as exc:
            typer.secho(f"Failed to prepare isolated Copilot workspaces: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        for variant in prompt_variants:
            view = workspace_views[variant["id"]]
            variant["workspace_root"] = str(view["workspace_root"])
            if view.get("skill_dir_workspace_path") is not None:
                variant["skill_dir_runtime_path"] = str(view["skill_dir_workspace_path"])
        typer.echo(f"Prepared {len(workspace_views)} isolated Copilot workspace(s).")

        # Pre-flight: bring up each sandbox container and ensure the Copilot CLI
        # inside it is authenticated. Workspaces are variant-scoped so control and
        # each variant see only the files installed for that view.
        from .copilot_runtime import preflight_default_runtime_sync
        typer.echo("Preparing Copilot sandboxes...")
        try:
            for variant_id, view in workspace_views.items():
                preflight_default_runtime_sync(
                    log_dir=str(copilot_logs_dir),
                    workspace_dir=str(view["workspace_root"]),
                    container_identity_dir=str(view["workspace_root"]),
                    reset=True,
                )
        except RuntimeError as exc:
            typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1)
        typer.echo("Sandboxes ready.")
        # Build generation tasks
        results = []  # stub pending evaluation records
        # Round-robin task queues per model to avoid hammering a single LLM
        tasks_by_model = {model: [] for model in model_names}
        for prompt_case in prompt_cases:
            for model in model_names:
                for variant in prompt_variants:
                    n_samples = int(variant.get("n_samples_requested") or samples)
                    for sample_index in range(n_samples):
                        seed = (base_seed + sample_index) if base_seed is not None else None
                        variant_id = variant.get("id") or "control"
                        variant_kind = variant.get("kind") or ("control" if variant_id == "control" else "instruction_set")
                        workspace_view = workspace_views[variant_id]
                        workspace_sandbox_root = workspace_view["sandbox_root"]

                        if variant_kind == "skill":
                            raw_path = out_dir / "raw_skills" / variant_id / prompt_case.prompt_case_id
                            # Each turn is a subdirectory: <stub>__t<N>/index.html
                            html_file_stub = raw_path / f"{model}__s{sample_index}"
                            conversation_file = raw_path / f"{model}__s{sample_index}.agent.json"
                            # Per-sample workdir under <run_dir>/sandbox/. The agent
                            # writes its final HTML to <workdir>/index.html; the
                            # harness reads that file back. Unique per task so
                            # parallel sessions never collide on the shared
                            # /workspace mount.
                            sandbox_workdir = (
                                workspace_sandbox_root
                                / "skills"
                                / variant_id
                                / prompt_case.prompt_case_id
                                / f"{model}__s{sample_index}"
                            )
                            tasks_by_model[model].append({
                                "test_name": prompt_case.test_name,
                                "base_test_name": prompt_case.base_test_name,
                                "prompt_case_id": prompt_case.prompt_case_id,
                                "prompt_dimensions": prompt_case.prompt_dimensions,
                                "model": model,
                                "sample_index": sample_index,
                                "prompt_text": prompt_case.prompt_text,
                                "seed": seed,
                                "temperature": effective_temperature,
                                "disable_cache": disable_cache,
                                "output_format_override": output_format_override,
                                "custom_instructions_text": variant.get("custom_instructions_text"),
                                "prompt_variant_id": variant_id,
                                "prompt_variant_kind": "skill",
                                "html_out_path_stub": str(html_file_stub),
                                "conversation_out_path": str(conversation_file),
                                "model_display_name": model_display_lookup.get(model),
                                "runtime_log_dir": str(copilot_logs_dir),
                                "sandbox_workdir": str(sandbox_workdir),
                                "workspace_dir": str(workspace_view["workspace_root"]),
                                "container_identity_dir": str(workspace_view["workspace_root"]),
                                "provider_config": model_provider_lookup.get(model),
                                "agent_config": _merge_agent_timeout(variant.get("agent") or {}, agent_timeout),
                                "skill_config": {
                                    "id": variant["skill_id"],
                                    "skill_dir_abs_path": variant["skill_dir_runtime_path"],
                                    "skill_files_hash": variant["skill_files_hash"],
                                    "turns": variant["turns"],
                                },
                            })
                            continue

                        if variant_id == "control":
                            raw_path = out_dir / "raw" / prompt_case.prompt_case_id
                            # Each sample is a subdirectory: <stem>/index.html
                            stem = f"{model}__s{sample_index}" if n_samples > 1 else model
                            html_file = raw_path / stem / "index.html"
                            # Control is now an agentic Copilot session like the
                            # other variants, so persist its conversation
                            # transcript next to the HTML for the detailed report.
                            conversation_file = raw_path / (
                                f"{model}__s{sample_index}.agent.json"
                                if n_samples > 1
                                else f"{model}.agent.json"
                            )
                            sandbox_workdir = (
                                workspace_sandbox_root
                                / "control"
                                / prompt_case.prompt_case_id
                                / f"{model}__s{sample_index}"
                            )
                        else:
                            raw_path = out_dir / "raw_variants" / variant_id / prompt_case.prompt_case_id
                            html_file = raw_path / f"{model}__s{sample_index}" / "index.html"
                            conversation_file = raw_path / f"{model}__s{sample_index}.agent.json"
                            sandbox_workdir = (
                                workspace_sandbox_root
                                / "variants"
                                / variant_id
                                / prompt_case.prompt_case_id
                                / f"{model}__s{sample_index}"
                            )

                        tasks_by_model[model].append({
                            "test_name": prompt_case.test_name,
                            "base_test_name": prompt_case.base_test_name,
                            "prompt_case_id": prompt_case.prompt_case_id,
                            "prompt_dimensions": prompt_case.prompt_dimensions,
                            "model": model,
                            "sample_index": sample_index,
                            "prompt_text": prompt_case.prompt_text,
                            "seed": seed,
                            "temperature": effective_temperature,
                            "disable_cache": disable_cache,
                            "output_format_override": output_format_override,
                            "custom_instructions_text": variant.get("custom_instructions_text"),
                            "prompt_variant_id": variant_id,
                            "prompt_variant_kind": variant_kind,
                            "html_out_path": str(html_file),
                            "conversation_out_path": (str(conversation_file) if conversation_file is not None else None),
                            "model_display_name": model_display_lookup.get(model),
                            "runtime_log_dir": str(copilot_logs_dir),
                            "sandbox_workdir": str(sandbox_workdir),
                            "workspace_dir": str(workspace_view["workspace_root"]),
                            "container_identity_dir": str(workspace_view["workspace_root"]),
                            "provider_config": model_provider_lookup.get(model),
                            "agent_config": _merge_agent_timeout(variant.get("agent") or {}, agent_timeout),
                        })

        # Flatten into a single task list using round-robin across models
        gen_tasks = []
        made_progress = True
        while made_progress:
            made_progress = False
            for model in model_names:
                queue = tasks_by_model.get(model)
                if queue:
                    gen_tasks.append(queue.pop(0))
                    made_progress = True

        if gen_tasks:
            # All generations are now Copilot agent sessions. Concurrency caps the
            # number of in-flight sessions on the shared CopilotClient.
            if concurrency is None:
                concurrency_limit = min(4, len(gen_tasks))
            else:
                concurrency_limit = max(1, concurrency)

            def _append_result_record(gen_result: dict):
                test_name = gen_result["test_name"]
                base_test_name = gen_result.get("base_test_name")
                prompt_case_id = gen_result.get("prompt_case_id")
                prompt_dimensions = gen_result.get("prompt_dimensions") or []
                model = gen_result["model"]
                sample_index = gen_result["sample_index"]
                prompt_text = gen_result["prompt_text"]
                meta = gen_result.get("meta") or {}
                html_path = gen_result["html_path"]
                conversation_path = gen_result.get("conversation_path")
                eval_path = gen_result.get("eval_path")
                prompt_variant_id = gen_result.get("prompt_variant_id")
                prompt_variant_kind = gen_result.get("prompt_variant_kind")

                variant_id = prompt_variant_id or "control"

                rec = ResultRecord(
                    test_name=test_name,
                    base_test_name=base_test_name,
                    prompt_case_id=prompt_case_id,
                    prompt_dimensions=prompt_dimensions,
                    model_name=model,
                    timestamp=datetime.utcnow(),
                    generation_html_path=str(html_path),
                    generation_conversation_path=conversation_path,
                    generation_eval_path=eval_path,
                    screenshot_path=None,
                    test_function=TestFunctionResult(status="PENDING", assertions=[], error=None, duration_ms=None),
                    axe=None,
                    result="PENDING",
                    generation=GenerationMeta(
                        latency_s=meta.get("latency_s", 0.0),
                        prompt_hash=meta.get("prompt_hash", generator.compute_prompt_hash(prompt_text)),
                        cached=meta.get("cached", False),
                        tokens_in=meta.get("tokens_in"),
                        tokens_out=meta.get("tokens_out"),
                        total_tokens=meta.get("total_tokens"),
                        cost_usd=meta.get("cost_usd"),
                        seed=meta.get("seed"),
                        temperature=meta.get("temperature"),
                        output_format_instructions=meta.get(
                            "output_format_instructions",
                            generator.get_base_output_format_instructions(),
                        ),
                        custom_instructions=meta.get("custom_instructions", generator.get_custom_instructions()),
                        effective_output_format_instructions=meta.get(
                            "effective_output_format_instructions",
                            generator.get_effective_output_format_instructions(),
                        ),
                        generation_mode=meta.get("generation_mode"),
                        agent_sandbox=meta.get("agent_sandbox"),
                        agent_limit_error=meta.get("agent_limit_error"),
                        agent_limits=meta.get("agent_limits"),
                        browser_smoke=meta.get("browser_smoke"),
                    ),
                    sample_index=sample_index,
                    prompt_variant_id=variant_id,
                    prompt_variant_kind=prompt_variant_kind,
                    turn_id=gen_result.get("turn_id"),
                    turn_index=gen_result.get("turn_index"),
                    turn_count_total=gen_result.get("turn_count_total"),
                )
                results.append(json.loads(rec.model_dump_json()))

            async def _run_generations() -> None:
                from concurrent.futures import ThreadPoolExecutor
                # Set an explicit thread pool sized to the concurrency limit + headroom.
                # This prevents deadlocks: each worker blocks its thread waiting for the
                # Copilot runtime loop, so we need at least concurrency_limit threads.
                loop = asyncio.get_running_loop()
                loop.set_default_executor(ThreadPoolExecutor(max_workers=concurrency_limit + 4))

                sem = asyncio.Semaphore(concurrency_limit)
                total = len(gen_tasks)
                done = 0
                limit_errors: list[str] = []
                _render_progress("Generating", done, total)
                lock = asyncio.Lock()

                async def _runner(task: dict):
                    nonlocal done
                    # Run the synchronous worker in a thread so multiple sessions
                    # can be in flight against the shared Copilot client.
                    async with sem:
                        gen_result = await asyncio.to_thread(_generate_worker, task)
                    async with lock:
                        done += 1
                        _render_progress("Generating", done, total)
                        if isinstance(gen_result, dict) and "skill_turn_records" in gen_result:
                            for tr in gen_result["skill_turn_records"]:
                                _append_result_record(tr)
                                tr_meta = tr.get("meta") or {}
                                if tr_meta.get("agent_limit_error"):
                                    limit_errors.append(
                                        f"  {tr.get('test_name','?')} / {tr.get('model','?')} s{tr.get('sample_index',0)}: "
                                        f"{tr_meta['agent_limit_error']}"
                                    )
                        else:
                            _append_result_record(gen_result)
                            r_meta = (gen_result.get("meta") or {})
                            if r_meta.get("agent_limit_error"):
                                limit_errors.append(
                                    f"  {gen_result.get('test_name','?')} / {gen_result.get('model','?')} "
                                    f"s{gen_result.get('sample_index',0)}: {r_meta['agent_limit_error']}"
                                )

                await asyncio.gather(*[_runner(task) for task in gen_tasks])
                return limit_errors

            typer.echo(f"Generating with concurrency={concurrency_limit}...")
            generation_limit_errors = asyncio.run(_run_generations())
            if generation_limit_errors:
                typer.echo("")
                typer.secho(
                    f"Warning: {len(generation_limit_errors)} generation(s) hit agent limits:",
                    fg=typer.colors.YELLOW, err=True,
                )
                for msg in generation_limit_errors:
                    typer.echo(msg, err=True)

        run_json = {
            "run_id": run_id,
            "models": model_names,
            "tests": [pc.test_name for pc in prompt_cases],
            "prompts": prompts_map,
            "results": results,
            "aggregates": [],  # will be populated after evaluation
            "meta": {
                "sampling": {
                    "samples_per_case": samples,
                    "k_values": [int(x.strip()) for x in k.split(",") if x.strip().isdigit()],  # stored but not yet computed
                    "temperature": effective_temperature,
                    "base_seed": base_seed,
                    "disable_cache": disable_cache,
                    "concurrency_generation": (concurrency if concurrency is not None else (min(4, len(gen_tasks)) if gen_tasks else None)),
                    "prompt_dimensions_file": str(prompt_dimensions_path.resolve()),
                },
                "prompting": {
                    "output_format_instructions": base_prompting_output_format_instructions,
                    "effective_output_format_instructions": base_prompting_effective_output_format_instructions,
                    "custom_instructions": base_prompting_custom_instructions,
                    "custom_instructions_path": custom_instructions_path,
                },
                "prompt_variants": [json.loads(PromptVariant(
                    id=v.get("id") or "control",
                    name=v.get("name"),
                    description=v.get("description"),
                    url=v.get("url"),
                    custom_instructions_path=v.get("custom_instructions_path"),
                    n_samples_requested=v.get("n_samples_requested"),
                    generation_mode=v.get("generation_mode"),
                    agent_sandbox=generator.format_agent_sandbox((v.get("agent") or {}).get("sandbox")),
                    agent_limits=(v.get("agent") or {}).get("limits"),
                    kind=v.get("kind") or ("control" if (v.get("id") or "control") == "control" else "instruction_set"),
                    skill_path=v.get("skill_dir_abs_path"),
                    turns=v.get("turns"),
                ).model_dump_json()) for v in prompt_variants],
                "prompt_cases": [json.loads(PromptCase(
                    id=pc["id"],
                    test_name=pc["test_name"],
                    base_test_name=pc["base_test_name"],
                    prompt_dimensions=pc.get("prompt_dimensions") or [],
                ).model_dump_json()) for pc in prompt_spec_set.prompt_cases_meta],
                "models_info": models_info,
                "runtime": {
                    "engine": "copilot_sdk",
                    "log_dir": str(copilot_logs_dir.resolve()),
                    "models_config_path": str(models_file_path),
                },
                "status": "GENERATED_ONLY",
            },
        }
        (out_dir / "results.json").write_text(json.dumps(run_json, indent=2), encoding="utf-8")
        latest_link = Path(out) / "latest"
        try:
            if latest_link.exists() or latest_link.is_symlink():
                latest_link.unlink()
            latest_link.symlink_to(out_dir)
        except OSError:
            pass  # Symlink creation may fail on Windows without Developer Mode
        if keep_sandbox:
            for view in workspace_views.values():
                workspace_sandbox_root = view["sandbox_root"]
                if not workspace_sandbox_root.exists():
                    continue
                try:
                    shutil.copytree(workspace_sandbox_root, sandbox_root, dirs_exist_ok=True)
                except OSError as exc:
                    typer.echo(f"Warning: failed to preserve sandbox dir {sandbox_root}: {exc}", err=True)
                    break
    finally:
        if workspace_views:
            from .copilot_runtime import cleanup_default_runtime_sync
            cleanup_errors: list[str] = []
            for view in workspace_views.values():
                try:
                    cleanup_default_runtime_sync(
                        workspace_dir=str(view["workspace_root"]),
                        container_identity_dir=str(view["workspace_root"]),
                    )
                except RuntimeError as exc:
                    cleanup_errors.append(str(exc))

            workspaces_root = out_dir / _WORKSPACE_VIEWS_DIRNAME
            if workspaces_root.exists():
                try:
                    shutil.rmtree(workspaces_root)
                except OSError as exc:
                    typer.echo(
                        f"Warning: failed to remove isolated workspace dir {workspaces_root}: {exc}",
                        err=True,
                    )

            if cleanup_errors:
                typer.echo(
                    f"Warning: failed to clean up {len(cleanup_errors)} Copilot sandbox(s).",
                    err=True,
                )
                for msg in cleanup_errors:
                    typer.echo(msg, err=True)
    # Clean up per-sample sandbox dirs unless explicitly preserved. The agent
    # may have created node_modules/ or other auxiliary files; the only
    # artifact the harness needs (index.html) has already been copied into
    # <run_dir>/raw[_variants|_skills]/. Skipping this cleanup with
    # --keep-sandbox is useful when debugging tool use.
    if not keep_sandbox and sandbox_root.exists():
        try:
            shutil.rmtree(sandbox_root)
        except OSError as exc:
            typer.echo(f"Warning: failed to remove sandbox dir {sandbox_root}: {exc}", err=True)
    _print_generation_summary(results, gen_tasks)
    typer.echo(f"Generation complete. Run directory ready for evaluation: {out_dir}")


@app.command()
def evaluate(
    run_dir: str = typer.Argument(..., help="Existing run directory produced by 'run' command"),
    test_cases_dir: str = typer.Option("test_cases", help="Directory containing test case folders."),
    test_cases: str = typer.Option(None, "--test-cases", help="Comma-separated base test case names to evaluate (e.g. single-checkbox,modal-dialog). Defaults to all."),
    k: str = typer.Option("1,5,10", help="Comma-separated k values for pass@k metrics."),
    generate_report: bool = typer.Option(True, help="Generate HTML report (index.html) after evaluation."),
    report_include_generated_html_samples: bool = typer.Option(
        True,
        "--report-include-generated-html-samples/--report-exclude-generated-html-samples",
        help="Include direct links to generated HTML samples in the HTML report.",
    ),
    processes: int = typer.Option(None, "--processes", "-p", help="Number of parallel processes for evaluation (defaults to CPU count; use 1 to disable)."),
):
    """Evaluate previously generated HTML samples without requiring models config: run accessibility tests, compute aggregates, optionally render report."""
    rd = Path(run_dir)
    if not rd.exists():
        typer.secho(f"Run directory not found: {rd}", err=True)
        raise typer.Exit(code=1)
    results_json_path = rd / "results.json"
    prior_data = {}
    if results_json_path.exists():
        try:
            prior_data = json.loads(results_json_path.read_text(encoding="utf-8"))
        except Exception:
            typer.secho("Warning: Failed to parse existing results.json; proceeding without prior metadata.", err=True)
    # derive model list and display names from prior data
    model_names = prior_data.get("models") or []
    meta_block = (prior_data.get("meta") or {})
    stored_models_info = meta_block.get("models_info") or []
    display_lookup = {m.get("name"): m.get("display_name") for m in stored_models_info if m.get("name")}
    tcd = Path(test_cases_dir)
    prompts_map = prior_data.get("prompts") or _legacy_prompt_map(tcd)
    k_values = [int(x.strip()) for x in k.split(",") if x.strip().isdigit()]
    if not k_values:
        k_values = [1]

    # Map generation meta by (prompt_case_id or test_name, model, sample_index, variant, turn_id) for reuse
    gen_meta_map = {}
    for r in prior_data.get("results", []) if prior_data else []:
        variant_id = r.get("prompt_variant_id") or "control"
        key = (
            r.get("prompt_case_id") or r.get("test_name"),
            r.get("model_name"),
            r.get("sample_index"),
            variant_id,
            r.get("turn_id"),
        )
        gen_meta_map[key] = r.get("generation")

    # Build evaluation task list
    tasks = []
    test_case_filter = set(name.strip() for name in test_cases.split(",") if name.strip()) if test_cases else None
    test_js_lookup = {
        p.name: p / "test.js"
        for p in sorted(tcd.iterdir())
        if p.is_dir() and (p / "test.js").exists()
    }

    prior_results = prior_data.get("results") or []
    if prior_results:
        for result in prior_results:
            html_path = result.get("generation_html_path")
            if not html_path:
                continue
            base_test_name = result.get("base_test_name") or result.get("test_name")
            if test_case_filter and base_test_name not in test_case_filter:
                continue
            test_js = test_js_lookup.get(base_test_name)
            if test_js is None:
                typer.secho(f"Skipping missing test.js for base test '{base_test_name}'", err=True)
                continue
            test_name = result.get("test_name") or base_test_name
            prompt_case_id = result.get("prompt_case_id") or test_name
            prompt_variant_id = result.get("prompt_variant_id") or "control"
            prompt_variant_kind = result.get("prompt_variant_kind")
            turn_id = result.get("turn_id")
            turn_index = result.get("turn_index")
            turn_count_total = result.get("turn_count_total")
            model = result.get("model_name")
            sample_index = result.get("sample_index")
            screenshot_path = result.get("screenshot_path") or str(_default_screenshot_path(
                rd,
                prompt_case_id,
                test_name,
                model,
                sample_index,
                prompt_variant_id,
                prompt_variant_kind=prompt_variant_kind,
                turn_index=turn_index,
            ))
            gen_meta = gen_meta_map.get((prompt_case_id, model, sample_index, prompt_variant_id, turn_id)) or (result.get("generation") or {})
            if sample_index is None and not gen_meta:
                gen_meta = gen_meta_map.get((prompt_case_id, model, 0, prompt_variant_id, turn_id)) or {}
            tasks.append({
                "html_path": str(html_path),
                "test_js_path": str(test_js),
                "screenshot_path": str(screenshot_path),
                "generation_conversation_path": result.get("generation_conversation_path"),
                "generation_eval_path": result.get("generation_eval_path"),
                "test_name": test_name,
                "base_test_name": base_test_name,
                "prompt_case_id": prompt_case_id,
                "prompt_dimensions": result.get("prompt_dimensions") or [],
                "model": model,
                "sample_index": sample_index,
                "gen_meta": gen_meta,
                "prompt_text": prompts_map.get(test_name, ""),
                "prompt_variant_id": prompt_variant_id,
                "prompt_variant_kind": prompt_variant_kind,
                "turn_id": turn_id,
                "turn_index": turn_index,
                "turn_count_total": turn_count_total,
            })
    else:
        typer.secho("No prior generation records found in results.json; falling back to legacy directory scan.", err=True)
        for base_test_name, test_js in test_js_lookup.items():
            if test_case_filter and base_test_name not in test_case_filter:
                continue
            raw_dir = rd / "raw" / base_test_name
            if not raw_dir.exists():
                continue
            for hf in sorted(raw_dir.glob("**/*.html")):
                # New layout: <model__s0>/index.html → derive from parent dir name
                # Legacy layout: <model__s0.html> → derive from filename
                if hf.name == "index.html":
                    fname = hf.parent.name
                else:
                    fname = hf.stem
                if "__s" in fname:
                    model_part, sample_part = fname.split("__s", 1)
                    try:
                        sample_index = int(sample_part)
                    except ValueError:
                        sample_index = None
                    model = model_part
                else:
                    model = fname
                    sample_index = None
                tasks.append({
                    "html_path": str(hf),
                    "test_js_path": str(test_js),
                    "screenshot_path": str(_default_screenshot_path(rd, base_test_name, base_test_name, model, sample_index, "control")),
                    "generation_conversation_path": None,
                    "generation_eval_path": None,
                    "test_name": base_test_name,
                    "base_test_name": base_test_name,
                    "prompt_case_id": base_test_name,
                    "prompt_dimensions": [],
                    "model": model,
                    "sample_index": sample_index,
                    "gen_meta": gen_meta_map.get((base_test_name, model, sample_index, "control", None)) or {},
                    "prompt_text": prompts_map.get(base_test_name, ""),
                    "prompt_variant_id": "control",
                    "prompt_variant_kind": "control",
                    "turn_id": None,
                    "turn_index": None,
                    "turn_count_total": None,
                })

    # Sort tasks for deterministic ordering
    tasks.sort(
        key=lambda t: (
            t["prompt_variant_id"] != "control",
            t["prompt_variant_id"],
            t["test_name"],
            t["model"],
            t["sample_index"] if t["sample_index"] is not None else -1,
            t.get("turn_index") if t.get("turn_index") is not None else -1,
        )
    )


    all_results = []
    pass_map: dict[tuple[str, str, str | None, str, str, str | None, str | None], dict[str, Any]] = {}
    if not tasks:
        typer.secho("No evaluation tasks found.", err=True)
    else:
        pool_size = None
        if processes is None:
            # Default: use CPU count but cap at len(tasks)
            pool_size = min(multiprocessing.cpu_count(), len(tasks))
        else:
            pool_size = max(1, processes)
        if pool_size == 1:
            total = len(tasks)
            done = 0
            _render_progress("Evaluating", done, total)
            for t in tasks:
                res = _evaluate_worker(t)
                all_results.append(res)
                key = (
                    res.get("test_name"),
                    res.get("base_test_name"),
                    res.get("prompt_case_id") or res.get("test_name"),
                    res.get("model_name"),
                    res.get("prompt_variant_id") or "control",
                    res.get("prompt_variant_kind"),
                    res.get("turn_id"),
                )
                entry = pass_map.setdefault(key, {"statuses": [], "prompt_dimensions": res.get("prompt_dimensions") or []})
                entry["statuses"].append({"pass": res.get("result") == "PASS"})
                done += 1
                _render_progress("Evaluating", done, total)
        else:
            typer.echo(f"Evaluating with {pool_size} processes...")
            with multiprocessing.Pool(processes=pool_size) as pool:
                total = len(tasks)
                done = 0
                _render_progress("Evaluating", done, total)
                for res in pool.imap(_evaluate_worker, tasks):
                    all_results.append(res)
                    key = (
                        res.get("test_name"),
                        res.get("base_test_name"),
                        res.get("prompt_case_id") or res.get("test_name"),
                        res.get("model_name"),
                        res.get("prompt_variant_id") or "control",
                        res.get("prompt_variant_kind"),
                        res.get("turn_id"),
                    )
                    entry = pass_map.setdefault(key, {"statuses": [], "prompt_dimensions": res.get("prompt_dimensions") or []})
                    entry["statuses"].append({"pass": res.get("result") == "PASS"})
                    done += 1
                    _render_progress("Evaluating", done, total)

    aggregates: List[dict] = []
    for (test_name, base_test_name, prompt_case_id, model, variant_id, variant_kind, turn_id), entry in pass_map.items():
        statuses = entry["statuses"]
        n = len(statuses)
        c = sum(1 for status in statuses if status.get("pass"))
        pass_at = compute_pass_at_k(c, n, k_values)
        # Derive turn_index for this group from one of the evaluated records.
        turn_index_for_group: int | None = None
        if variant_kind == "skill":
            for r in all_results:
                if (
                    r.get("test_name") == test_name
                    and r.get("model_name") == model
                    and (r.get("prompt_variant_id") or "control") == variant_id
                    and r.get("turn_id") == turn_id
                ):
                    ti = r.get("turn_index")
                    if ti is not None:
                        turn_index_for_group = int(ti)
                        break
        agg = AggregateRecord(
            test_name=test_name,
            base_test_name=base_test_name,
            prompt_case_id=prompt_case_id,
            prompt_dimensions=entry.get("prompt_dimensions") or [],
            model_name=model,
            prompt_variant_id=variant_id or "control",
            prompt_variant_kind=variant_kind,
            turn_id=turn_id,
            turn_index=turn_index_for_group,
            n_samples=n,
            n_applicable=n,
            n_not_applicable=0,
            n_pass=c,
            pass_at_k=format_pass_at_k(pass_at),
            k_values=k_values,
            computed_at=datetime.utcnow(),
        )
        aggregates.append(json.loads(agg.model_dump_json()))

    updated_json = {
        "run_id": prior_data.get("run_id") or rd.name,
        "models": model_names,
        "tests": prior_data.get("tests") or sorted({r.get("test_name") for r in all_results if r.get("test_name")}),
        "prompts": prompts_map,
        "results": all_results,
        "aggregates": aggregates,
        "meta": {
            **(prior_data.get("meta") or {}),
            "sampling": {
                **((prior_data.get("meta") or {}).get("sampling") or {}),
                "k_values": k_values,
                "processes": (processes if processes is not None else min(multiprocessing.cpu_count(), len(tasks))) if tasks else None,
            },
            "status": "EVALUATED",
        },
    }
    results_json_path.write_text(json.dumps(updated_json, indent=2), encoding="utf-8")
    if generate_report:
        from .report import render_report
        # Synthesize minimal models_cfg for backward compatibility with report renderer
        synthesized_models_cfg = {
            "models": [
                {"name": name, "display_name": display_lookup.get(name) or (str(name).split('/')[-1])}
                for name in model_names
            ]
        }
        render_report(
            results_json_path,
            rd / "index.html",
            synthesized_models_cfg,
            include_generated_html_samples=report_include_generated_html_samples,
        )
        typer.echo(f"Evaluation complete. Report generated: {rd}/index.html")
    else:
        typer.echo("Evaluation complete. Report generation skipped.")


@app.command()
def report(
    run_dir: str,
    models_file: str = typer.Option("config/models.yaml", help="Models config YAML"),
    include_generated_html_samples: bool = typer.Option(
        True,
        "--include-generated-html-samples/--exclude-generated-html-samples",
        help="Include direct links to generated HTML samples in the HTML report.",
    ),
    ):
    """Regenerate HTML report for an existing run directory."""
    models_cfg, _ = load_models_config(models_file)
    rd = Path(run_dir)
    from .report import render_report
    render_report(
        rd / "results.json",
        rd / "index.html",
        models_cfg,
        include_generated_html_samples=include_generated_html_samples,
    )
    typer.echo("Report regenerated.")


@app.command()
def serve(
    run_dir: str,
    host: str = typer.Option("127.0.0.1", help="Host interface to bind the local HTTP server"),
    port: int = typer.Option(8000, min=0, help="Port to bind. Use 0 to choose an ephemeral port automatically"),
    open_browser: bool = typer.Option(False, "--open", help="Open the served report URL in the default browser"),
):
    """Serve an existing run directory over localhost HTTP until interrupted."""
    rd = Path(run_dir)
    if not rd.is_dir():
        raise typer.BadParameter(f"Run directory does not exist: {rd}")

    static_server = node_bridge.serve_directory(rd, host=host, port=port)
    report_url = static_server.index_url
    try:
        typer.echo(f"Serving run directory: {rd}")
        typer.echo(f"Base URL: {static_server.base_url}/")
        if (rd / "index.html").exists():
            typer.echo(f"Report URL: {report_url}")
            if open_browser:
                typer.launch(report_url)
        else:
            typer.echo("Report URL: <missing index.html; run evaluate or report first>")
        typer.echo("Press Ctrl+C to stop.")
        _wait_for_serve_interrupt()
    except KeyboardInterrupt:
        typer.echo("Stopping server...")
    finally:
        static_server.close()


def main():  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
