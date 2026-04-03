"""Typer CLI for running evaluations and generating reports."""
import json
import multiprocessing
from datetime import datetime
from pathlib import Path
import typer
import yaml
from typing import List

from . import generator, node_bridge
from .schema import (
    ResultRecord,
    TestFunctionResult,
    AxeResult,
    GenerationMeta,
    AggregateRecord,
    PromptVariant,
)
from .metrics import compute_pass_at_k, format_pass_at_k
from .utils import atomic_write_text

# importing os module for environment variables
import os
# importing necessary functions from dotenv library
from dotenv import load_dotenv, dotenv_values 
# loading variables from .env file
load_dotenv() 

app = typer.Typer(add_completion=False)


def _render_progress(prefix: str, done: int, total: int) -> None:
    """Render an in-place progress indicator.

    Uses carriage returns to avoid spamming lines.
    """
    if total <= 0:
        return
    done = max(0, min(done, total))
    pct = int((done / total) * 100)
    typer.echo(f"\r{prefix}: {pct}% ({done}/{total})", nl=False)
    if done >= total:
        typer.echo("")


def _evaluate_worker(args_tuple):
    """Top-level worker for multiprocessing to ensure picklability on spawn-based systems (macOS, Windows)."""
    html_path, test_js_path, screenshot_path, test_name, model, sample_index, gen_meta, prompt_text, prompt_variant_id = args_tuple
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
        model_name=model,
        timestamp=datetime.utcnow(),
        generation_html_path=html_path,
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
        ),
        sample_index=sample_index,
        prompt_variant_id=prompt_variant_id,
    )
    return json.loads(rec.model_dump_json()), test_name, model, prompt_variant_id, {
        "pass": result_pass,
    }


def _generate_worker(task):
    """Top-level generation worker for multiprocessing; receives a tuple of parameters."""
    (
        test_name,
        model,
        sample_index,
        prompt_text,
        seed,
        temperature,
        disable_cache,
        system_prompt_override,
        custom_instructions_text,
        prompt_variant_id,
        debug_truncated_cache,
        html_out_path,
        model_display_name,
    ) = task

    # Configure prompts within this worker process for the specific variant.
    generator.configure_prompts(system_prompt_override, custom_instructions_text)

    kwargs = {
        "temperature": temperature,
        "seed": seed,
        "disable_cache": disable_cache,
        "model_display_name": model_display_name,
    }
    if debug_truncated_cache:
        kwargs["debug_truncated_cache"] = True

    html, meta = generator.generate_html_with_meta(model, prompt_text, sample_index, **kwargs)

    out_path = Path(html_out_path)
    out_path.parent.mkdir(exist_ok=True, parents=True)
    atomic_write_text(out_path, html, encoding="utf-8")

    # Return only small, picklable data
    return test_name, model, sample_index, prompt_text, meta, str(out_path), prompt_variant_id


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
        })
    return out


