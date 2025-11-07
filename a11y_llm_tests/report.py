"""HTML reporting for evaluation runs."""
from pathlib import Path
import orjson
from jinja2 import Template
from collections import OrderedDict
# importing os module for environment variables
import os

TEMPLATE = """<!DOCTYPE html>
<html lang=\"en\">
<head>
<meta charset=\"UTF-8\" />
<title>{{ site_name }}</title>
<base href=".">
<style>
:root {
  --bg-surface: #111827;
  --surface: #1f2937;
  --surface-muted: #283446;
  --border-subtle: #334155;
  --border-strong: #475569;
  --text-primary: #f9fafb;
  --text-secondary: #cbd5f5;
  --text-on-accent: #ffffff;
  --accent: #006aec;
  --accent-strong: #3b82f6;
  --pass: #0a8336;
  --fail: #a80000;
  --warn: #fbbf24;
  --badge-radius: 999px;
  --card-shadow: 0 12px 30px rgba(8, 47, 73, 0.35);
  --focus-ring: 0 0 0 3px rgba(29, 78, 216, 0.35);
  --link-text: #659fff;
}
* { box-sizing: border-box; }
body {
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  font-size: 16px;
  background: var(--bg-surface);
  color: var(--text-primary);
  margin: 0;
  line-height: 1.6;
}
a { color: var(--link-text); }
a:hover { color: var(--accent-strong); }
header, main, footer {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 1.5rem;
}
header { padding-top: 2.5rem; padding-bottom: 1.5rem; }
header h1 { margin: 0; font-size: 2.25rem; letter-spacing: -0.015em; }
p, ul, li { color: var(--text-secondary); }
main { padding-bottom: 3rem; }
section + section { margin-top: 2rem; }
table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  border: 1px solid var(--border-subtle);
  background: var(--surface);
  border-radius: 0.75rem;
  overflow: hidden;
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.1);
  margin-bottom: 1.5rem;
}
caption {
  text-align: left;
  padding: 1rem 1.25rem 0.5rem;
  font-weight: 700;
  font-size: 1.05rem;
  color: var(--text-primary);
}
thead th {
  background: var(--surface-muted);
  color: var(--text-primary);
  padding: 0.75rem 1rem;
  text-align: left;
  font-size: 0.95rem;
  border-bottom: 1px solid var(--border-subtle);
}
tbody td, tbody th {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-secondary);
  vertical-align: top;
}
tbody tr:last-child td, tbody tr:last-child th { border-bottom: none; }
tbody tr:nth-child(even) { background: rgba(15, 23, 42, 0.04); }
.badge-pass, .badge-fail {
  display: inline-flex;
  align-items: center;
  font-weight: 600;
  font-size: 0.85rem;
  padding: 0.15rem 0.6rem;
  border-radius: var(--badge-radius);
  letter-spacing: 0.01em;
}
.badge-pass { background: var(--pass); color: var(--text-on-accent); }
.badge-fail { background: var(--fail); color: var(--text-on-accent); }
code { font-size: 0.85rem; background: var(--surface-muted); padding: 0.1rem 0.35rem; border-radius: 0.35rem; }
details {
  border: 1px solid var(--border-subtle);
  border-radius: 0.75rem;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  background: var(--surface);
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.08);
}
details[open] {
  border-color: var(--accent-strong);
  box-shadow: 0 12px 24px rgba(37, 99, 235, 0.12);
}
details summary {
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  list-style: none;
}
details summary::-webkit-details-marker { display: none; }
details summary h2,
details summary h3,
details summary h4,
details summary h5 {
  display: inline-flex;
  margin: 0;
  font-size: 1.05rem;
  color: var(--text-primary);
}
details summary:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
  border-radius: 0.5rem;
}
tbody th { text-align: left; }
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: flex-end;
  padding: 1rem;
  background: var(--surface);
  border: 1px solid var(--border-subtle);
  border-radius: 0.75rem;
  box-shadow: 0 6px 20px rgba(15, 23, 42, 0.1);
  margin-bottom: 1rem;
}
.filters label {
  display: flex;
  flex-direction: column;
  font-weight: 600;
  font-size: 0.95rem;
  color: var(--text-primary);
}
.filters select {
  margin-top: 0.35rem;
  padding: 0.4rem 0.6rem;
  font-size: 0.95rem;
  border-radius: 0.5rem;
  border: 1px solid var(--border-strong);
  background: var(--surface-muted);
  color: var(--text-primary);
}
.filters button {
  padding: 0.45rem 0.9rem;
  font-size: 0.95rem;
  border-radius: 0.5rem;
  border: none;
  background: var(--accent);
  color: var(--text-on-accent);
  font-weight: 600;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.filters button:hover {
  transform: translateY(-1px);
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.22);
}
.filters button:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}
.filters-summary { margin: 1rem 0 0.5rem; font-size: 0.95rem; color: var(--text-primary); font-weight: 600; }
.samples {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1.25rem;
  margin-top: 1rem;
}
.sample-card {
  border-radius: 0.9rem;
  border: 1px solid var(--border-subtle);
  padding: 1rem;
  background: var(--surface);
  box-shadow: var(--card-shadow);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.sample-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 16px 32px rgba(15, 23, 42, 0.16);
}
.sample-card h4 {
  margin-top: 0;
  margin-bottom: 0.25rem;
  font-size: 1.05rem;
  color: var(--text-primary);
}
.sample-card p { margin: 0.35rem 0; color: var(--text-secondary); }
.pass-rate-bar {
  height: 12px;
  background: var(--surface-muted);
  position: relative;
  border-radius: 999px;
  overflow: hidden;
  margin: 1rem 0;
}
.pass-rate-bar span {
  position: absolute;
  inset: 0;
  background: var(--pass);
  transition: width 0.4s ease;
}
figure { margin: 0.75rem 0 0; }
figure img {
  width: 100%;
  border-radius: 0.75rem;
  border: 1px solid var(--border-subtle);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.2);
}
.prompt-block {
  white-space: pre-wrap;
  background: var(--surface-muted);
  padding: 0.85rem 1rem;
  border-radius: 0.75rem;
  border: 1px solid var(--border-subtle);
  font-size: 0.92rem;
  color: var(--text-primary);
  box-shadow: inset 0 1px 3px rgba(15, 23, 42, 0.12);
}
.agg-table { margin-top: 1rem; }
footer {
  padding: 2rem 1.5rem 3rem;
  color: var(--text-secondary);
}
footer a { color: var(--link-text); }
details ul { margin: 0.5rem 0 0.25rem; padding-left: 1.15rem; }
details li { margin-bottom: 0.35rem; }
@media (max-width: 768px) {
  header, main, footer { padding: 0 1rem; }
  header h1 { font-size: 1.75rem; }
  table, details { box-shadow: none; }
  .filters { padding: 0.75rem; }
}
</style>
</head>
<body>
<header>
<h1>{{ site_name }}</h1>
</header>
<main id=\"main\">
<section>
{% set total_samples = tests|length * n_samples %}
<p>All Models were tested against {{ tests|length }} test cases. Each test case was tested {{ n_samples }} times. This results in <strong>{{ total_samples }}</strong> total samples being evaluated per model.</p>
<table>
<thead>
<tr><th>Model</th><th>Rank</th><th>WCAG Pass Rate*</th><th>Avg Total WCAG Failures</th><th>Avg Axe WCAG Failures</th><th>Avg Assertion WCAG Failures</th><th>Avg Best Practice Failures</th></tr>
</thead>
<tbody>
{% for model, stats in summary.items() %}
<tr>
  <th>{{ model_display_names[model] }}</th>
  <td>{{ loop.index }}</td>
  <td>{{ "%.0f%%"|format(stats.pass_rate * 100) }}</td>
  <td>{{ "%.2f"|format(stats.avg_failures) }}</td>
  <td>{{ "%.2f"|format(stats.avg_axe_failures) }}</td>
  <td>{{ "%.2f"|format(stats.avg_assertion_failures) }}</td>
  <td>{{ "%.2f"|format(stats.avg_bp_failures) }}</td>
</tr>
{% endfor %}
</tbody>
</table>
<p>* These tests do not comprehensively test all WCAG requirements, only a subset of the most common issues. WCAG failures may still exist even for passing tests.</p>
{% if aggregates %}
<details>
  <summary><h2>Pass@k Aggregates</h2></summary>
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
  <td>{{ model_display_names[a.model_name] }}</td>
  <td>{{ a.n_samples }}</td>
  <td>{{ a.n_pass }}</td>
  {% for k,v in a.pass_at_k.items() %}
    <td>{{ '%.2f'|format(v) }}</td>
  {% endfor %}
  </tr>
  {% endfor %}
  </tbody>
  </table>
</details>
{% endif %}
</section>
<details open>
<summary><h2>Methodology</h2></summary>
  <p>This report shows how well various LLMs generate accessible HTML.</p>
  <ul>
    <li>Each test uses a prompt to generate HTML. The generated HTML is thentested for accessibility.</li>
    <li>The prompts intentionally do not include specific accessibility instructions. The goal is to see if the LLMs produce accessible HTML by default.</li>
    <li>The resulting HTML is rendered in a browser via Playwright (Chromium). This allows the HTML's JavaScript and CSS to execute, which can impact accessibility.</li>
    <li>The rendered HTML is evaluated using <a href="https://github.com/dequelabs/axe-core">axe-core</a> to identify common accessibility issues.</li>
    <li>A custom test script (JavaScript) is executed against the rendered page to check for accessibility requirements that are specific to the test case and not covered by axe-core. These tests look for <a href="https://www.w3.org/WAI/WCAG22/quickref/">WCAG 2.2</a>) failures and best practices. Best practices do not impact pass/fail results.</li>
    <li>Each test case is run multiple times (samples) to evaluate the consistency and reliability of the LLM's output.</li>
    <li>Default temperatures / settings are used for all models.</li>
  </ul>
  <p>All tests are automatic and deterministic (no human intervention). Only a fraction of accessibility requirements in WCAG can be covered in this way. Many requirements still need a human to evaluate. As such, these tests are not comprehensive. Even if a test passes, it may still fail WCAG and contain serious accessibility issues.</p>
  <p>Please leave feedback, review the source code, and contribute test cases, assertions, and other improvements at the <a href="https://github.com/microsoft/a11y-llm-eval">GitHub Project</a>.</p>
</details>
<details>
  <summary><h2>Glossary</h2></summary>
  <h3>Column Definitions</h3>
  <ul>
    <li><strong>Rank</strong>: The position of the model when sorted by WCAG Pass Rate (lower is better).</li>
    <li><strong>WCAG Pass Rate</strong>: The percentage of samples that passed all WCAG tests, including both axe-core WCAG checks and custom WCAG assertions. This does not include best practices.</li>
    <li><strong>Avg Total WCAG Failures</strong>: The average number of total WCAG failures (axe-core + assertions) per sample for the model. This does not include best practices.</li>
    <li><strong>Avg Axe WCAG Failures</strong>: The average number of axe-core detected WCAG failures per sample for the model. This does not include best practices.</li>
    <li><strong>Avg Assertion WCAG Failures</strong>: The average number of custom WCAG assertion failures per sample for the model. This does not include best practices.</li>
    <li><strong>Avg Best Practice Failures</strong>: The average number of best practice accessibility issues (informational only) per sample for the model. This includes axe-core best practices and best practice assertions.</li>
  </ul>

  <h3>Other Glossary Terms</h3>
  <ul>
    <li><strong>Assertion</strong>: A specific accessibility check defined in the test script. Each assertion checks for a particular accessibility requirement or best practice for the specific test case which is not already tested by axe.</li>
    <li><strong>Axe-core</strong>: An open-source accessibility testing engine developed by Deque Systems. It is widely used for automated accessibility testing of web applications. <a href="https://github.com/dequelabs/axe-core">Axe-core</a></li>
    <li><strong>Pass@k</strong>: A metric that estimates the likelihood of at least one sample passing a test when k samples are randomly selected.</li>
    <li><strong>WCAG</strong>: <a href=https://www.w3.org/WAI/WCAG22/quickref/">Web Content Accessibility Guidelines</a>, a set of guidelines for making web content more accessible to people with disabilities.</li>
    <li><strong>Test Case</strong>: A specific scenario designed to evaluate the accessibility of generated HTML content. Each test case includes a prompt, expected accessibility requirements, and a test script.</li>
  </ul>
</details>
<section>
<h2 id="details-h2">Detailed Results</h2>
<div class="filters" role="region" aria-label="Detailed results filters">
  <label>
    Model
    <select id="model-filter">
      <option value="">All models</option>
      {% for model, name in model_display_names|dictsort(by='value') %}
        <option value="{{ model }}">{{ name }}</option>
      {% endfor %}
    </select>
  </label>
  <label>
    Result
    <select id="result-filter">
      <option value="">All results</option>
      <option value="PASS">Pass</option>
      <option value="FAIL">Fail</option>
    </select>
  </label>
  <button type="button" id="reset-filters">Reset</button>
</div>
<p id="filter-count" class="filters-summary" aria-live="polite" aria-atomic="true"></p>
<p id="no-results-message" hidden>No samples match the current filters.</p>
{% for test_name, test_data in grouped_results.items() %}
<section>
  <details>
    <summary><h3>{{ test_name }}</h3></summary>
    {% if test_data.prompt %}
    <details>
      <summary>Prompt</summary>
      <pre class="prompt-block">{{ test_data.prompt }}</pre>
    </details>
    {% endif %}
    {% for group in test_data.models %}
    <details data-model-group="{{ group.model_name }}">
      <summary><h4>{{ model_display_names[group.model_name] }}</h4></summary>
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
        <div class="sample-card" data-model="{{ r.model_name }}" data-result="{{ r.result }}">
          {# Trim the first two path segments (e.g., 'runs/<run_id>/...') #}
          {% set _parts = r.generation_html_path.split('/') %}
          {% set _trimmed = '/'.join(_parts[2:]) %}
          <h4><a href="{{ _trimmed }}">Sample {{ r.sample_index if r.sample_index is not none else loop.index0 }}</a></h4>
          <p><span class="badge-{{ 'pass' if r.result=='PASS' else 'fail' }}">{{ r.result }}</span> | Latency {{ '%.2f'|format(r.generation.latency_s) }}s{% if r.generation.cached %} cached{% endif %}</p>
          <p>Axe WCAG: {{ r.axe.failure_count if r.axe else 'n/a' }}{% if r.axe and r.axe.best_practice_count > 0 %} | BP: {{ r.axe.best_practice_count }}{% endif %}{% if r.generation.cost_usd is not none %} | ${{ '%.4f'|format(r.generation.cost_usd) }}{% endif %}</p>
          {% if r.screenshot_path %}
            {# Trim the first two path segments (e.g., 'runs/<run_id>/...') #}
            {% set _parts = r.screenshot_path.split('/') %}
            {% set _trimmed = '/'.join(_parts[2:]) %}
            <figure>
              <img src="{{ _trimmed }}" alt="Screenshot sample {{ r.sample_index }} for {{ r.test_name }} / {{ model_display_names[r.model_name] }}" style="max-width:320px;">
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
          {% if r.axe.failure_count > 0 %}
          <details>
            <summary>Axe WCAG Failures ({{ r.axe.failure_count }}) <span role="img" aria-label="Fail">❌</span></summary>
            <ul>
              {% for v in r.axe.failures %}
              <li>({{ v.nodes|length }}x) - <strong>{{ v.id }}</strong> ({{ v.impact }}): {{ v.description }}</li>
              {% endfor %}
            </ul>
          </details>
          {% endif %}
          {% if r.axe.best_practice_count > 0 %}
          <details>
            <summary>Axe Best Practice Issues ({{ r.axe.best_practice_count }}) <span role="img" aria-label="Warning">⚠️</span></summary>
            <ul>
              {% for v in r.axe.best_practice_failures %}
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
  </details>
</section>
{% endfor %}
</section>
<section hidden>
  <details>
    <summary><h2>Costs</h2></summary>
    <table>
      <caption>Costs per model</caption>
      <thead>
        <tr><th>Model</th><th>Total Cost ($)</th><th>Avg Cost/Test ($)</th></tr>
      </thead>
      <tbody>
        {% for model, stats in summary.items() %}
        <tr>
          <th>{{ model_display_names[model] }}</th>
          <td>{{ "%.4f"|format(stats.total_cost) }}</td>
          <td>{{ "%.4f"|format(stats.avg_cost) }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </details>
</section>
</main>
<footer>
<p>GitHub Project: <a href="https://github.com/microsoft/a11y-llm-eval">a11y-llm-eval</a>. Run ID: {{ run_id }}</p>
{{ footer_content|safe }}
</footer>
<script>
document.addEventListener('DOMContentLoaded', function () {
  const modelFilter = document.getElementById('model-filter');
  const resultFilter = document.getElementById('result-filter');
  const resetButton = document.getElementById('reset-filters');
  const modelSections = Array.from(document.querySelectorAll('[data-model-group]'));
  const allCards = Array.from(document.querySelectorAll('.sample-card'));
  const noResultsMessage = document.getElementById('no-results-message');
  const countEl = document.getElementById('filter-count');
  const totalCardCount = allCards.length;

  function applyFilters() {
    const modelValue = modelFilter ? modelFilter.value : '';
    const resultValue = resultFilter ? resultFilter.value : '';
    let anyVisible = false;
    let visibleCardCount = 0;

    modelSections.forEach(function (section) {
      const cards = Array.from(section.querySelectorAll('.sample-card'));
      const sectionModel = section.getAttribute('data-model-group');
      let sectionHasVisibleCard = false;

      cards.forEach(function (card) {
        const cardModel = card.getAttribute('data-model');
        const cardResult = card.getAttribute('data-result');
        const matchesModel = !modelValue || cardModel === modelValue;
        const matchesResult = !resultValue || cardResult === resultValue;
        const shouldShowCard = matchesModel && matchesResult;

        card.style.display = shouldShowCard ? '' : 'none';
        if (shouldShowCard) {
          sectionHasVisibleCard = true;
          visibleCardCount += 1;
        }
      });

      const sectionMatchesModel = !modelValue || sectionModel === modelValue;
      const shouldShowSection = sectionMatchesModel && sectionHasVisibleCard;
      section.style.display = shouldShowSection ? '' : 'none';
      section.toggleAttribute('hidden', !shouldShowSection);

      if (shouldShowSection) {
        anyVisible = true;
      }
    });

    if (noResultsMessage) {
      noResultsMessage.hidden = anyVisible;
    }
    if (countEl) {
      const message = anyVisible ? `Showing ${visibleCardCount} of ${totalCardCount} samples` : `Showing 0 of ${totalCardCount} samples`;
      countEl.textContent = message;
    }
  }

  if (modelFilter) {
    modelFilter.addEventListener('change', applyFilters);
  }
  if (resultFilter) {
    resultFilter.addEventListener('change', applyFilters);
  }
  if (resetButton) {
    resetButton.addEventListener('click', function () {
      if (modelFilter) {
        modelFilter.value = '';
      }
      if (resultFilter) {
        resultFilter.value = '';
      }
      applyFilters();
    });
  }

  applyFilters();
});
</script>
</body>
</html>
"""

