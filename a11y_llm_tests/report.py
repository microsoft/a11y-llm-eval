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
  --heatmap-low: #2d3748; /* fallback low value */
  --heatmap-high: #16a34a; /* fallback high value */
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
summary { cursor: pointer;}
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
/* Heatmap cells for pass@k tables */
.pass-at-k-cell {
  transition: background-color 0.25s ease, color 0.25s ease;
  text-align: center;
  font-weight: 600;
}
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
  <th>{{ model_display_names.get(model, model) }}</th>
  <td>{{ loop.index }}</td>
  <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(stats.pass_rate) }}">{{ "%.0f%%"|format(stats.pass_rate * 100) }}</td>
  <td>{{ "%.2f"|format(stats.avg_failures) }}</td>
  <td>{{ "%.2f"|format(stats.avg_axe_failures) }}</td>
  <td>{{ "%.2f"|format(stats.avg_assertion_failures) }}</td>
  <td>{{ "%.2f"|format(stats.avg_bp_failures) }}</td>
</tr>
{% endfor %}
</tbody>
</table>
<p>* These tests do not comprehensively test all WCAG requirements, only a subset of the most common issues. WCAG failures may still exist even for passing tests.</p>
{% if aggregates_by_test %}
<details>
  <summary><h2>Pass@k Aggregates</h2></summary>
  <p>Pass@k is a formula that determines the likelihood that if you pick random k samples from the set, then at least one of them would pass. For example, pass@10=.50 means that there is a 50 percent likelihood that at least 1 of the 10 randomly selected samples from the set would pass.</p>
  <p>Pass@K is a metric used to evaluate the performance of models when multiple samples are generated per test case.</p>
  {% for test_name, info in aggregates_by_test.items() %}
    <table class="agg-table">
      <caption>{{ test_name }}</caption>
      <thead>
        <tr>
          <th>Model</th>
          <th>Samples</th>
          <th>Passes</th>
          {% for k in info.ks %}
            <th>pass@{{ k }}</th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for a in info.rows %}
        <tr>
          <td>{{ model_display_names.get(a.model_name, a.model_name) }}</td>
          <td>{{ a.n_samples }}</td>
          <td>{{ a.n_pass }}</td>
          {% for k in info.ks %}
            {% set v = a.pass_at_k.get(k) %}
            <td class="pass-at-k-cell" data-pass-at-k="{{ k }}" data-pass="{% if v is not none %}{{ '%.4f'|format(v) }}{% else %}{% endif %}">{% if v is not none %}{{ '%.0f%%'|format(v * 100) }}{% else %}-{% endif %}</td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
  {% endfor %}
</details>
{% endif %}

