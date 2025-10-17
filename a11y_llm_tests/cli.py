"""Typer CLI for running evaluations and generating reports."""
import json
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


@app.command()
def run(
    models_file: str = typer.Option("config/models.yaml", help="Models config YAML"),
    out: str = typer.Option("runs", help="Output directory"),
    samples: int = typer.Option(1, min=1, help="Number of samples per (test,model)."),
    k: str = typer.Option("1,5,10", help="Comma-separated k values for pass@k metrics."),
    base_seed: int = typer.Option(None, help="Base seed for reproducibility; each sample adds its index."),
    temperature: float = typer.Option(None, help="Override model temperature (if supported)."),
    disable_cache: bool = typer.Option(False, help="Disable generation cache (always re-generate)."),
    test_cases_dir: str = typer.Option("test_cases", help="Directory containing test case folders."),
):
    """Execute all test cases against all configured models, optionally sampling multiple generations for pass@k metrics."""
    run_id = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
    out_dir = Path(out) / run_id
    (out_dir / "raw").mkdir(parents=True, exist_ok=True)
    (out_dir / "screenshots").mkdir(parents=True, exist_ok=True)

    models_cfg = yaml.safe_load(open(models_file))
    model_names = [m["name"] for m in models_cfg.get("models", [])]
    tcd = Path(test_cases_dir)
    test_dirs = [p for p in tcd.iterdir() if p.is_dir() and (p / "prompt.md").exists()]
    results = []  # per-sample ResultRecord JSON dicts
    aggregates: List[dict] = []
    k_values = [int(x.strip()) for x in k.split(",") if x.strip().isdigit()]
    if not k_values:
        k_values = [1]
    prompts_map = {}
    for td in test_dirs:
        prompt = (td / "prompt.md").read_text(encoding="utf-8")
        prompts_map[td.name] = prompt
        test_js = td / "test.js"
        test_name = td.name
        for model in model_names:
            pass_statuses = []  # track pass/fail for samples
            for sample_index in range(samples):
                seed = (base_seed + sample_index) if base_seed is not None else None
                html, meta = generator.generate_html_with_meta(
                    model,
                    prompt,
                    temperature=temperature,
                    seed=seed,
                    disable_cache=disable_cache,
                )
                cached = meta.get("cached", False)
                latency = meta.get("latency_s", 0.0)
                raw_path = out_dir / "raw" / test_name
                html_file = raw_path / f"{model}__s{sample_index}.html" if samples > 1 else raw_path / f"{model}.html"
                html_file.parent.mkdir(exist_ok=True, parents=True)
                # Persist HTML
                html_file.write_text(html, encoding="utf-8")
                screenshot_name = f"{test_name}__{model}__s{sample_index}.png" if samples > 1 else f"{test_name}__{model}.png"
                screenshot_path = out_dir / "screenshots" / screenshot_name
                screenshot_path.parent.mkdir(exist_ok=True, parents=True)
                node_res = node_bridge.run(html, str(test_js), str(screenshot_path))
                tf = node_res.get("testFunctionResult", {})
                assertions_raw = tf.get("assertions", [])
                # Normalize assertion types; default to 'R'
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
                )
                axe_data = node_res.get("axeResult") or node_res.get("axe_result") or node_res.get("axe")
                axe_obj = None
                if axe_data and isinstance(axe_data, dict):
                    axe_obj = AxeResult(
                        violation_count=axe_data.get("violation_count", 0),
                        violations=axe_data.get("violations", []),
                        best_practice_count=axe_data.get("best_practice_count", 0),
                        best_practice_violations=axe_data.get("best_practice_violations", []),
                    )
                result_pass = (test_result.status == "pass" and axe_obj.violation_count == 0)
                pass_statuses.append(result_pass)
                rec = ResultRecord(
                    test_name=test_name,
                    model_name=model,
                    timestamp=datetime.utcnow(),
                    generation_html_path=str(html_file),
                    screenshot_path=str(screenshot_path),
                    test_function=test_result,
                    axe=axe_obj,
                    result="PASS" if result_pass else "FAIL",
                    generation=GenerationMeta(
                        latency_s=latency,
                        prompt_hash=meta.get("prompt_hash", generator.prompt_hash(prompt)),
                        cached=cached,
                        tokens_in=meta.get("tokens_in"),
                        tokens_out=meta.get("tokens_out"),
                        total_tokens=meta.get("total_tokens"),
                        cost_usd=meta.get("cost_usd"),
                        seed=meta.get("seed"),
                        temperature=meta.get("temperature"),
                    ),
                    sample_index=sample_index,
                )
                results.append(json.loads(rec.model_dump_json()))
            # After sampling, compute aggregates
            c = sum(1 for x in pass_statuses if x)
            n = len(pass_statuses)
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

    run_json = {
        "run_id": run_id,
        "models": model_names,
        "tests": [d.name for d in test_dirs],
        "prompts": prompts_map,
        "results": results,
        "aggregates": aggregates,
        "meta": {
            "sampling": {
                "samples_per_case": samples,
                "k_values": k_values,
                "temperature": temperature,
                "base_seed": base_seed,
                "disable_cache": disable_cache,
            }
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
    from .report import render_report
    render_report(out_dir / "results.json", out_dir / "report.html")
    typer.echo(f"Run complete: {out_dir}/report.html")


@app.command()
def report(run_dir: str):
    """Regenerate HTML report for an existing run directory."""
    rd = Path(run_dir)
    from .report import render_report
    render_report(rd / "results.json", rd / "report.rebuilt.html")
    typer.echo("Report regenerated.")


def main():  # pragma: no cover
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