def render_report(run_json_path: Path, out_html: Path, models_cfg: dict):
    data = orjson.loads(run_json_path.read_bytes())
    from collections import defaultdict
    per_model = defaultdict(lambda: {
        "axe_failures": [], "total_test_function_passes": 0, "bp_passes": 0, "total": 0, "bp_total": 0,  "costs": [],
        "axe_bp_failures": [], "axe_bp_passes": 0, "axe_bp_total": 0, "total_axe_failures": 0,
        "total_failures": 0, "total_passes": 0, "total_assertion_bp_failures": 0,  "total_assertion_failures": 0
    })
    results = data.get("results", [])
    model_display_names = {}

    for m in models_cfg.get("models", []):
        model_name = m.get("name")
        display_name = m.get("display_name", model_name.split('/')[-1])
        model_display_names[model_name] = display_name

    for r in results:
        model = r["model_name"]
        per_model[model]["total"] += 1
        if r.get("result") == "PASS":
            per_model[model]["total_passes"] += 1
        # Determine test function pass count
        if r.get("test_function", {}).get("status") == "pass":
            per_model[model]["total_test_function_passes"] += 1
        # Track best-practice assertions pass rate separately
        assertions = r.get("test_function", {}).get("assertions", [])
        bp_assertions = [a for a in assertions if (a.get("type") or "R").upper() == "BP"]
        if bp_assertions:
            per_model[model]["bp_total"] += 1  # treat per-test BP status aggregate: pass if all BP pass
            if all(a.get("status") == "pass" for a in bp_assertions):
                per_model[model]["bp_passes"] += 1
        per_model[model]["total_assertion_bp_failures"] +=r.get("test_function", {}).get("total_assertion_bp_failures", 0)
        per_model[model]["total_assertion_failures"] +=r.get("test_function", {}).get("total_assertion_failures", 0)
        
        # Track axe failures (WCAG only now) and best practice failures
        axe = r.get("axe") or {}
        fc = axe.get("failure_count")  # WCAG failures only
        if fc is not None:
            per_model[model]["axe_failures"].append(axe.get("failures", []))
        per_model[model]["total_axe_failures"] += fc
        
        # Track axe best practice failures separately
        bp_fc = axe.get("best_practice_count", 0)
        per_model[model]["axe_bp_failures"].append(axe.get("best_practice_failures", []))
        per_model[model]["axe_bp_total"] += bp_fc
        if bp_fc == 0:
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
        avg_axe_failures = s["total_axe_failures"] / s["total"] if s["total"] else 0.0
        total_cost = sum(s["costs"]) if s["costs"] else 0.0
        avg_cost = (total_cost / s["total"]) if s["total"] else 0.0
        # Calculate combined best practice pass rate (custom BP assertions + axe BP failures)
        total_bp_failures = s["total_assertion_bp_failures"] + s["axe_bp_total"]
        total_axe_failures = s["total_axe_failures"]
        total_assertion_failures = s["total_assertion_failures"]
        total_assertion_bp_failures = s["total_assertion_bp_failures"]
        avg_assertion_failures = (total_assertion_failures / s["total"]) if s["total"] else 0.0
        avg_bp_failures = (total_bp_failures / s["total"]) if s["total"] else 0.0
        total_failures = total_assertion_failures + total_axe_failures
        avg_failures = (total_failures / s["total"]) if s["total"] else 0.0

        summary[m] = {
            "avg_axe_failures": avg_axe_failures,
            "pass_rate": s["total_passes"] / s["total"] if s["total"] else 0,
            "total_cost": total_cost,
            "avg_cost": avg_cost,
            "total_assertion_failures": total_assertion_failures,
            "total_assertion_bp_failures": total_assertion_bp_failures,
            "avg_assertion_failures": avg_assertion_failures,
            "avg_bp_failures": avg_bp_failures,
            "total_failures": total_failures,
            "avg_failures": avg_failures,
        }

    # Group samples by (test_name, model_name)
    grouped = {}
    for r in results:
        key = (r["test_name"], r["model_name"])
        grouped.setdefault(key, []).append(r)
    # Sort samples by sample_index if present
    grouped_results = OrderedDict()
    agg_index = {}
    # Enhance aggregates with display_model_name (provider prefix stripped)
    for a in data.get("aggregates", []) or []:
        agg_index[(a["test_name"], a["model_name"])] = a

    prompts_map = data.get("prompts", {}) or {}
    for (test_name, model_name), samples in sorted(grouped.items()):
        samples_sorted = sorted(
            samples, key=lambda x: (x.get("sample_index") is None, x.get("sample_index") or 0)
        )
        test_entry = grouped_results.setdefault(
            test_name,
            {
                "prompt": prompts_map.get(test_name),
                "models": [],
            },
        )
        test_entry["models"].append(
            {
                "model_name": model_name,
                "samples": samples_sorted,
                "aggregate": agg_index.get((test_name, model_name)),
            }
        )

    summary = OrderedDict(
        sorted(
            summary.items(),
            key=lambda item: (
                -item[1]["pass_rate"],   # higher pass_rate first
                item[1]["avg_failures"], # then lowest avg_failures
            ),
        )
    )
    
    html = Template(TEMPLATE).render(
        run_id=data.get("run_id", "unknown"),
        models=data.get("models", []),
        model_display_names=model_display_names,
        tests=data.get("tests", []),
        summary=summary,
        results=results,
        aggregates=data.get("aggregates", []),
        grouped_results=grouped_results,
        site_name=os.getenv("SITE_NAME", "A11y LLM Eval"),
        footer_content=os.getenv("FOOTER_CONTENT", ""),
        n_samples=data.get("meta").get("sampling").get("samples_per_case", 0),
    )
    out_html.write_text(html, encoding="utf-8")
