"""HTML reporting for evaluation runs."""
from pathlib import Path
import orjson
from jinja2 import Template

TEMPLATE = """<!DOCTYPE html>
<html lang=\"en\">
<head>
<meta charset=\"UTF-8\" />
<title>LLM Accessibility Evaluation Report</title>
<base href=".">
<style>
body { font-family: system-ui, sans-serif; line-height:1.4; }
table { border-collapse: collapse; width: 100%; }
th, td { border:1px solid #ccc; padding:4px 6px; vertical-align: top; }
th { background:#f2f2f2; }
.badge-pass { background:#007c00; color:#fff; padding:2px 6px; border-radius:4px; }
.badge-fail { background:#a00; color:#fff; padding:2px 6px; border-radius:4px; }
code { font-size: 0.85rem; }
header, main, footer { max-width: 1200px; margin: 0 auto; }
header:focus-within a.skip-link { top: 0; }
a.skip-link { position:absolute; left:0; top:-40px; background:#000; color:#fff; padding:8px; }
.agg-table { margin-top: 1rem; }
.samples { display:flex; flex-wrap:wrap; gap:1rem; }
.sample-card { border:1px solid #ddd; padding:0.5rem; border-radius:6px; width:360px; }
.sample-card h4 { margin:0 0 .25rem; font-size:1rem; }
.pass-rate-bar { height:8px; background:#eee; position:relative; border-radius:4px; overflow:hidden; margin-bottom:1rem; margin-top:1rem;}
.pass-rate-bar span { position:absolute; left:0; top:0; bottom:0; background:#0a0; }
details h3 { display:inline-block; }
details { border: 1px solid #ccc; border-radius: 4px; padding: 0.5rem; margin-bottom: 1rem; }
details summary { cursor: pointer; }
</style>
</head>
<body>
<a href=\"#main\" class=\"skip-link\">Skip to main content</a>
<header>
<h1>LLM Accessibility Evaluation</h1>
<p>Run ID: {{ run_id }}</p>
</header>
<main id=\"main\">
<section aria-labelledby=\"summary-h2\">
<h2 id=\"summary-h2\">Summary</h2>
<table aria-describedby=\"summary-caption\">
<caption id=\"summary-caption\">Average statistics per model</caption>
<thead>
<tr><th>Model</th><th>Avg Axe Violations</th><th>Custom Test Pass Rate</th><th>Best Practice Pass Rate</th><th>Total Cost ($)</th><th>Avg Cost/Test ($)</th></tr>
</thead>
<tbody>
{% for model, stats in summary.items() %}
<tr>
  <th>{{ stats.display_name }}</th>
  <td>{{ "%.2f"|format(stats.avg_violations) }}</td>
  <td>{{ "%.0f%%"|format(stats.req_pass_rate * 100) }}</td>
  <td>{{ "%.0f%%"|format(stats.bp_pass_rate * 100) }}</td>
  <td>{{ "%.4f"|format(stats.total_cost) }}</td>
  <td>{{ "%.4f"|format(stats.avg_cost) }}</td>
</tr>
{% endfor %}
</tbody>
</table>
{% if aggregates %}
<h3>Pass@k Aggregates</h3>
<p>Pass@k is a formula that determines the likelyhood that if you pick random k samples from the set, then at least one of them would pass. For example, pass@10=.50 means that there is a 50 percent likelyhood that at least 1 of the 10 randomly selected samples from the set would pass.</p>
<p>Pass@K is a metric used to evaluate the performance of code generation models, especially in scenarios where multiple code samples are generated for a single problem.</p>
<table class="agg-table">
<thead>
<tr>
  <th>Test</th><th>Model</th><th>Samples</th><th>Passes</th>
  {% if aggregates and aggregates[0].pass_at_k %}
    {% for k,v in aggregates[0].pass_at_k.items() %}
      <th>pass@{{ k }}</th>
    {% endfor %}
  {% endif %}
</tr>
</thead>
<tbody>
{% for a in aggregates %}
<tr>
 <td>{{ a.test_name }}</td>
 <td>{{ a.display_model_name }}</td>
 <td>{{ a.n_samples }}</td>
 <td>{{ a.n_pass }}</td>
 {% for k,v in a.pass_at_k.items() %}
   <td>{{ '%.3f'|format(v) }}</td>
 {% endfor %}
</tr>
{% endfor %}
</tbody>
</table>
{% endif %}
</section>
<section aria-labelledby=\"details-h2\">
<h2>Methodology</h2>
<p>This report shows how well various LLMs generate accessible HTML.</p>
<ul>
  <li>Each test uses a prompt to generate HTML. These prompts do not contain any accessibility guidance.</li>
  <li>The resulting HTML is rendered in a browser via Playwright (Chromium). This allows the HTML's JavaScript and CSS to execute, which can impact accessibility.</li>
  <li>The rendered HTML is evaluated using <a href="https://github.com/dequelabs/axe-core">axe-core</a> to identify common accessibility issues.</li>
  <li>A custom test script (JavaScript) is executed against the rendered page to check for accessibility requirements that are specific to the test case and not covered by axe-core. These tests look for <a href="https://www.w3.org/WAI/WCAG22/quickref/">WCAG 2.2</a>) failures and best practices. Best practices do not impact pass/fail results.</li>
  <li>Each test case is run multiple times (samples) with different random seeds to evaluate the consistency and reliability of the LLM's output.</li>
</ul>
<p>All tests are automatic and deterministic (no human intervention). Only a fraction of accessibility requirements in WCAG can be covered in this way. Many requirements still need a human to evaluate. As such, these tests are not comprehensive. Even if a test passes, it may still fail WCAG and contain serious accessibility issues.</p>
<p>Please leave feedback, review the source code, and contribute test cases, assertions, and other improvements at the <a href="https://github.com/mfairchild365/a11y-llm-tests">GitHub Project</a>.</p>
<h2 id=\"details-h2\">Detailed Results</h2>
{% for group in grouped_results %}
<details>
  <summary><h3>{{ group.test_name }} — {{ group.display_model_name }}</h3></summary>
  {% if group.prompt %}
  <details>
    <summary>Prompt</summary>
    <pre style="white-space:pre-wrap; background:#f9f9f9; padding:.5rem; border:1px solid #ddd;">{{ group.prompt }}</pre>
  </details>
  {% endif %}
  {% set agg = group.aggregate %}
  {% if agg %}
  <p>Samples: {{ agg.n_samples }} | Passes: {{ agg.n_pass }}</p>
  <table>
    <thead><tr>{% for k,v in agg.pass_at_k.items() %}<th>pass@{{ k }}</th>{% endfor %}</tr></thead>
    <tbody><tr>{% for k,v in agg.pass_at_k.items() %}<td>{{ '%.3f'|format(v) }}</td>{% endfor %}</tr></tbody>
  </table>
  {% set _percent = (100.0 * (agg.n_pass / agg.n_samples)) if agg.n_samples else 0 %}
  <div class="pass-rate-bar" role="img" aria-label="Pass ratio - {{ _percent }} percent"><span style="width: {{ _percent }}%"></span></div>
  {% endif %}
  <div class="samples">
  {% for r in group.samples %}
    <div class="sample-card">
      {# Trim the first two path segments (e.g., 'runs/<run_id>/...') #}
      {% set _parts = r.generation_html_path.split('/') %}
      {% set _trimmed = '/'.join(_parts[2:]) %}
      <h4><a href="{{ _trimmed }}">Sample {{ r.sample_index if r.sample_index is not none else loop.index0 }}</a></h4>
      <p><span class="badge-{{ 'pass' if r.result=='PASS' else 'fail' }}">{{ r.result }}</span> | Latency {{ '%.2f'|format(r.generation.latency_s) }}s{% if r.generation.cached %} cached{% endif %}</p>
      <p>Axe WCAG: {{ r.axe.violation_count if r.axe else 'n/a' }}{% if r.axe and r.axe.best_practice_count > 0 %} | BP: {{ r.axe.best_practice_count }}{% endif %}{% if r.generation.cost_usd is not none %} | ${{ '%.4f'|format(r.generation.cost_usd) }}{% endif %}</p>
      {% if r.screenshot_path %}
        {# Trim the first two path segments (e.g., 'runs/<run_id>/...') #}
        {% set _parts = r.screenshot_path.split('/') %}
        {% set _trimmed = '/'.join(_parts[2:]) %}
      <figure>
        <img src="{{ _trimmed }}" alt="Screenshot sample {{ r.sample_index }} for {{ r.test_name }} / {{ r.model_name }}" style="max-width:320px;">
      </figure>
      {% endif %}
      <details>
        <summary>
          Assertions
          {% if r.test_function.status == "fail" %}
            <span role="img" aria-label="Fail">❌</span>
          {% elif r.test_function.status == "pass" %}
            <span role="img" aria-label="Pass">✅</span>
          {% endif %}
        </summary>
        <ul>
          {% for a in r.test_function.assertions %}
          <li>
            {% if a.status == "fail" %}
              <span role="img" aria-label="Fail">❌</span>:
            {% elif a.status == "pass" %}
              <span role="img" aria-label="Pass">✅</span>:
            {% endif %}
            {{ a.name }} ({{ a.type if a.type else 'R' }}): {{ a.status }}
            {% if a.message %} - {{ a.message }}{% endif %}
          </li>
          {% endfor %}
        </ul>
      </details>
      {% if r.axe %}
      {% if r.axe.violation_count > 0 %}
      <details>
        <summary>Axe WCAG Violations ({{ r.axe.violation_count }}) <span role="img" aria-label="Fail">❌</span></summary>
        <ul>
          {% for v in r.axe.violations %}
          <li>({{ v.nodes|length }}x) - <strong>{{ v.id }}</strong> ({{ v.impact }}): {{ v.description }}</li>
          {% endfor %}
        </ul>
      </details>
      {% endif %}
      {% if r.axe.best_practice_count > 0 %}
      <details>
        <summary>Axe Best Practice Issues ({{ r.axe.best_practice_count }}) <span role="img" aria-label="Warning">⚠️</span></summary>
        <ul>
          {% for v in r.axe.best_practice_violations %}
          <li><strong>{{ v.id }}</strong> ({{ v.impact }}): {{ v.description }} <em>(Best Practice - does not affect pass/fail)</em></li>
          {% endfor %}
        </ul>
      </details>
      {% endif %}
      {% endif %}
    </div>
  {% endfor %}
  </div>
</details>
{% endfor %}
</section>
</main>
<footer>
<p>GitHub Project: <a href="https://github.com/mfairchild365/a11y-llm-tests">a11y-llm-tests</a>.</p>
</footer>
</body>
</html>
"""