@app.command()
def run(
    models_file: str = typer.Option("config/models.yaml", help="Models config YAML"),
    out: str = typer.Option("runs", help="Output directory"),
    samples: int = typer.Option(1, min=1, help="Number of samples per (test,model)."),
    k: str = typer.Option("1,5,10", help="Comma-separated k values for pass@k metrics (stored for later evaluation)."),
    base_seed: int = typer.Option(None, help="Base seed for reproducibility; each sample adds its index."),
    temperature: float = typer.Option(None, help="Override model temperature (if supported)."),
    disable_cache: bool = typer.Option(False, help="Disable generation cache (always re-generate)."),
    instruction_sets_file: str = typer.Option(None, help="Optional YAML defining custom instruction sets to benchmark vs control."),
    instruction_samples: int = typer.Option(None, min=1, help="Default samples per instruction set (if not specified in instruction sets file)."),
    test_cases_dir: str = typer.Option("test_cases", help="Directory containing test case folders."),
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

    models_cfg = yaml.safe_load(open(models_file))
    defaults_cfg = models_cfg.get("defaults") or {}
    config_dir = Path(models_file).resolve().parent
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
    # - When benchmarking instruction sets, control must be the base system prompt with no custom instructions.
    # - Otherwise, keep existing behavior (defaults.custom_instructions_markdown applies).
    instructions_cfg = defaults_cfg.get("custom_instructions_markdown")
    custom_instructions_text = None
    custom_instructions_path = None
    if instruction_sets_file is None and instructions_cfg:
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
    model_names = [m["name"] for m in models_cfg.get("models", [])]
    model_display_lookup = {}
    models_info = []
    for m in models_cfg.get("models", []):
        name = m.get("name")
        display_name = m.get("display_name") or (name.split('/')[-1] if isinstance(name, str) else name)
        model_display_lookup[name] = display_name
        models_info.append({"name": name, "display_name": display_name})
    tcd = Path(test_cases_dir)
    test_dirs = [p for p in tcd.iterdir() if p.is_dir() and (p / "prompt.md").exists()]

    # Prompt variants: always include control
    prompt_variants: list[dict] = []
    prompt_variants.append({
        "id": "control",
        "name": "Control",
        "description": "Base system prompt; no custom instructions" if instruction_sets_file else "Base prompt configuration",
        "custom_instructions_path": (None if instruction_sets_file else custom_instructions_path),
        "custom_instructions_text": (None if instruction_sets_file else custom_instructions_text),
        "n_samples_requested": samples,
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
            })
    # Build generation tasks
    results = []  # stub pending evaluation records
    prompts_map = {}
    # Round-robin task queues per model to avoid hammering a single LLM
    tasks_by_model = {model: [] for model in model_names}
    for td in test_dirs:
        prompt_text = (td / "prompt.md").read_text(encoding="utf-8")
        prompts_map[td.name] = prompt_text
        for model in model_names:
            for variant in prompt_variants:
                n_samples = int(variant.get("n_samples_requested") or samples)
                for sample_index in range(n_samples):
                    seed = (base_seed + sample_index) if base_seed is not None else None
                    variant_id = variant.get("id") or "control"

                    if variant_id == "control":
                        raw_path = out_dir / "raw" / td.name
                        html_file = raw_path / (f"{model}__s{sample_index}.html" if samples > 1 else f"{model}.html")
                    else:
                        raw_path = out_dir / "raw_variants" / variant_id / td.name
                        html_file = raw_path / f"{model}__s{sample_index}.html"

                    tasks_by_model[model].append((
                        td.name,
                        model,
                        sample_index,
                        prompt_text,
                        seed,
                        effective_temperature,
                        disable_cache,
                        system_prompt_override,
                        variant.get("custom_instructions_text"),
                        variant_id,
                        debug_truncated_cache,
                        str(html_file),
                        model_display_lookup.get(model),
                    ))

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

    if gen_tasks:
        pool_size = None
        if processes is None:
            pool_size = min(multiprocessing.cpu_count(), len(gen_tasks))
        else:
            pool_size = max(1, processes)
        truncated_cache_files: set[str] = set()
        def _consume_generation_results(gen_results_iter):
            total = len(gen_tasks)
            done = 0
            _render_progress("Generating", done, total)
            for test_name, model, sample_index, prompt_text, meta, html_path, prompt_variant_id in gen_results_iter:
                done += 1
                _render_progress("Generating", done, total)

                if debug_truncated_cache and isinstance(meta, dict):
                    tcf = meta.get("truncated_cache_files")
                    if isinstance(tcf, list):
                        for p in tcf:
                            if isinstance(p, str) and p:
                                truncated_cache_files.add(p)

                variant_id = prompt_variant_id or "control"

                rec = ResultRecord(
                    test_name=test_name,
                    model_name=model,
                    timestamp=datetime.utcnow(),
                    generation_html_path=str(html_path),
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
                    ),
                    sample_index=sample_index,
                    prompt_variant_id=variant_id,
                )
                results.append(json.loads(rec.model_dump_json()))

        if pool_size == 1:
            try:
                _consume_generation_results(map(_generate_worker, gen_tasks))
            except generator.OutputTokenLimitHit as exc:
                typer.echo("")
                typer.secho(str(exc), fg=typer.colors.RED, err=True)
                raise typer.Exit(code=2)
        else:
            typer.echo(f"Generating with {pool_size} processes...")
            with multiprocessing.Pool(processes=pool_size) as pool:
                try:
                    _consume_generation_results(pool.imap(_generate_worker, gen_tasks))
                except generator.OutputTokenLimitHit as exc:
                    pool.terminate()
                    pool.join()
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
        "tests": [d.name for d in test_dirs],
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
            ).model_dump_json()) for v in prompt_variants],
            "models_info": models_info,
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
    typer.echo(f"Generation complete. Run directory ready for evaluation: {out_dir}")


