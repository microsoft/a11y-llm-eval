"""Typer CLI for running evaluations and generating reports."""
import hashlib
import inspect
import json
import multiprocessing
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
from .utils import atomic_write_text, check_docker_network_pool

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


def _render_progress(prefix: str, done: int, total: int) -> None:
    """Render a progress indicator.

    Prints a new line each time percent or done/total changes.  We intentionally
    avoid the ``\\r``-overwrite trick: worker subprocesses, Docker/compose, and
    the inspect_ai sandbox write their own lines to stdout/stderr during a run,
    which would push an in-place progress line up and leave visible gaps.  A
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
    """Top-level worker for multiprocessing to ensure picklability on spawn-based systems (macOS, Windows)."""
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
    node_res = node_bridge.run(html, test_js_path, screenshot_path)
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
            system_prompt=gen_meta.get("system_prompt", generator.get_base_system_prompt()),
            custom_instructions=gen_meta.get("custom_instructions", generator.get_custom_instructions()),
            effective_system_prompt=gen_meta.get("effective_system_prompt", generator.get_effective_system_prompt()),
            generation_mode=gen_meta.get("generation_mode"),
            agent_sandbox=gen_meta.get("agent_sandbox"),
            agent_limit_error=gen_meta.get("agent_limit_error"),
            agent_limits=gen_meta.get("agent_limits"),
        ),
        sample_index=sample_index,
        prompt_variant_id=prompt_variant_id,
        prompt_variant_kind=prompt_variant_kind,
        turn_id=turn_id,
        turn_index=turn_index,
        turn_count_total=turn_count_total,
    )
    return json.loads(rec.model_dump_json())


def _generate_worker(task):
    """Top-level generation worker for multiprocessing; receives a tuple of parameters."""
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
    system_prompt_override = task.get("system_prompt_override")
    custom_instructions_text = task.get("custom_instructions_text")
    prompt_variant_id = task.get("prompt_variant_id")
    prompt_variant_kind = task.get("prompt_variant_kind")
    debug_truncated_cache = task.get("debug_truncated_cache", False)
    html_out_path = task.get("html_out_path")
    conversation_out_path = task.get("conversation_out_path")
    model_display_name = task.get("model_display_name")
    provider_config = task.get("provider_config")
    runtime_log_dir = task.get("runtime_log_dir")
    generation_mode = task.get("generation_mode") or "direct"
    agent_config = task.get("agent_config") or {}

    # Configure prompts within this worker process for the specific variant.
    generator.configure_prompts(system_prompt_override, custom_instructions_text)
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
            html_path = Path(f"{html_out_path_stub}__t{t_idx}.html")
            html_path.parent.mkdir(exist_ok=True, parents=True)
            atomic_write_text(html_path, tr["html"] or "", encoding="utf-8")
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
                "eval_path": meta.get("agent_eval_path"),
                "prompt_variant_id": prompt_variant_id,
                "prompt_variant_kind": "skill",
                "turn_id": tr["turn_id"],
                "turn_index": t_idx,
                "turn_count_total": total_turns,
                "turn_error": tr.get("error"),
            })
        return {"skill_turn_records": skill_turn_records}

    conversation_payload = None
    if generation_mode == "inspect_react_agent":
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
        )
    else:
        kwargs = {
            "temperature": temperature,
            "seed": seed,
            "disable_cache": disable_cache,
        }
        try:
            generate_signature = inspect.signature(generator.generate_html_with_meta)
            if "model_display_name" in generate_signature.parameters:
                kwargs["model_display_name"] = model_display_name
            if "provider_config" in generate_signature.parameters:
                kwargs["provider_config"] = provider_config
            if "runtime_log_dir" in generate_signature.parameters:
                kwargs["runtime_log_dir"] = runtime_log_dir
        except (TypeError, ValueError):
            pass

        if debug_truncated_cache:
            kwargs["debug_truncated_cache"] = True

        html, meta = generator.generate_html_with_meta(model, prompt_text, sample_index, **kwargs)

    out_path = Path(html_out_path)
    out_path.parent.mkdir(exist_ok=True, parents=True)
    atomic_write_text(out_path, html, encoding="utf-8")

    conversation_path = None
    if conversation_payload is not None and conversation_out_path:
        conversation_target = Path(conversation_out_path)
        conversation_target.parent.mkdir(exist_ok=True, parents=True)
        atomic_write_text(conversation_target, json.dumps(conversation_payload, indent=2), encoding="utf-8")
        conversation_path = str(conversation_target)

    # Return only small, picklable data
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
        "eval_path": meta.get("agent_eval_path"),
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


def _resolve_cli_path(path_value: str, base_dir: Path) -> Path:
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate

    workspace_candidate = Path.cwd() / candidate
    if workspace_candidate.exists():
        return workspace_candidate

    return base_dir / candidate

def _provider_batch_enabled(provider_config: Any) -> bool:
    if not isinstance(provider_config, dict):
        return True
    batch_cfg = provider_config.get("batch")
    if not isinstance(batch_cfg, dict):
        return True
    enabled = batch_cfg.get("enabled")
    if enabled is None:
        return True
    return bool(enabled)


def _batch_group_key(task: dict[str, Any]) -> tuple[Any, ...]:
    provider_config = task.get("provider_config") or {}
    return (
        task.get("generation_mode") or "direct",
        task.get("model"),
        task.get("seed"),
        task.get("temperature"),
        task.get("system_prompt_override"),
        task.get("custom_instructions_text"),
        task.get("disable_cache", False),
        task.get("debug_truncated_cache", False),
        json.dumps(provider_config, sort_keys=True),
    )


def _generate_batch_group(indexed_tasks: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    first_task = indexed_tasks[0][1]
    generator.configure_prompts(
        first_task.get("system_prompt_override"),
        first_task.get("custom_instructions_text"),
    )
    generator.configure_runtime(first_task.get("runtime_log_dir"))

    requests = []
    for _, task in indexed_tasks:
        requests.append({
            "user_prompt": task["prompt_text"],
            "iteration": task["sample_index"],
            "temperature": task.get("temperature"),
            "seed": task.get("seed"),
            "disable_cache": task.get("disable_cache", False),
            "debug_truncated_cache": task.get("debug_truncated_cache", False),
        })

    kwargs = {
        "temperature": first_task.get("temperature"),
        "seed": first_task.get("seed"),
        "disable_cache": first_task.get("disable_cache", False),
        "debug_truncated_cache": first_task.get("debug_truncated_cache", False),
    }
    try:
        batch_signature = inspect.signature(generator.generate_html_batch_with_meta)
        if "model_display_name" in batch_signature.parameters:
            kwargs["model_display_name"] = first_task.get("model_display_name")
        if "provider_config" in batch_signature.parameters:
            kwargs["provider_config"] = first_task.get("provider_config")
        if "runtime_log_dir" in batch_signature.parameters:
            kwargs["runtime_log_dir"] = first_task.get("runtime_log_dir")
    except (TypeError, ValueError):
        pass

    batch_results = generator.generate_html_batch_with_meta(first_task["model"], requests, **kwargs)
    if len(batch_results) != len(indexed_tasks):
        raise RuntimeError("generate_html_batch_with_meta returned an unexpected number of results")

    generated_results = []
    for (_, task), batch_result in zip(indexed_tasks, batch_results):
        html = batch_result["html"]
        meta = batch_result.get("meta") or {}
        out_path = Path(task["html_out_path"])
        out_path.parent.mkdir(exist_ok=True, parents=True)
        atomic_write_text(out_path, html, encoding="utf-8")
        generated_results.append({
            "test_name": task["test_name"],
            "base_test_name": task["base_test_name"],
            "prompt_case_id": task["prompt_case_id"],
            "prompt_dimensions": task.get("prompt_dimensions") or [],
            "model": task["model"],
            "sample_index": task["sample_index"],
            "prompt_text": task["prompt_text"],
            "meta": meta,
            "html_path": str(out_path),
            "prompt_variant_id": task.get("prompt_variant_id"),
        })
    return generated_results


def _load_instruction_sets(instruction_sets_file: str, base_dir: Path) -> list[dict]:
    """Load instruction sets YAML.

    Expected format:
      instruction_sets:
        - id: concise
          name: Concise
          description: ...
          system_prompt_append_markdown: path/to/file.md
          samples: 10
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
                f"Instruction set '{sid}' cannot specify generation_mode; instruction sets always use the inspect_react_agent path"
            )
        md_path = s.get("system_prompt_append_markdown")
        if not md_path:
            raise ValueError(f"Instruction set '{sid}' must include system_prompt_append_markdown")
        mdp = Path(md_path)
        if not mdp.is_absolute():
            mdp = (base_dir / mdp).resolve()
        if not mdp.exists():
            raise FileNotFoundError(f"Instruction markdown not found for '{sid}': {mdp}")
        out.append({
            "id": sid,
            "name": (s.get("name") or sid).strip(),
            "description": (s.get("description") or "").strip() or None,
            "markdown_path": str(mdp),
            "markdown_text": mdp.read_text(encoding="utf-8"),
            "samples": s.get("samples"),
            "generation_mode": "inspect_react_agent",
            "agent": s.get("agent") if isinstance(s.get("agent"), dict) else {},
        })
    return out