{% if variant_comparisons %}
<details>
  <summary><h2>Instruction Benchmarks (vs Control)</h2></summary>
  <p>This section compares each instruction set (system prompt append) against the control configuration. Sample counts may differ between variants.</p>
  {% for v in variant_comparisons %}
    <h3>{{ v.name }}</h3>
    {% if v.description %}<p>{{ v.description }}</p>{% endif %}
    {% if v.n_samples_requested %}<p><strong>Variant samples per (test, model):</strong> {{ v.n_samples_requested }}</p>{% endif %}
    <table>
      <thead>
        <tr>
          <th>Model</th>
          <th>Control Pass Rate</th>
          <th>{{ v.name }} Pass Rate</th>
          <th>Δ Pass Rate</th>
        </tr>
      </thead>
      <tbody>
        {% for row in v.rows %}
        <tr>
          <th>{{ row.model_display }}</th>
          <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(row.control_pass_rate) }}">{{ '%.0f%%'|format(row.control_pass_rate * 100) }}</td>
          <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(row.variant_pass_rate) }}">{{ '%.0f%%'|format(row.variant_pass_rate * 100) }}</td>
          <td>{{ '%+.1fpp'|format(row.delta_pass_rate * 100) }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  {% endfor %}
</details>
{% endif %}
</section>
<section>
<details open>
  <summary><h2>Analysis</h2></summary>
  <p>This section summarizes where models perform well, where they struggle, and the most frequent types of accessibility issues observed across all samples.</p>

  <p><strong>Interpretation.</strong>
  {% if global_hardest_tests %}
    The hardest test cases overall are
    {% for row in global_hardest_tests %}
      {{ row.test_name }}{% if not loop.last %}, {% endif %}
    {% endfor %}, where models still fail WCAG checks more often than elsewhere.
  {% endif %}
  {% if per_model_easiest %}
    Across models, the strongest areas tend to be the “easiest tests by model” listed below, indicating patterns the models already handle relatively well.
  {% endif %}
  {% if common_axe_failures %}
    The most frequent WCAG issues involve axe-core rules such as
    {% for f in common_axe_failures[:3] %}
      {{ f.id }}{% if not loop.last %}, {% endif %}
    {% endfor %}, highlighting recurring accessibility gaps in the generated HTML.
  {% endif %}
  </p>

  {% if global_hardest_tests %}
  <h3>Where models can improve the most (hardest tests)</h3>
  <table>
    <thead>
      <tr>
        <th>Test case</th>
        <th>Overall WCAG pass rate</th>
        <th>Avg WCAG failures / sample</th>
        <th>Best model</th>
        <th>Best model pass rate</th>
        <th>Hardest model</th>
        <th>Hardest model pass rate</th>
      </tr>
    </thead>
    <tbody>
      {% for row in global_hardest_tests %}
      <tr>
        <th>{{ row.test_name }}</th>
        <td>{{ "%.0f%%"|format(row.pass_rate * 100) }}</td>
        <td>{{ "%.2f"|format(row.avg_wcag_failures) }}</td>
        <td>{% if row.best_model %}{{ model_display_names.get(row.best_model, row.best_model) }}{% else %}-{% endif %}</td>
        <td>{% if row.best_model_pass_rate is not none %}{{ "%.0f%%"|format(row.best_model_pass_rate * 100) }}{% else %}-{% endif %}</td>
        <td>{% if row.worst_model %}{{ model_display_names.get(row.worst_model, row.worst_model) }}{% else %}-{% endif %}</td>
        <td>{% if row.worst_model_pass_rate is not none %}{{ "%.0f%%"|format(row.worst_model_pass_rate * 100) }}{% else %}-{% endif %}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}

  {% if per_model_hardest %}
  <h3>Hardest tests by model</h3>
  <table>
    <thead>
      <tr>
        <th>Model</th>
        <th>Most challenging test cases</th>
      </tr>
    </thead>
    <tbody>
      {% for model, tests_info in per_model_hardest.items() %}
      <tr>
        <th>{{ model_display_names.get(model, model) }}</th>
        <td>
          {% if tests_info %}
            {% for t in tests_info %}
              {{ t.test_name }} ({{ "%.0f%%"|format(t.pass_rate * 100) }}{% if not loop.last %}, {% endif %})
            {% endfor %}
          {% else %}
            -
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}

  {% if per_model_easiest %}
  <h3>Where models perform well (easiest tests by model)</h3>
  <table>
    <thead>
      <tr>
        <th>Model</th>
        <th>Strongest test cases</th>
      </tr>
    </thead>
    <tbody>
      {% for model, tests_info in per_model_easiest.items() %}
      <tr>
        <th>{{ model_display_names.get(model, model) }}</th>
        <td>
          {% if tests_info %}
            {% for t in tests_info %}
              {{ t.test_name }} ({{ "%.0f%%"|format(t.pass_rate * 100) }}{% if not loop.last %}, {% endif %})
            {% endfor %}
          {% else %}
            -
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}

  {% if common_axe_failures %}
  <h3>Most common WCAG failures (axe-core)</h3>
  <table>
    <thead>
      <tr>
        <th>Rule</th>
        <th>Impact</th>
        <th>Total occurrences</th>
        <th>Models affected</th>
        <th>Tests affected</th>
        <th>Description</th>
      </tr>
    </thead>
    <tbody>
      {% for f in common_axe_failures %}
      <tr>
        <th>{{ f.id }}</th>
        <td>{{ f.impact or "-" }}</td>
        <td>{{ f.count }}</td>
        <td>{{ f.n_models }}</td>
        <td>{{ f.n_tests }}</td>
        <td>{{ f.description or "" }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}

  {% if common_axe_bp_failures %}
  <h3>Most common best-practice issues (axe-core)</h3>
  <table>
    <thead>
      <tr>
        <th>Rule</th>
        <th>Impact</th>
        <th>Total occurrences</th>
        <th>Models affected</th>
        <th>Tests affected</th>
        <th>Description</th>
      </tr>
    </thead>
    <tbody>
      {% for f in common_axe_bp_failures %}
      <tr>
        <th>{{ f.id }}</th>
        <td>{{ f.impact or "-" }}</td>
        <td>{{ f.count }}</td>
        <td>{{ f.n_models }}</td>
        <td>{{ f.n_tests }}</td>
        <td>{{ f.description or "" }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}

  {% if analysis_assertions_by_test %}
  <h3>Assertion-level patterns (per test case)</h3>
  {% for test_name, assertions in analysis_assertions_by_test.items() %}
    {% if assertions %}
      <h4>{{ test_name }}</h4>
      <table>
        <thead>
          <tr>
            <th>Assertion</th>
            <th>Type</th>
            <th>Failure rate</th>
            <th>Failures / total</th>
          </tr>
        </thead>
        <tbody>
          {% for a in assertions %}
          <tr>
            <th>{{ a.name }}</th>
            <td>{{ a.type }}</td>
            <td>{{ "%.0f%%"|format(a.fail_rate * 100) }}</td>
            <td>{{ a.fail_count }} / {{ a.total }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      <p><small>Assertion statistics are computed within this test case only and are not compared across different test cases.</small></p>
    {% endif %}
  {% endfor %}
  {% endif %}
</details>
</section>
<details open>
<summary><h2>Methodology</h2></summary>
  <p>This report shows how well various LLMs generate accessible HTML.</p>
  <ul>
    <li>Each test uses a prompt to generate HTML. The generated HTML is then tested for accessibility.</li>
    <li>The prompts intentionally do not include specific accessibility instructions. The goal is to see if the LLMs produce accessible HTML by default.</li>
    <li>The resulting HTML is rendered in a browser via Playwright (Chromium). This allows the HTML's JavaScript and CSS to execute, which can impact accessibility.</li>
    <li>The rendered HTML is evaluated using <a href="https://github.com/dequelabs/axe-core">axe-core</a> to identify common accessibility issues.</li>
    <li>A custom test script (JavaScript) is executed against the rendered page to check for accessibility requirements that are specific to the test case and not covered by axe-core. These tests look for <a href="https://www.w3.org/WAI/WCAG22/quickref/">WCAG 2.2</a> failures and best practices. Best practices do not impact pass/fail results.</li>
    <li>Each test case is run multiple times (samples) to evaluate the consistency and reliability of the LLM's output.</li>
    <li>Default temperatures / settings are used for all models.</li>
  </ul>
  {% set system_prompt = prompting_meta.get('system_prompt') %}
  {% set effective_system_prompt = prompting_meta.get('effective_system_prompt') %}
  {% set display_system_prompt = effective_system_prompt or system_prompt %}
  {% set custom_instructions = prompting_meta.get('custom_instructions') %}
  {% set custom_instructions_path = prompting_meta.get('custom_instructions_path') %}
  {% if display_system_prompt %}
  <details>
    <summary><h3>System Prompt</h3></summary>
    <pre class="prompt-block">{{ display_system_prompt|e }}</pre>
    {% if effective_system_prompt and system_prompt and effective_system_prompt != system_prompt %}
    <p><small>The effective system prompt shown includes custom instructions.</small></p>
    {% endif %}
  </details>
  {% endif %}
  {% if custom_instructions %}
  <details>
    <summary><h3>Custom Instructions</h3></summary>
    <pre class="prompt-block">{{ custom_instructions }}</pre>
    {% if custom_instructions_path %}
    <p><small>Source: {{ custom_instructions_path }}</small></p>
    {% endif %}
  </details>
  {% endif %}
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
    {% set assertion_names = assertion_names_by_test.get(test_name) %}
    {% if assertion_names %}
    <div class="filters assertion-filters" role="region" aria-label="Filters for assertions in {{ test_name }} test case">
      <label>
        Assertion
        <select class="assertion-name-filter">
          <option value="">All assertions</option>
          {% for assertion_name in assertion_names|sort %}
            <option value="{{ assertion_name }}">{{ assertion_name }}</option>
          {% endfor %}
        </select>
      </label>
      <label>
        Assertion result
        <select class="assertion-status-filter">
          <option value="">All results</option>
          <option value="pass">Pass</option>
          <option value="fail">Fail</option>
        </select>
      </label>
      <button type="button" class="assertion-reset-filters">Reset</button>
    </div>
    <p class="filters-summary assertion-filter-count" aria-live="polite" aria-atomic="true"></p>
    {% endif %}
    {% if test_data.prompt %}
    <details>
      <summary>Prompt</summary>
      <pre class="prompt-block">{{ test_data.prompt|e }}</pre>
    </details>
    {% endif %}
    {% for group in test_data.models %}
    {% set agg = group.aggregate %}
    <details data-model-group="{{ group.model_name }}">
      <summary>
        <h4>
          {{ model_display_names.get(group.model_name, group.model_name) }}
          {% if agg and agg.n_samples %}
            &nbsp;—&nbsp;{{ '%.0f%%'|format((agg.n_pass / agg.n_samples) * 100) }}
          {% endif %}
        </h4>
      </summary>
      {% if agg %}
      <p>Samples: {{ agg.n_samples }} | Passes: {{ agg.n_pass }}</p>
      <table>
        <thead><tr>{% for k,v in agg.pass_at_k.items() %}<th>pass@{{ k }}</th>{% endfor %}</tr></thead>
        <tbody><tr>{% for k,v in agg.pass_at_k.items() %}
          <td class="pass-at-k-cell" data-pass-at-k="{{ k }}" data-pass="{{ '%.4f'|format(v) }}">{{ '%.0f%%'|format(v * 100) }}</td>
        {% endfor %}</tr></tbody>
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
          <h4><a href="{{ _trimmed }}">Sample {{ r.sample_index if r.sample_index is not none else loop.index0 }} ({{ model_display_names.get(r.model_name, r.model_name) }})</a></h4>
          <p><span class="badge-{{ 'pass' if r.result=='PASS' else 'fail' }}">{{ r.result }}</span> | Latency {{ '%.2f'|format(r.generation.latency_s) }}s{% if r.generation.cached %} cached{% endif %}</p>
          <p>Axe WCAG: {{ r.axe.failure_count if r.axe else 'n/a' }}{% if r.axe and r.axe.best_practice_count > 0 %} | BP: {{ r.axe.best_practice_count }}{% endif %}{% if r.generation.cost_usd is not none %} | ${{ '%.4f'|format(r.generation.cost_usd) }}{% endif %}</p>
          {% if r.screenshot_path %}
            {# Trim the first two path segments (e.g., 'runs/<run_id>/...') #}
            {% set _parts = r.screenshot_path.split('/') %}
            {% set _trimmed = '/'.join(_parts[2:]) %}
            <figure>
              <img src="{{ _trimmed }}" alt="Screenshot sample {{ r.sample_index }} for {{ r.test_name }} / {{ model_display_names.get(r.model_name, r.model_name) }}" style="max-width:320px;">
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
              <li data-assertion-name="{{ a.name }}" data-assertion-status="{{ a.status }}">
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
          <th>{{ model_display_names.get(model, model) }}</th>
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
        const hiddenByAssertion = card.classList.contains('hidden-by-assertion');
        const shouldShowCard = matchesModel && matchesResult && !hiddenByAssertion;

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

    updateAssertionCounts();
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
  const assertionFilterContainers = Array.from(document.querySelectorAll('.assertion-filters'));

  assertionFilterContainers.forEach(function (container) {
    const nameFilter = container.querySelector('.assertion-name-filter');
    const statusFilter = container.querySelector('.assertion-status-filter');
    const resetAssertionButton = container.querySelector('.assertion-reset-filters');
    const testCaseSection = container.closest('section');
    if (!testCaseSection) return;

    const sampleCards = Array.from(testCaseSection.querySelectorAll('.sample-card'));

    function applyAssertionFilters() {
      const nameValue = nameFilter ? nameFilter.value : '';
      const statusValue = statusFilter ? statusFilter.value : '';

      sampleCards.forEach(function (card) {
        const assertionItems = Array.from(card.querySelectorAll('li[data-assertion-name][data-assertion-status]'));
        let matches = true;

        if (nameValue || statusValue) {
          matches = assertionItems.some(function (item) {
            const itemName = item.getAttribute('data-assertion-name') || '';
            const itemStatus = item.getAttribute('data-assertion-status') || '';
            const matchesName = !nameValue || itemName === nameValue;
            const matchesStatus = !statusValue || itemStatus === statusValue;
            return matchesName && matchesStatus;
          });
        }

        card.classList.toggle('hidden-by-assertion', !matches);
      });

      applyFilters();
    }

    if (nameFilter) {
      nameFilter.addEventListener('change', applyAssertionFilters);
    }
    if (statusFilter) {
      statusFilter.addEventListener('change', applyAssertionFilters);
    }
    if (resetAssertionButton) {
      resetAssertionButton.addEventListener('click', function () {
        if (nameFilter) {
          nameFilter.value = '';
        }
        if (statusFilter) {
          statusFilter.value = '';
        }
        sampleCards.forEach(function (card) {
          card.classList.remove('hidden-by-assertion');
        });
        applyFilters();
      });
    }

    applyAssertionFilters();
  });

  function updateAssertionCounts() {
    const containers = Array.from(document.querySelectorAll('.assertion-filters'));
    containers.forEach(function (container) {
      const summaryEl = container.parentElement.querySelector('.assertion-filter-count');
      if (!summaryEl) return;
      const testCaseSection = container.closest('section');
      if (!testCaseSection) return;
      const cards = Array.from(testCaseSection.querySelectorAll('.sample-card'));
      const total = cards.length;
      let visible = 0;
      cards.forEach(function (card) {
        if (card.style.display !== 'none') {
          visible += 1;
        }
      });
      if (!total) {
        summaryEl.textContent = '';
      } else {
        summaryEl.textContent = `Showing ${visible} of ${total} samples in this test case`;
      }
    });
  }
});
</script>
<script>
// Heatmap coloring for pass@k cells: maps 0.0-1.0 to a green-ish scale and ensures text contrast
document.addEventListener('DOMContentLoaded', function () {
  function lerp(a, b, t) { return a + (b - a) * t; }
  function hexToRgb(hex) {
    const h = hex.replace('#','');
    return [parseInt(h.substring(0,2),16), parseInt(h.substring(2,4),16), parseInt(h.substring(4,6),16)];
  }
  function rgbToHex(r,g,b){
    return '#' + [r,g,b].map(x=>{ const s = Math.round(x).toString(16); return s.length===1 ? '0'+s : s; }).join('');
  }
  function luminance(r,g,b){
    const rs = r/255, gs = g/255, bs = b/255;
    const a = [rs,gs,bs].map(c=> c <= 0.03928 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4));
    return 0.2126*a[0] + 0.7152*a[1] + 0.0722*a[2];
  }
  function contrastRatio(l1, l2){
    const hi = Math.max(l1,l2), lo = Math.min(l1,l2);
    return (hi + 0.05) / (lo + 0.05);
  }

  // Define heatmap endpoints
  const lowColor = getComputedStyle(document.documentElement).getPropertyValue('--heatmap-low').trim() || '#2d3748';
  const highColor = getComputedStyle(document.documentElement).getPropertyValue('--heatmap-high').trim() || '#16a34a';
  const lowRgb = hexToRgb(lowColor.replace(/\s/g,''));
  const highRgb = hexToRgb(highColor.replace(/\s/g,''));

  const cells = Array.from(document.querySelectorAll('.pass-at-k-cell'));
  cells.forEach(function(cell){
    const v = cell.getAttribute('data-pass');
    if (!v) return;
    const t = Math.min(1, Math.max(0, parseFloat(v)));
    const r = lerp(lowRgb[0], highRgb[0], t);
    const g = lerp(lowRgb[1], highRgb[1], t);
    const b = lerp(lowRgb[2], highRgb[2], t);
    const bg = rgbToHex(r,g,b);
    cell.style.backgroundColor = bg;
    // compute readable foreground (black or white) based on WCAG contrast
    const Lbg = luminance(r,g,b);
    const Lwhite = luminance(255,255,255);
    const Lblack = luminance(0,0,0);
    const contrastWithWhite = contrastRatio(Lwhite, Lbg);
    const contrastWithBlack = contrastRatio(Lblack, Lbg);
    const fg = contrastWithWhite >= contrastWithBlack ? '#ffffff' : '#000000';
    cell.style.color = fg;
  });
});
</script>
</body>
</html>
"""

def render_report(run_json_path: Path, out_html: Path, models_cfg: dict):
  data = orjson.loads(run_json_path.read_bytes())
  meta_block = data.get("meta") or {}
  sampling_meta = meta_block.get("sampling") or {}
  prompting_meta = meta_block.get("prompting") or {}
  from collections import defaultdict

  all_results = data.get("results", []) or []

  def _variant_id(r: dict) -> str:
    return (r.get("prompt_variant_id") or "control")

  control_results = [r for r in all_results if _variant_id(r) == "control"]
  results_by_variant = defaultdict(list)
  for r in all_results:
    results_by_variant[_variant_id(r)].append(r)

  all_aggregates = data.get("aggregates", []) or []
  control_aggregates = [a for a in all_aggregates if (a.get("prompt_variant_id") or "control") == "control"]

  prompt_variants_meta = meta_block.get("prompt_variants") or []
  prompt_variant_meta_by_id = {}
  for pv in prompt_variants_meta:
    if isinstance(pv, dict) and pv.get("id"):
      prompt_variant_meta_by_id[pv.get("id")] = pv

  variant_ids = [vid for vid in results_by_variant.keys() if vid != "control"]

  # Main report content uses control-only results.
  results = control_results

  assertion_names_by_test = defaultdict(set)
  for r in results:
    test_name = r.get("test_name")
    if not test_name:
      continue
    assertions = r.get("test_function", {}).get("assertions", [])
    for a in assertions:
      name = a.get("name")
      if name:
        assertion_names_by_test[test_name].add(name)

  # Build display name mapping with precedence:
  # 1. Stored meta.models_info
  # 2. Provided models_cfg
  # 3. Fallback to last path segment of model name
  model_display_names = {}
  for m in (meta_block.get("models_info") or []):
    name = m.get("name")
    if not name:
      continue
    model_display_names[name] = m.get("display_name") or name.split('/')[-1]
    model_display_names[name.split('/')[-1]] = m.get("display_name") or name.split('/')[-1]
  for m in (models_cfg.get("models") or []):
    name = m.get("name")
    if not name:
      continue
    display = m.get("display_name") or model_display_names.get(name) or name.split('/')[-1]
    model_display_names[name] = display
  # Ensure any model appearing only in results has a mapping
  for r in all_results:
    n = r.get("model_name")
    if n and n not in model_display_names:
      model_display_names[n] = n.split('/')[-1]
  
  per_model = defaultdict(lambda: {
    "axe_failures": [],
    "total_test_function_passes": 0,
    "bp_passes": 0,
    "total": 0,
    "bp_total": 0,
    "costs": [],
    "axe_bp_failures": [],
    "axe_bp_passes": 0,
    "axe_bp_total": 0,
    "total_axe_failures": 0,
    "total_failures": 0,
    "total_passes": 0,
    "total_assertion_bp_failures": 0,
    "total_assertion_failures": 0,
  })

  for r in results:
    model = r.get("model_name")
    if not model:
      continue
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
      per_model[model]["bp_total"] += 1 # treat per-test BP status aggregate: pass if all BP pass
      if all(a.get("status") == "pass" for a in bp_assertions):
        per_model[model]["bp_passes"] += 1
    per_model[model]["total_assertion_bp_failures"] += r.get("test_function", {}).get("total_assertion_bp_failures", 0)
    per_model[model]["total_assertion_failures"] += r.get("test_function", {}).get("total_assertion_failures", 0)
    # Track axe failures (WCAG only now) and best practice failures
    axe = r.get("axe") or {}
    fc = axe.get("failure_count")
    if fc is not None:
      per_model[model]["axe_failures"].append(axe.get("failures", []))
    per_model[model]["total_axe_failures"] += (fc or 0)
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
  # Build per-test/per-model stats and failure patterns for analysis
  test_model_stats = defaultdict(lambda: defaultdict(lambda: {
    "n_samples": 0,
    "n_pass": 0,
    "total_wcag_failures": 0.0,
    "total_axe_failures": 0.0,
    "total_assertion_failures": 0.0,
  }))

  assertion_stats_by_test = defaultdict(lambda: defaultdict(lambda: {
    "fail": 0,
    "total": 0,
    "type": "R",
  }))

  axe_wcag_failure_stats = {}
  axe_bp_failure_stats = {}

  for r in results:
    test_name = r.get("test_name")
    model = r.get("model_name")
    if not test_name or not model:
      continue

    stats = test_model_stats[test_name][model]
    stats["n_samples"] += 1
    if r.get("result") == "PASS":
      stats["n_pass"] += 1

    tf = r.get("test_function") or {}
    assertion_failures = tf.get("total_assertion_failures") or 0
    stats["total_assertion_failures"] += assertion_failures

    axe = r.get("axe") or {}
    axe_failures = axe.get("failure_count") or 0
    stats["total_axe_failures"] += axe_failures
    stats["total_wcag_failures"] += (assertion_failures + axe_failures)

    # Assertion-level stats (per test case only)
    for a in tf.get("assertions") or []:
      name = a.get("name")
      if not name:
        continue
      atype = (a.get("type") or "R").upper()
      a_stats = assertion_stats_by_test[test_name][name]
      a_stats["total"] += 1
      if a.get("status") == "fail":
        a_stats["fail"] += 1
      a_stats["type"] = atype

    # Axe WCAG failure patterns
    if axe:
      for v in axe.get("failures") or []:
        vid = v.get("id") or "unknown"
        entry = axe_wcag_failure_stats.setdefault(vid, {
          "count": 0,
          "models": set(),
          "tests": set(),
          "impact": v.get("impact"),
          "description": v.get("description"),
        })
        entry["count"] += 1
        entry["models"].add(model)
        entry["tests"].add(test_name)

      for v in axe.get("best_practice_failures") or []:
        vid = v.get("id") or "unknown"
        entry = axe_bp_failure_stats.setdefault(vid, {
          "count": 0,
          "models": set(),
          "tests": set(),
          "impact": v.get("impact"),
          "description": v.get("description"),
        })
        entry["count"] += 1
        entry["models"].add(model)
        entry["tests"].add(test_name)

  # create summary
  summary = {}
  for m, s in per_model.items():
    avg_axe_failures = s["total_axe_failures"] / s["total"] if s["total"] else 0.0
    total_cost = sum(s["costs"]) if s["costs"] else 0.0
    avg_cost = (total_cost / s["total"]) if s["total"] else 0.0
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
    key = (r.get("test_name"), r.get("model_name"))
    grouped.setdefault(key, []).append(r)
  # Sort samples by sample_index if present
  grouped_results = OrderedDict()
  agg_index = {}
  # Enhance aggregates with display_model_name (provider prefix stripped)
  for a in (control_aggregates or []):
    agg_index[(a.get("test_name"), a.get("model_name"))] = a

  prompts_map = (data.get("prompts") or {})
  for (test_name, model_name), samples in sorted(grouped.items()):
    samples_sorted = sorted(samples, key=lambda x: (x.get("sample_index") is None, x.get("sample_index") or 0))
    test_entry = grouped_results.setdefault(test_name, {"prompt": prompts_map.get(test_name), "models": []})
    test_entry["models"].append({
      "model_name": model_name,
      "samples": samples_sorted,
      "aggregate": agg_index.get((test_name, model_name)),
    })

  summary = OrderedDict(sorted(summary.items(), key=lambda item: (-item[1]["pass_rate"], item[1]["avg_failures"])) )

  # Variant comparisons (instruction sets) vs control
  variant_comparisons = []
  if variant_ids:
    def _compute_summary_simple(sub_results):
      pm = defaultdict(lambda: {
        "total": 0,
        "total_passes": 0,
        "total_axe_failures": 0,
        "total_assertion_failures": 0,
        "total_assertion_bp_failures": 0,
        "axe_bp_total": 0,
      })
      for rr in sub_results:
        model = rr.get("model_name")
        if not model:
          continue
        pm[model]["total"] += 1
        if rr.get("result") == "PASS":
          pm[model]["total_passes"] += 1
        tf = rr.get("test_function") or {}
        pm[model]["total_assertion_failures"] += tf.get("total_assertion_failures", 0)
        pm[model]["total_assertion_bp_failures"] += tf.get("total_assertion_bp_failures", 0)
        axe = rr.get("axe") or {}
        pm[model]["total_axe_failures"] += (axe.get("failure_count") or 0)
        pm[model]["axe_bp_total"] += (axe.get("best_practice_count") or 0)

      out = {}
      for m, s in pm.items():
        total = s["total"] or 0
        pass_rate = (s["total_passes"] / total) if total else 0.0
        total_bp_failures = s["total_assertion_bp_failures"] + s["axe_bp_total"]
        total_failures = s["total_assertion_failures"] + s["total_axe_failures"]
        out[m] = {
          "pass_rate": pass_rate,
          "avg_failures": (total_failures / total) if total else 0.0,
        }
      return out

    control_summary_simple = _compute_summary_simple(control_results)
    for vid in sorted(variant_ids):
      v_results = results_by_variant.get(vid) or []
      v_summary_simple = _compute_summary_simple(v_results)
      pv = prompt_variant_meta_by_id.get(vid) or {}
      model_union = sorted(set(control_summary_simple.keys()) | set(v_summary_simple.keys()))
      rows = []
      for model in model_union:
        c = control_summary_simple.get(model) or {"pass_rate": 0.0, "avg_failures": 0.0}
        v = v_summary_simple.get(model) or {"pass_rate": 0.0, "avg_failures": 0.0}
        rows.append({
          "model_name": model,
          "model_display": model_display_names.get(model, model),
          "control_pass_rate": c["pass_rate"],
          "variant_pass_rate": v["pass_rate"],
          "delta_pass_rate": v["pass_rate"] - c["pass_rate"],
          "control_avg_failures": c["avg_failures"],
          "variant_avg_failures": v["avg_failures"],
          "delta_avg_failures": v["avg_failures"] - c["avg_failures"],
        })
      variant_comparisons.append({
        "id": vid,
        "name": pv.get("name") or vid,
        "description": pv.get("description"),
        "n_samples_requested": pv.get("n_samples_requested"),
        "rows": rows,
      })
  # Build aggregates_by_test: for each test, list all models and their aggregates (ensures unique table per test)
  aggregates_by_test = OrderedDict()
  tests_in_order = list(grouped_results.keys())
  for test_name in tests_in_order:
    models_info = grouped_results.get(test_name, {}).get('models', [])
    rows = []
    ks_set = []
    for m in models_info:
      model_name = m.get('model_name')
      agg = agg_index.get((test_name, model_name))
      if agg:
        pass_at_k = agg.get('pass_at_k') or {}
        # preserve order of keys as they appear; avoid duplicates
        for k in pass_at_k.keys():
          if k not in ks_set:
            ks_set.append(k)
        rows.append({
          'model_name': model_name,
          'n_samples': agg.get('n_samples', 0),
          'n_pass': agg.get('n_pass', 0),
          'pass_at_k': pass_at_k,
        })
      else:
        rows.append({
          'model_name': model_name,
          'n_samples': 0,
          'n_pass': 0,
          'pass_at_k': {},
        })
    # try to sort ks numerically when possible
    try:
      ks_sorted = sorted(ks_set, key=lambda x: int(x))
    except Exception:
      ks_sorted = sorted(ks_set)
    aggregates_by_test[test_name] = {'rows': rows, 'ks': ks_sorted}

  # Convert assertion_names_by_test sets to sorted lists for template rendering
  assertion_names_by_test = {k: sorted(v) for k, v in assertion_names_by_test.items()}

  # Global test-level difficulty across all models
  global_test_stats = []
  for test_name, models_stats in test_model_stats.items():
    total_samples = sum(s["n_samples"] for s in models_stats.values())
    if not total_samples:
      continue
    total_pass = sum(s["n_pass"] for s in models_stats.values())
    total_wcag_failures = sum(s["total_wcag_failures"] for s in models_stats.values())
    pass_rate = (total_pass / total_samples) if total_samples else 0.0
    avg_wcag_failures = (total_wcag_failures / total_samples) if total_samples else 0.0

    best_model = None
    best_rate = None
    worst_model = None
    worst_rate = None
    for model, s in models_stats.items():
      if not s["n_samples"]:
        continue
      pr = s["n_pass"] / s["n_samples"]
      if best_rate is None or pr > best_rate:
        best_rate = pr
        best_model = model
      if worst_rate is None or pr < worst_rate:
        worst_rate = pr
        worst_model = model

    global_test_stats.append({
      "test_name": test_name,
      "pass_rate": pass_rate,
      "avg_wcag_failures": avg_wcag_failures,
      "best_model": best_model,
      "best_model_pass_rate": best_rate,
      "worst_model": worst_model,
      "worst_model_pass_rate": worst_rate,
    })
  # Hardest tests: only include cases where there is room to improve
  hardest_candidates = [
    t for t in global_test_stats
    if (t["pass_rate"] < 1.0) or (t["avg_wcag_failures"] > 0.0)
  ]

  global_hardest_tests = sorted(
    hardest_candidates,
    key=lambda x: (x["pass_rate"], -x["avg_wcag_failures"]),
  )[:5]

  # Easiest tests: exclude any test that already appears in the hardest list
  hardest_names = {t["test_name"] for t in global_hardest_tests}
  easiest_candidates = [
    t for t in global_test_stats
    if t["test_name"] not in hardest_names
  ]

  global_easiest_tests = sorted(
    easiest_candidates,
    key=lambda x: (-x["pass_rate"], x["avg_wcag_failures"]),
  )[:5]

  # Per-model hardest/easiest tests
  per_model_tests = defaultdict(list)
  for test_name, models_stats in test_model_stats.items():
    for model, s in models_stats.items():
      if not s["n_samples"]:
        continue
      pr = s["n_pass"] / s["n_samples"]
      avg_wcag = (s["total_wcag_failures"] / s["n_samples"]) if s["n_samples"] else 0.0
      per_model_tests[model].append({
        "test_name": test_name,
        "pass_rate": pr,
        "avg_wcag_failures": avg_wcag,
      })

  per_model_hardest = {}
  per_model_easiest = {}
  for model, tests in per_model_tests.items():
    if not tests:
      per_model_hardest[model] = []
      per_model_easiest[model] = []
      continue

    sorted_tests = sorted(tests, key=lambda x: (x["pass_rate"], -x["avg_wcag_failures"]))

    # Easiest per model: tests with pass rate >= 80%
    easiest = []
    for t in reversed(sorted_tests):  # start from highest pass rate
      if t["pass_rate"] >= 0.80:
        easiest.append(t)
      if len(easiest) >= 3:
        break
    per_model_easiest[model] = easiest

    # Hardest per model: exclude any test that qualifies as "easiest" (>= 80% pass)
    easiest_names_model = {t["test_name"] for t in easiest}
    hardest = []
    for t in sorted_tests:  # from lowest pass rate upward
      if t["test_name"] in easiest_names_model:
        continue
      # Only include genuinely difficult tests (some failures)
      if t["pass_rate"] < 1.0 or t["avg_wcag_failures"] > 0.0:
        hardest.append(t)
      if len(hardest) >= 3:
        break
    per_model_hardest[model] = hardest

  # Common axe-core failure patterns
  def _prepare_axe_list(src_dict, limit=10):
    items = []
    for rid, info in src_dict.items():
      items.append({
        "id": rid,
        "count": info.get("count", 0),
        "impact": info.get("impact"),
        "description": info.get("description"),
        "n_models": len(info.get("models") or []),
        "n_tests": len(info.get("tests") or []),
      })
    items.sort(key=lambda x: (-x["count"], x["id"]))
    return items[:limit]

  common_axe_failures = _prepare_axe_list(axe_wcag_failure_stats)
  common_axe_bp_failures = _prepare_axe_list(axe_bp_failure_stats)

  # Assertion-level analysis per test case (not compared across tests)
  analysis_assertions_by_test = {}
  for test_name, assertions in assertion_stats_by_test.items():
    rows = []
    for name, s in assertions.items():
      if not s["total"]:
        continue
      fail_rate = s["fail"] / s["total"]
      rows.append({
        "name": name,
        "type": s.get("type") or "R",
        "fail_rate": fail_rate,
        "fail_count": s["fail"],
        "total": s["total"],
      })
    rows.sort(key=lambda x: (-x["fail_rate"], -x["fail_count"], x["name"]))
    analysis_assertions_by_test[test_name] = rows[:5]

  html = Template(TEMPLATE).render(
    run_id=data.get("run_id", "unknown"),
    models=data.get("models", []),
    model_display_names=model_display_names,
    tests=data.get("tests", []),
    summary=summary,
    results=results,
    aggregates=control_aggregates,
    aggregates_by_test=aggregates_by_test,
    grouped_results=grouped_results,
    assertion_names_by_test=assertion_names_by_test,
    site_name=os.getenv("SITE_NAME", "A11y LLM Eval"),
    footer_content=os.getenv("FOOTER_CONTENT", ""),
    n_samples=sampling_meta.get("samples_per_case", 0),
    prompting_meta=prompting_meta,
    global_hardest_tests=global_hardest_tests,
    global_easiest_tests=global_easiest_tests,
    per_model_hardest=per_model_hardest,
    per_model_easiest=per_model_easiest,
    common_axe_failures=common_axe_failures,
    common_axe_bp_failures=common_axe_bp_failures,
    analysis_assertions_by_test=analysis_assertions_by_test,
    variant_comparisons=variant_comparisons,
  )
  out_html.write_text(html, encoding="utf-8")