@app.command()
def evaluate(
    run_dir: str = typer.Argument(..., help="Existing run directory produced by 'run' command"),
    test_cases_dir: str = typer.Option("test_cases", help="Directory containing test case folders."),
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
    # prompts
    tcd = Path(test_cases_dir)
    test_dirs = [p for p in tcd.iterdir() if p.is_dir() and (p / "prompt.md").exists()]
    prompts_map = {td.name: (td / "prompt.md").read_text(encoding="utf-8") for td in test_dirs}
    k_values = [int(x.strip()) for x in k.split(",") if x.strip().isdigit()]
    if not k_values:
        k_values = [1]

    # Map generation meta by (test, model, sample_index, variant) for reuse
    gen_meta_map = {}
    for r in prior_data.get("results", []) if prior_data else []:
        variant_id = r.get("prompt_variant_id") or "control"
        key = (r.get("test_name"), r.get("model_name"), r.get("sample_index"), variant_id)
        gen_meta_map[key] = r.get("generation")

    # Build evaluation task list
    # each entry: (html_path, test_js_path, screenshot_path, test_name, model, sample_index, gen_meta, prompt_text, prompt_variant_id)
    tasks = []
    for td in test_dirs:
        test_name = td.name
        test_js = td / "test.js"
        # Control (legacy behavior)
        raw_dir = rd / "raw" / test_name
        if raw_dir.exists():
            html_files = sorted(raw_dir.glob("**/*.html"))
            for hf in html_files:
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
                screenshot_name = f"{test_name}__{model}__s{sample_index}.png" if sample_index is not None else f"{test_name}__{model}.png"
                screenshot_path = rd / "screenshots" / screenshot_name
                gen_meta = gen_meta_map.get((test_name, model, sample_index, "control")) or {}
                if sample_index is None and not gen_meta:
                    gen_meta = gen_meta_map.get((test_name, model, 0, "control")) or {}
                tasks.append((str(hf), str(test_js), str(screenshot_path), test_name, model, sample_index, gen_meta, prompts_map.get(test_name, ""), "control"))
        else:
            typer.secho(f"Skipping missing raw dir for test '{test_name}'", err=True)

        # Variants
        variants_root = rd / "raw_variants"
        if variants_root.exists():
            for variant_dir in sorted([p for p in variants_root.iterdir() if p.is_dir()]):
                variant_id = variant_dir.name
                v_test_dir = variant_dir / test_name
                if not v_test_dir.exists():
                    continue
                v_html_files = sorted(v_test_dir.glob("**/*.html"))
                for hf in v_html_files:
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
                    screenshot_name = f"{test_name}__{model}__s{sample_index}.png" if sample_index is not None else f"{test_name}__{model}.png"
                    screenshot_path = rd / "screenshots_variants" / variant_id / screenshot_name
                    gen_meta = gen_meta_map.get((test_name, model, sample_index, variant_id)) or {}
                    if sample_index is None and not gen_meta:
                        gen_meta = gen_meta_map.get((test_name, model, 0, variant_id)) or {}
                    tasks.append((str(hf), str(test_js), str(screenshot_path), test_name, model, sample_index, gen_meta, prompts_map.get(test_name, ""), variant_id))

    # Sort tasks for deterministic ordering
    # Sort tasks for deterministic ordering (control first)
    tasks.sort(key=lambda t: (t[8] != "control", t[8], t[3], t[4], t[5] if t[5] is not None else -1))


    all_results = []
    pass_map = {}  # (test_name, model, variant) -> list[bool]
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
                res, test_name, model, prompt_variant_id, sample_outcome = _evaluate_worker(t)
                all_results.append(res)
                pass_map.setdefault((test_name, model, prompt_variant_id or "control"), []).append(sample_outcome)
                done += 1
                _render_progress("Evaluating", done, total)
        else:
            typer.echo(f"Evaluating with {pool_size} processes...")
            with multiprocessing.Pool(processes=pool_size) as pool:
                total = len(tasks)
                done = 0
                _render_progress("Evaluating", done, total)
                for res, test_name, model, prompt_variant_id, sample_outcome in pool.imap(_evaluate_worker, tasks):
                    all_results.append(res)
                    pass_map.setdefault((test_name, model, prompt_variant_id or "control"), []).append(sample_outcome)
                    done += 1
                    _render_progress("Evaluating", done, total)

    aggregates: List[dict] = []
    for (test_name, model, variant_id), statuses in pass_map.items():
        n = len(statuses)
        c = sum(1 for status in statuses if status.get("pass"))
        pass_at = compute_pass_at_k(c, n, k_values)
        agg = AggregateRecord(
            test_name=test_name,
            model_name=model,
            prompt_variant_id=variant_id or "control",
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
        "tests": [d.name for d in test_dirs],
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
    models_cfg = yaml.safe_load(open(models_file))
    rd = Path(run_dir)
    from .report import render_report
    render_report(rd / "results.json", rd / "index.html", models_cfg)
    typer.echo("Report regenerated.")


def main():  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
