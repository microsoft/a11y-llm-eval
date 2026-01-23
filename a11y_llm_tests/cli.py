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
)
from .metrics import compute_pass_at_k, format_pass_at_k

# importing os module for environment variables
import os
# importing necessary functions from dotenv library
from dotenv import load_dotenv, dotenv_values 
# loading variables from .env file
load_dotenv() 

app = typer.Typer(add_completion=False)


def _evaluate_worker(args_tuple):
    """Top-level worker for multiprocessing to ensure picklability on spawn-based systems (macOS, Windows)."""
    html_path, test_js_path, screenshot_path, test_name, model, sample_index, gen_meta, prompt_text = args_tuple
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
        norm_assertions.append({
            "name": a.get("name", "unknown"),
            "status": a.get("status", "fail"),
            "message": a.get("message"),
            "type": atype,
        })
    test_result = TestFunctionResult(
        status=tf.get("status", "error"),
        assertions=norm_assertions,
        error=tf.get("error"),
        duration_ms=tf.get("duration_ms"),
        total_assertion_failures=tf.get("total_assertion_failures", 0),
        total_assertion_bp_failures=tf.get("total_assertion_bp_failures", 0)
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
    )
    return json.loads(rec.model_dump_json()), test_name, model, result_pass


def _generate_worker(task):
    """Top-level generation worker for multiprocessing; receives a tuple of parameters."""
    test_name, model, sample_index, prompt_text, seed, temperature, disable_cache = task
    html, meta = generator.generate_html_with_meta(
        model,
        prompt_text,
        sample_index,
        temperature=temperature,
        seed=seed,
        disable_cache=disable_cache,
    )
    return test_name, model, sample_index, prompt_text, meta, html


@app.command()
def run(
    models_file: str = typer.Option("config/models.yaml", help="Models config YAML"),
    out: str = typer.Option("runs", help="Output directory"),
    samples: int = typer.Option(1, min=1, help="Number of samples per (test,model)."),
    k: str = typer.Option("1,5,10", help="Comma-separated k values for pass@k metrics (stored for later evaluation)."),
    base_seed: int = typer.Option(None, help="Base seed for reproducibility; each sample adds its index."),
    temperature: float = typer.Option(None, help="Override model temperature (if supported)."),
    disable_cache: bool = typer.Option(False, help="Disable generation cache (always re-generate)."),
    test_cases_dir: str = typer.Option("test_cases", help="Directory containing test case folders."),
    processes: int = typer.Option(None, "--processes", "-p", help="Parallel processes for generation (defaults CPU count; use 1 to disable)."),
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
    instructions_cfg = defaults_cfg.get("custom_instructions_markdown")
    custom_instructions_text = None
    custom_instructions_path = None
    if instructions_cfg:
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
    model_names = [m["name"] for m in models_cfg.get("models", [])]
    models_info = []
    for m in models_cfg.get("models", []):
        name = m.get("name")
        display_name = m.get("display_name") or (name.split('/')[-1] if isinstance(name, str) else name)
        models_info.append({"name": name, "display_name": display_name})
    tcd = Path(test_cases_dir)
    test_dirs = [p for p in tcd.iterdir() if p.is_dir() and (p / "prompt.md").exists()]
    # Build generation tasks
    results = []  # stub pending evaluation records
    prompts_map = {}
    # Round-robin task queues per model to avoid hammering a single LLM
    tasks_by_model = {model: [] for model in model_names}
    for td in test_dirs:
        prompt_text = (td / "prompt.md").read_text(encoding="utf-8")
        prompts_map[td.name] = prompt_text
        for model in model_names:
            for sample_index in range(samples):
                seed = (base_seed + sample_index) if base_seed is not None else None
                tasks_by_model[model].append((td.name, model, sample_index, prompt_text, seed, temperature, disable_cache))

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
        if pool_size == 1:
            gen_results_iter = map(_generate_worker, gen_tasks)
        else:
            typer.echo(f"Generating with {pool_size} processes...")
            with multiprocessing.Pool(processes=pool_size) as pool:
                gen_results_iter = pool.map(_generate_worker, gen_tasks)
        for test_name, model, sample_index, prompt_text, meta, html in gen_results_iter:
            raw_path = out_dir / "raw" / test_name
            html_file = raw_path / f"{model}__s{sample_index}.html" if samples > 1 else raw_path / f"{model}.html"
            html_file.parent.mkdir(exist_ok=True, parents=True)
            html_file.write_text(html, encoding="utf-8")
            rec = ResultRecord(
                test_name=test_name,
                model_name=model,
                timestamp=datetime.utcnow(),
                generation_html_path=str(html_file),
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
            )
            results.append(json.loads(rec.model_dump_json()))

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
                "temperature": temperature,
                "base_seed": base_seed,
                "disable_cache": disable_cache,
                "processes_generation": (processes if processes is not None else min(multiprocessing.cpu_count(), len(gen_tasks))) if gen_tasks else None,
            },
            "prompting": {
                "system_prompt": generator.get_base_system_prompt(),
                "effective_system_prompt": generator.get_effective_system_prompt(),
                "custom_instructions": generator.get_custom_instructions(),
                "custom_instructions_path": custom_instructions_path,
            },
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

    # Map generation meta by triple for reuse
    gen_meta_map = {}
    for r in prior_data.get("results", []) if prior_data else []:
        key = (r.get("test_name"), r.get("model_name"), r.get("sample_index"))
        gen_meta_map[key] = r.get("generation")

    # Build evaluation task list
    tasks = []  # each entry: (html_path, test_js_path, screenshot_path, test_name, model, sample_index, gen_meta, prompt_text)
    for td in test_dirs:
        test_name = td.name
        test_js = td / "test.js"
        raw_dir = rd / "raw" / test_name
        if not raw_dir.exists():
            typer.secho(f"Skipping missing raw dir for test '{test_name}'", err=True)
            continue
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
            gen_meta = gen_meta_map.get((test_name, model, sample_index)) or {}
            tasks.append((str(hf), str(test_js), str(screenshot_path), test_name, model, sample_index, gen_meta, prompts_map.get(test_name, "")))

    # Sort tasks for deterministic ordering
    tasks.sort(key=lambda t: (t[3], t[4], t[5] if t[5] is not None else -1))


    all_results = []
    pass_map = {}  # (test_name, model) -> list[bool]
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
            for t in tasks:
                res, test_name, model, passed = _evaluate_worker(t)
                all_results.append(res)
                pass_map.setdefault((test_name, model), []).append(passed)
        else:
            typer.echo(f"Evaluating with {pool_size} processes...")
            with multiprocessing.Pool(processes=pool_size) as pool:
                for res, test_name, model, passed in pool.map(_evaluate_worker, tasks):
                    all_results.append(res)
                    pass_map.setdefault((test_name, model), []).append(passed)

    aggregates: List[dict] = []
    for (test_name, model), statuses in pass_map.items():
        c = sum(1 for x in statuses if x)
        n = len(statuses)
        pass_at = compute_pass_at_k(c, n, k_values)
        agg = AggregateRecord(
            test_name=test_name,
            model_name=model,
            n_samples=n,
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