def render_report(run_json_path: Path, out_html: Path):
    data = orjson.loads(run_json_path.read_bytes())
    from collections import defaultdict
    per_model = defaultdict(lambda: {
        "violations": [], "req_passes": 0, "bp_passes": 0, "total": 0, "bp_total": 0, "costs": [],
        "bp_violations": [], "axe_bp_passes": 0, "axe_bp_total": 0
    })
    results = data.get("results", [])
    for r in results:
        model = r["model_name"]
        per_model[model]["total"] += 1
        # Determine requirement pass (test_function.status already excludes BP failures)
        if r.get("test_function", {}).get("status") == "pass":
            per_model[model]["req_passes"] += 1
        # Track best-practice assertions pass rate separately
        assertions = r.get("test_function", {}).get("assertions", [])
        bp_assertions = [a for a in assertions if (a.get("type") or "R").upper() == "BP"]
        if bp_assertions:
            per_model[model]["bp_total"] += 1  # treat per-test BP status aggregate: pass if all BP pass
            if all(a.get("status") == "pass" for a in bp_assertions):
                per_model[model]["bp_passes"] += 1
        
        # Track axe violations (WCAG only now) and best practice violations
        axe = r.get("axe") or {}
        vc = axe.get("violation_count")  # WCAG violations only
        if vc is not None:
            per_model[model]["violations"].append(vc)
        
        # Track axe best practice violations separately
        bp_vc = axe.get("best_practice_count", 0)
        per_model[model]["bp_violations"].append(bp_vc)
        per_model[model]["axe_bp_total"] += 1
        if bp_vc == 0:
            per_model[model]["axe_bp_passes"] += 1
        gen = r.get("generation", {})
        cost = gen.get("cost_usd")
        if cost is not None:
            try:
                per_model[model]["costs"].append(float(cost))
            except (TypeError, ValueError):
                pass
    # create summary
    summary = {}
    for m, s in per_model.items():
        avg_v = sum(s["violations"]) / len(s["violations"]) if s["violations"] else 0
        total_cost = sum(s["costs"]) if s["costs"] else 0.0
        avg_cost = (total_cost / s["total"]) if s["total"] else 0.0
        # Calculate combined best practice pass rate (custom BP assertions + axe BP violations)
        total_bp_tests = s["bp_total"] + s["axe_bp_total"]
        total_bp_passes = s["bp_passes"] + s["axe_bp_passes"]
        combined_bp_pass_rate = (total_bp_passes / total_bp_tests) if total_bp_tests else 1.0
        
        summary[m] = {
            "avg_violations": avg_v,
            "req_pass_rate": s["req_passes"] / s["total"] if s["total"] else 0,
            # Combined BP pass rate: custom BP assertions AND axe best practice violations
            "bp_pass_rate": combined_bp_pass_rate,
            "total_cost": total_cost,
            "avg_cost": avg_cost,
            "display_name": m.split('/')[-1],
        }

    # Group samples by (test_name, model_name)
    grouped = {}
    for r in results:
        key = (r["test_name"], r["model_name"])
        grouped.setdefault(key, []).append(r)
    # Sort samples by sample_index if present
    grouped_results = []
    agg_index = {}
    # Enhance aggregates with display_model_name (provider prefix stripped)
    for a in data.get("aggregates", []) or []:
        a["display_model_name"] = a["model_name"].split('/')[-1]
        agg_index[(a["test_name"], a["model_name"])] = a

    prompts_map = data.get("prompts", {}) or {}
    for (test_name, model_name), samples in sorted(grouped.items()):
        samples_sorted = sorted(
            samples, key=lambda x: (x.get("sample_index") is None, x.get("sample_index") or 0)
        )
        grouped_results.append(
            {
                "test_name": test_name,
                "model_name": model_name,
                "display_model_name": model_name.split('/')[-1],
                "samples": samples_sorted,
                "aggregate": agg_index.get((test_name, model_name)),
                "prompt": prompts_map.get(test_name),
            }
        )

    html = Template(TEMPLATE).render(
        run_id=data.get("run_id", "unknown"),
        models=data.get("models", []),
        tests=data.get("tests", []),
        summary=summary,
        results=results,
        aggregates=data.get("aggregates", []),
        grouped_results=grouped_results,
    )
    out_html.write_text(html, encoding="utf-8")