SKILL_SANDBOX_MOUNT_ROOT = "/workspace/.skills"
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


def _skill_system_prompt_preamble(skill_id: str, skill_name: str, sandbox_path: str) -> str:
    """Preamble appended to the system prompt when a skill variant is active."""
    return (
        f"A skill named `{skill_name}` ({skill_id}) is available inside the sandbox at "
        f"`{sandbox_path}/SKILL.md`. Read it before producing output and follow its "
        f"guidance. The skill directory and any support files live under `{sandbox_path}/`."
    )


def _load_skills(skills_file: str, base_dir: Path, existing_ids: set[str] | None = None) -> list[dict]:
    """Load a skills YAML file.

    Expected format::

        skills:
          - id: a11y-reviewer
            name: Accessibility Reviewer
            description: ...
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
                f"Skill '{sid}' cannot specify generation_mode; skills always use the inspect_react_agent path"
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

        sandbox_path = f"{SKILL_SANDBOX_MOUNT_ROOT}/{sid}"
        name = (s.get("name") or sid).strip()
        files_hash = _hash_skill_files(sdp)
        out.append({
            "id": sid,
            "name": name,
            "description": (s.get("description") or "").strip() or None,
            "skill_dir_abs_path": str(sdp),
            "skill_files_hash": files_hash,
            "sandbox_mount_path": sandbox_path,
            "system_prompt_preamble": _skill_system_prompt_preamble(sid, name, sandbox_path),
            "turns": turns,
            "samples": s.get("samples"),
            "generation_mode": "inspect_react_agent",
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
    processes: int = typer.Option(None, "--processes", "-p", help="Parallel processes for generation (defaults CPU count; use 1 to disable)."),
    debug_truncated_cache: bool = typer.Option(
        False,
        help="Debug: if truncated/corrupted cached HTML is detected, preserve it and print a list at the end of generation.",
    ),
):
    """Generate HTML samples ONLY (no evaluation). A later 'evaluate' command will run tests & build report."""
    run_id = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    out_dir = Path(out) / run_id
    (out_dir / "raw").mkdir(parents=True, exist_ok=True)
    # Prepare screenshots directory (will be populated during evaluation phase)
    (out_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    inspect_logs_dir = out_dir / "inspect_logs"
    inspect_logs_dir.mkdir(parents=True, exist_ok=True)

    models_cfg, models_file_path = load_models_config(models_file)
    normalized_models = normalize_models_config(models_cfg)
    defaults_cfg = normalized_models["defaults"]
    config_dir = models_file_path.parent
    system_prompt_override = defaults_cfg.get("system_prompt")

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
    generator.configure_prompts(system_prompt_override, custom_instructions_text)
    # Capture prompting meta *now* (important when --processes=1, since workers mutate module state).
    base_prompting_system_prompt = generator.get_base_system_prompt()
    base_prompting_effective_system_prompt = generator.get_effective_system_prompt()
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
        "generation_mode": "direct",
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
                "custom_instructions_path": s.get("markdown_path"),
                "custom_instructions_text": s.get("markdown_text"),
                "n_samples_requested": n_int,
                "generation_mode": "inspect_react_agent",
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
                # Treat the skill preamble as the custom-instructions payload so it
                # flows through the existing effective-system-prompt / cache pipeline.
                "custom_instructions_path": None,
                "custom_instructions_text": sk["system_prompt_preamble"],
                "n_samples_requested": n_int,
                "generation_mode": "inspect_react_agent",
                "agent": sk.get("agent") or {},
                "kind": "skill",
                "skill_id": sk["id"],
                "skill_dir_abs_path": sk["skill_dir_abs_path"],
                "skill_files_hash": sk["skill_files_hash"],
                "sandbox_mount_path": sk["sandbox_mount_path"],
                "system_prompt_preamble": sk["system_prompt_preamble"],
                "turns": sk["turns"],
            })
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

                    if variant_kind == "skill":
                        raw_path = out_dir / "raw_skills" / variant_id / prompt_case.prompt_case_id
                        # One HTML file per turn; conversation sidecar is per-sample.
                        html_file_stub = raw_path / f"{model}__s{sample_index}"
                        conversation_file = raw_path / f"{model}__s{sample_index}.agent.json"
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
                            "system_prompt_override": system_prompt_override,
                            "custom_instructions_text": variant.get("custom_instructions_text"),
                            "prompt_variant_id": variant_id,
                            "prompt_variant_kind": "skill",
                            "debug_truncated_cache": debug_truncated_cache,
                            "html_out_path_stub": str(html_file_stub),
                            "conversation_out_path": str(conversation_file),
                            "model_display_name": model_display_lookup.get(model),
                            "runtime_log_dir": str(inspect_logs_dir),
                            "provider_config": model_provider_lookup.get(model),
                            "generation_mode": "inspect_react_agent",
                            "agent_config": variant.get("agent") or {},
                            "skill_config": {
                                "id": variant["skill_id"],
                                "host_dir": variant["skill_dir_abs_path"],
                                "sandbox_mount_path": variant["sandbox_mount_path"],
                                "system_prompt_preamble": variant["system_prompt_preamble"],
                                "skill_files_hash": variant["skill_files_hash"],
                                "turns": variant["turns"],
                            },
                        })
                        continue

                    if variant_id == "control":
                        raw_path = out_dir / "raw" / prompt_case.prompt_case_id
                        html_file = raw_path / (f"{model}__s{sample_index}.html" if n_samples > 1 else f"{model}.html")
                        conversation_file = None
                    else:
                        raw_path = out_dir / "raw_variants" / variant_id / prompt_case.prompt_case_id
                        html_file = raw_path / f"{model}__s{sample_index}.html"
                        conversation_file = raw_path / f"{model}__s{sample_index}.agent.json"

                    generation_mode = "direct" if variant_id == "control" else "inspect_react_agent"

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
                        "system_prompt_override": system_prompt_override,
                        "custom_instructions_text": variant.get("custom_instructions_text"),
                        "prompt_variant_id": variant_id,
                        "prompt_variant_kind": variant_kind,
                        "debug_truncated_cache": debug_truncated_cache,
                        "html_out_path": str(html_file),
                        "conversation_out_path": (str(conversation_file) if conversation_file is not None else None),
                        "model_display_name": model_display_lookup.get(model),
                        "runtime_log_dir": str(inspect_logs_dir),
                        "provider_config": model_provider_lookup.get(model),
                        "generation_mode": generation_mode,
                        "agent_config": variant.get("agent") or {},
                    })

    # Flatten into a single task list using round-robin across models
    gen_tasks = []  # (test_name, model, sample_index, prompt, seed)
    made_progress = True
    while made_progress:
        made_progress = False
        for model in model_names:
            queue = tasks_by_model.get(model)
            if queue:
                gen_tasks.append(queue.pop(0))
                made_progress = True

    # If any tasks use Docker sandboxes, check that the Docker network
    # address pool has capacity.  Fail early rather than partway through
    # a run when new sandboxes can no longer allocate subnets.
    has_agent_tasks = any(
        (t.get("generation_mode") or "direct") != "direct" for t in gen_tasks
    )
    if has_agent_tasks:
        check_docker_network_pool()

    if gen_tasks:
        pool_size = None
        if processes is None:
            pool_size = min(multiprocessing.cpu_count(), len(gen_tasks))
        else:
            pool_size = max(1, processes)
        # Cap parallelism for agent (Docker sandbox) tasks to avoid exhausting
        # Docker's network address pool.  Each sandbox allocates a subnet; the
        # default pool supports ~30 networks, so 8 concurrent sandboxes is a
        # safe default that leaves headroom for other Docker workloads.
        _MAX_AGENT_PARALLEL = 8
        if has_agent_tasks and processes is None and pool_size > _MAX_AGENT_PARALLEL:
            pool_size = _MAX_AGENT_PARALLEL
        truncated_cache_files: set[str] = set()
        def _consume_generation_results(gen_results_iter):
            total = len(gen_tasks)
            done = 0
            _render_progress("Generating", done, total)
            for gen_result in gen_results_iter:
                done += 1
                _render_progress("Generating", done, total)

                # Skill tasks return a dict wrapping a list of per-turn records.
                if isinstance(gen_result, dict) and "skill_turn_records" in gen_result:
                    turn_records = gen_result["skill_turn_records"]
                    for tr in turn_records:
                        _append_result_record(tr)
                    continue
                _append_result_record(gen_result)

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

            if debug_truncated_cache and isinstance(meta, dict):
                tcf = meta.get("truncated_cache_files")
                if isinstance(tcf, list):
                    for p in tcf:
                        if isinstance(p, str) and p:
                            truncated_cache_files.add(p)

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
                    system_prompt=meta.get("system_prompt", generator.get_base_system_prompt()),
                    custom_instructions=meta.get("custom_instructions", generator.get_custom_instructions()),
                    effective_system_prompt=meta.get("effective_system_prompt", generator.get_effective_system_prompt()),
                    generation_mode=meta.get("generation_mode"),
                    agent_sandbox=meta.get("agent_sandbox"),
                    agent_limit_error=meta.get("agent_limit_error"),
                    agent_limits=meta.get("agent_limits"),
                ),
                sample_index=sample_index,
                prompt_variant_id=variant_id,
                prompt_variant_kind=prompt_variant_kind,
                turn_id=gen_result.get("turn_id"),
                turn_index=gen_result.get("turn_index"),
                turn_count_total=gen_result.get("turn_count_total"),
            )
            results.append(json.loads(rec.model_dump_json()))

        batch_supported = (
            hasattr(generator, "generate_html_batch_with_meta")
            and generator.supports_batch_generation()
        )
        indexed_tasks = list(enumerate(gen_tasks))
        batched_groups: list[list[tuple[int, dict[str, Any]]]] = []
        single_indexed_tasks: list[tuple[int, dict[str, Any]]] = []

        if batch_supported:
            grouped_tasks: dict[tuple[Any, ...], list[tuple[int, dict[str, Any]]]] = {}
            for indexed_task in indexed_tasks:
                task = indexed_task[1]
                if (task.get("generation_mode") or "direct") == "direct" and _provider_batch_enabled(task.get("provider_config")):
                    grouped_tasks.setdefault(_batch_group_key(task), []).append(indexed_task)
                else:
                    single_indexed_tasks.append(indexed_task)

            for group in grouped_tasks.values():
                if len(group) > 1:
                    batched_groups.append(sorted(group, key=lambda item: item[0]))
                else:
                    single_indexed_tasks.extend(group)
            batched_groups.sort(key=lambda group: group[0][0])
        else:
            single_indexed_tasks = indexed_tasks

        single_indexed_tasks.sort(key=lambda item: item[0])
        single_tasks = [task for _, task in single_indexed_tasks]

        def _iter_generation_results():
            for group in batched_groups:
                for gen_result in _generate_batch_group(group):
                    yield gen_result

            if not single_tasks:
                return

            if pool_size == 1:
                for gen_result in map(_generate_worker, single_tasks):
                    yield gen_result
                return

            typer.echo(f"Generating with {pool_size} processes...")
            with multiprocessing.Pool(processes=pool_size) as pool:
                for gen_result in pool.imap(_generate_worker, single_tasks):
                    yield gen_result

        try:
            _consume_generation_results(_iter_generation_results())
        except generator.OutputTokenLimitHit as exc:
            typer.echo("")
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=2)

        if debug_truncated_cache:
            typer.echo("")
            if truncated_cache_files:
                typer.secho("Truncated/corrupted cached HTML files detected:", fg=typer.colors.YELLOW)
                for p in sorted(truncated_cache_files):
                    typer.echo(p)
            else:
                typer.echo("No truncated/corrupted cached HTML files detected.")

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
                "processes_generation": (processes if processes is not None else min(multiprocessing.cpu_count(), len(gen_tasks))) if gen_tasks else None,
                "prompt_dimensions_file": str(prompt_dimensions_path.resolve()),
            },
            "prompting": {
                "system_prompt": base_prompting_system_prompt,
                "effective_system_prompt": base_prompting_effective_system_prompt,
                "custom_instructions": base_prompting_custom_instructions,
                "custom_instructions_path": custom_instructions_path,
            },
            "prompt_variants": [json.loads(PromptVariant(
                id=v.get("id") or "control",
                name=v.get("name"),
                description=v.get("description"),
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
                "engine": "inspect_ai",
                "log_dir": str(inspect_logs_dir.resolve()),
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
        pass
    _print_generation_summary(results, gen_tasks)
    typer.echo(f"Generation complete. Run directory ready for evaluation: {out_dir}")


@app.command()
def evaluate(
    run_dir: str = typer.Argument(..., help="Existing run directory produced by 'run' command"),
    test_cases_dir: str = typer.Option("test_cases", help="Directory containing test case folders."),
    test_cases: str = typer.Option(None, "--test-cases", help="Comma-separated base test case names to evaluate (e.g. single-checkbox,modal-dialog). Defaults to all."),
    k: str = typer.Option("1,5,10", help="Comma-separated k values for pass@k metrics."),
    generate_report: bool = typer.Option(True, help="Generate HTML report (index.html) after evaluation."),
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
                fname = hf.name
                if "__s" in fname:
                    model_part, sample_part = fname.split("__s", 1)
                    sample_index_str = sample_part[:-5] if sample_part.endswith(".html") else sample_part
                    try:
                        sample_index = int(sample_index_str)
                    except ValueError:
                        sample_index = None
                    model = model_part
                else:
                    model = fname[:-5]
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
        render_report(results_json_path, rd / "index.html", synthesized_models_cfg)
        typer.echo(f"Evaluation complete. Report generated: {rd}/index.html")
    else:
        typer.echo("Evaluation complete. Report generation skipped.")


@app.command()
def report(
    run_dir: str,
    models_file: str = typer.Option("config/models.yaml", help="Models config YAML")
    ):
    """Regenerate HTML report for an existing run directory."""
    models_cfg, _ = load_models_config(models_file)
    rd = Path(run_dir)
    from .report import render_report
    render_report(rd / "results.json", rd / "index.html", models_cfg)
    typer.echo("Report regenerated.")


def main():  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
