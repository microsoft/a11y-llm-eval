"""HTML reporting for evaluation runs."""
from pathlib import Path
import re
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
.badge-pass, .badge-fail, .badge-na {
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
.badge-na { background: var(--warn); color: #1f2937; }
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
.transcript-summary {
  margin-top: 0.75rem;
  font-size: 0.92rem;
}
.transcript-meta {
  color: var(--text-secondary);
  margin: 0.35rem 0 0.65rem;
}
.transcript-turns {
  display: grid;
  gap: 0.35rem;
}
.transcript-turn {
  padding: 0.35rem 0.65rem;
  border-left: 3px solid var(--border-subtle);
  background: color-mix(in srgb, var(--surface-muted) 50%, transparent);
  border-radius: 0 0.4rem 0.4rem 0;
}
.transcript-turn-header {
  margin: 0;
  font-size: 0.75rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-primary);
}
.transcript-turn-msg {
  margin: 0.15rem 0;
  font-size: 0.88rem;
  color: var(--text-secondary);
  line-height: 1.45;
}
.transcript-turn-msg-label {
  font-weight: 600;
  font-size: 0.8rem;
  color: var(--text-primary);
}
.transcript-turn-prompt {
  margin: 0.2rem 0 0;
}
.transcript-tool-list {
  margin: 0.15rem 0 0;
  font-size: 0.82rem;
  color: #d97706;
  white-space: pre-wrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  line-height: 1.4;
}
.transcript-turn-system { border-left-color: #64748b; }
.transcript-turn-user { border-left-color: #2563eb; }
.transcript-turn-assistant { border-left-color: #16a34a; }
.agg-table { margin-top: 1rem; }
/* Heatmap cells for pass@k tables */
.pass-at-k-cell {
  transition: background-color 0.25s ease, color 0.25s ease;
  text-align: center;
  font-weight: 600;
}
.pass-rate-note {
  margin: 0.35rem 0 1.25rem;
  padding: 0.65rem 0.9rem;
  border-left: 3px solid var(--border-strong);
  background: color-mix(in srgb, var(--surface) 85%, transparent);
  color: var(--text-secondary);
  font-size: 0.85rem;
  border-radius: 0.35rem;
}
.pass-rate-note strong { color: var(--text-primary); }

/* Report navigation (single page) */
.report-nav {
  margin: 1rem 0 1.25rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 0.5rem;
  border: 1px solid var(--border-subtle);
  border-radius: 0.85rem;
  background: color-mix(in srgb, var(--surface) 92%, transparent);
  position: sticky;
  top: 0.5rem;
  z-index: 20;
  backdrop-filter: blur(6px);
}
.report-nav a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.45rem 0.85rem;
  border-radius: 0.65rem;
  border: 1px solid var(--border-subtle);
  background: var(--surface);
  color: var(--text-primary);
  font-weight: 700;
  text-decoration: none;
}
.report-nav a:hover {
  border-color: var(--border-strong);
  background: var(--surface-muted);
}
.report-nav a:focus-visible {
  box-shadow: var(--focus-ring);
}
.report-nav a[aria-current="page"] {
  background: var(--accent);
  border-color: var(--accent-strong);
  color: var(--text-on-accent);
}

[data-report-section][hidden] {
  display: none !important;
}

/* Keep anchor targets visible below sticky nav */
section[id], h2[id], h3[id] {
  scroll-margin-top: 5rem;
}
footer {
  padding: 2rem 1.5rem 3rem;
  color: var(--text-secondary);
}
footer a { color: var(--link-text); }
details ul { margin: 0.5rem 0 0.25rem; padding-left: 1.15rem; }
details li { margin-bottom: 0.35rem; }
.assertion-message-block { margin-top: 0.2rem; }
.assertion-message-list { margin-top: 0.35rem; }
.assertion-message-list li { margin-bottom: 0.2rem; }
@media (max-width: 768px) {
  header, main, footer { padding: 0 1rem; }
  header h1 { font-size: 1.75rem; }
  table, details { box-shadow: none; }
  .filters { padding: 0.75rem; }
  .report-nav {
    flex-wrap: nowrap;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: thin;
  }
  .report-nav a { white-space: nowrap; }
}
</style>
</head>
<body>
{% macro pass_rate_note() -%}
<p class="pass-rate-note"><strong>* Pass rate</strong> reflects only this harness's automated checks (a curated set of axe-core WCAG rules plus hand-written assertions per test case). Automated testing can detect only a subset of accessibility issues: 100% here means the sample passed every check that was run, <strong>not</strong> that the page is WCAG conformant or fully accessible.</p>
{%- endmacro %}
<header>
<h1>{{ site_name }}</h1>
</header>
<main id=\"main\">

<nav class="report-nav" aria-label="Report sections">
  <a href="index.html#control-summary" data-report-nav="control">Control</a>
  {% if instruction_benchmark_rows or instruction_set_analysis %}
  <a href="index.html#instruction-sets" data-report-nav="instructions">Instruction sets</a>
  {% endif %}
  {% if skill_benchmark_tables %}
  <a href="index.html#skills" data-report-nav="skills">Skills</a>
  {% endif %}
  <a href="index.html#details-h2" data-report-nav="details">Detailed results</a>
  <a href="index.html#methodology" data-report-nav="about">Methodology &amp; glossary</a>
</nav>

<section id="control-section" data-report-section="control">

<section id="control-summary">
<h2>Control summary</h2>
{% set total_samples = tests|length * n_samples %}
<p>Control results show how well models produce accessible code with no instructions or prompts to specifically create accessible code. Models are ranked by WCAG pass rate across {{ tests|length }} test cases and {{ n_samples }} samples per test ({{ total_samples }} samples per model). These tests do not comprehensively test all WCAG requirements, only a subset of the most common issues. WCAG failures may still exist even for passing tests.</p>
<table>
<thead>
<tr><th>Model</th><th>Rank</th><th>Pass rate*</th><th>Avg Total WCAG Failures</th><th>Avg Axe WCAG Failures</th><th>Avg Assertion WCAG Failures</th><th>Avg Best Practice Failures</th></tr>
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
{{ pass_rate_note() }}

{% if aggregates_by_test %}
<details>
  <summary><h3>Pass@k aggregates</h3></summary>
  <p>Pass@k estimates the probability that at least one of <em>k</em> randomly selected samples passes. This is computed from control samples only.</p>
  {% for test_name, info in aggregates_by_test.items() %}
    <table class="agg-table">
      <caption>{{ test_name }}</caption>
      <thead>
        <tr>
          <th>Model</th>
          <th>Samples</th>
          <th>Passes</th>
          {% for k in info.ks %}
            <th>pass@{{ k }}*</th>
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
            <td class="pass-at-k-cell" data-pass-at-k="{{ k }}" data-pass="{% if v is not none %}{{ '%.4f'|format(v) }}{% endif %}">{% if v is not none %}{{ '%.0f%%'|format(v * 100) }}{% else %}-{% endif %}</td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
  {% endfor %}
  {{ pass_rate_note() }}
</details>
{% endif %}

{% if global_hardest_tests or per_model_hardest or per_model_easiest or common_axe_failures or common_axe_bp_failures or analysis_assertions_by_test %}
<details>
  <summary><h3>Control analysis</h3></summary>
  <p>This section summarizes where models perform well, where they struggle, and the most frequent types of accessibility issues observed across all samples.</p>

  {% if common_axe_failures %}
  <h3>Most common axe WCAG failures</h3>
  <table>
    <thead>
      <tr>
        <th>Rule</th>
        <th>Impact</th>
        <th>Failures</th>
        <th>% of failures</th>
        <th>Seen in models</th>
        <th>Seen in test cases</th>
        <th>Description</th>
      </tr>
    </thead>
    <tbody>
      {% for f in common_axe_failures %}
      <tr>
        <th>{{ f.id }}</th>
        <td>{{ f.impact or '' }}</td>
        <td>{{ f.count }}</td>
        <td>{% if f.percent is not none %}{{ '%.1f%%'|format(f.percent * 100) }}{% else %}&mdash;{% endif %}</td>
        <td>{{ f.n_models }}</td>
        <td>{{ f.n_tests }}</td>
        <td class="note">{{ f.description or '' }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% endif %}

  {% if common_axe_bp_failures %}
  <h3>Most common axe best-practice failures</h3>
  <table>
    <thead>
      <tr>
        <th>Rule</th>
        <th>Impact</th>
        <th>Failures</th>
        <th>% of failures</th>
        <th>Seen in models</th>
        <th>Seen in test cases</th>
        <th>Description</th>
      </tr>
    </thead>
    <tbody>
      {% for f in common_axe_bp_failures %}
      <tr>
        <th>{{ f.id }}</th>
        <td>{{ f.impact or '' }}</td>
        <td>{{ f.count }}</td>
        <td>{% if f.percent is not none %}{{ '%.1f%%'|format(f.percent * 100) }}{% else %}&mdash;{% endif %}</td>
        <td>{{ f.n_models }}</td>
        <td>{{ f.n_tests }}</td>
        <td class="note">{{ f.description or '' }}</td>
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
            <th>Failures / applicable</th>
            <th>Not applicable</th>
          </tr>
        </thead>
        <tbody>
          {% for a in assertions %}
          <tr>
            <th>{{ a.name }}</th>
            <td>{{ a.type }}</td>
            <td>{% if a.fail_rate is not none %}{{ "%.0f%%"|format(a.fail_rate * 100) }}{% else %}-{% endif %}</td>
            <td>{{ a.fail_count }} / {{ a.applicable_total }}</td>
            <td>{{ a.na_count }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      <p><small>Assertion statistics are computed within this test case only and are not compared across different test cases.</small></p>
    {% endif %}
  {% endfor %}
  {% endif %}
</details>
{% endif %}
</section>

</section>

<section id="report-about" data-report-section="about">
<h2 id="methodology">Methodology</h2>
  <p>This report shows how well various LLMs generate accessible HTML.</p>
  <ul>
    <li>Each test uses a prompt to generate HTML. The generated HTML is then tested for accessibility.</li>
    <li>The prompts intentionally do not include specific accessibility instructions. The goal is to see if the LLMs produce accessible HTML by default.</li>
    <li><strong>Control (one-shot):</strong> Each model receives a single prompt and produces HTML in one turn with no tool use or iteration. This measures baseline accessibility out of the box.</li>
    <li><strong>Variants and skills (Copilot agent):</strong> Variant and skill samples are generated by the GitHub Copilot SDK as agentic sessions. The agent can take multiple turns, call its built-in tools, and iteratively refine the HTML before submitting a final result.</li>
    <li>The resulting HTML is rendered in a browser via Playwright (Chromium). This allows the HTML's JavaScript and CSS to execute, which can impact accessibility.</li>
    <li>The rendered HTML is evaluated using <a href="https://github.com/dequelabs/axe-core">axe-core</a> to identify common accessibility issues.</li>
    <li>A custom test script (JavaScript) is executed against the rendered page to check for accessibility requirements that are specific to the test case and not covered by axe-core. These tests look for <a href="https://www.w3.org/WAI/WCAG22/quickref/">WCAG 2.2</a> failures and best practices. Best practices do not impact pass/fail results.</li>
    <li>Each test case is run multiple times (samples) to evaluate the consistency and reliability of the LLM's output.</li>
    <li>By default, the harness does not explicitly set a temperature, so each provider/model uses its own default sampling behavior.</li>
  </ul>
  {% set output_format_instructions = prompting_meta.get('output_format_instructions') or prompting_meta.get('system_prompt') %}
  {% set effective_output_format_instructions = prompting_meta.get('effective_output_format_instructions') or prompting_meta.get('effective_system_prompt') %}
  {% set display_output_format_instructions = effective_output_format_instructions or output_format_instructions %}
  {% set custom_instructions = prompting_meta.get('custom_instructions') %}
  {% set custom_instructions_path = prompting_meta.get('custom_instructions_path') %}
  {% if display_output_format_instructions %}
  <details>
    <summary><h3>Output format instructions</h3></summary>
    <pre class="prompt-block">{{ display_output_format_instructions|e }}</pre>
    {% if effective_output_format_instructions and output_format_instructions and effective_output_format_instructions != output_format_instructions %}
    <p><small>Includes appended custom instructions.</small></p>
    {% endif %}
  </details>
  {% endif %}
  {% if custom_instructions %}
  <details>
    <summary><h3>Custom Instructions</h3></summary>
    <pre class="prompt-block">{{ custom_instructions|e }}</pre>
    {% if custom_instructions_path %}
    <p><small>Source: {{ custom_instructions_path }}</small></p>
    {% endif %}
  </details>
  {% endif %}
  <p>All tests are automatic and deterministic (no human intervention). Only a fraction of accessibility requirements in WCAG can be covered in this way. Many requirements still need a human to evaluate. As such, these tests are not comprehensive. Even if a test passes, it may still fail WCAG and contain serious accessibility issues.</p>
  <p>Please leave feedback, review the source code, and contribute test cases, assertions, and other improvements at the <a href="https://github.com/microsoft/a11y-llm-eval">GitHub Project</a>.</p>

<h2 id="glossary">Glossary</h2>
  <h3>Column Definitions</h3>
  <ul>
    <li><strong>Rank</strong>: The position of the model when sorted by WCAG Pass Rate (lower is better).</li>
    <li><strong>WCAG Pass Rate</strong>: The percentage of samples that passed all WCAG tests, including both axe-core WCAG checks and custom WCAG assertions. This does not include best practices.</li>
    <li><strong>Not applicable assertion</strong>: An assertion result that indicates a check did not apply to that sample. It is tracked at the assertion level and does not change the sample-level pass-rate denominator.</li>
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

  <h2 id="change-log">Change Log</h2>
  <h3>2/2026 Update</h3>
  <ul>
    <li><strong>Test Cases</strong>: Added a test case for a simple contact form with assertions for simple form controls. Also fixed some minor bugs in other test cases.</li>
    <li><strong>Instruction Sets</strong>: Added instruction set evaluation.</li>
    <li><strong>Report</strong>: Updated report layout and added new sections for instruction sets and analysis. Also allow filtering by instruction set and specific assertions within test cases.</li>
  </ul>
</section>

  </section>

  {% if instruction_benchmark_rows or instruction_set_analysis %}
  <section id="instruction-sets" data-report-section="instructions">

{% if instruction_benchmark_rows %}
<section id="instruction-benchmark-summary">
  <h2>Instruction Benchmarks (vs Control)</h2>
  <p>These results show how well each instruction set performs vs the control configuration (averaged across models). Instruction sets contain specific guidance intended to improve accessibility and are appended to the system prompt.</p>
  <p>Several instruction sets are used in this benchmark to help identify which instructions are most effective at improving accessibility. Models are ranked by average WCAG pass rate across all models and test cases for that instruction set.</p>
  <h3>Summary (ranked by avg WCAG pass rate)</h3>
  {% if instruction_benchmark_summary %}
    <table>
      <thead>
        <tr>
          <th>Rank</th>
          <th>Instruction Set</th>
          <th>Avg Control Pass Rate*</th>
          <th>Avg Instruction Set Pass Rate*</th>
          <th>Δ Avg Pass Rate*</th>
        </tr>
      </thead>
      <tbody>
        {% for row in instruction_benchmark_summary %}
        <tr>
          <td>{{ row.rank }}</td>
          <th>{{ row.variant_name }}</th>
          <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(row.avg_control_pass_rate) }}">{{ '%.0f%%'|format(row.avg_control_pass_rate * 100) }}</td>
          <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(row.avg_variant_pass_rate) }}">{{ '%.0f%%'|format(row.avg_variant_pass_rate * 100) }}</td>
          <td>{{ '%+.1fpp'|format(row.delta_avg_pass_rate * 100) }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {{ pass_rate_note() }}
  {% else %}
    <p><em>No benchmark summary table is available for this run.</em></p>
  {% endif %}
</section>

<section id="instruction-benchmark-details">
  <h2>Instruction benchmark details</h2>
  <p>This section includes per-model benchmark results and the full text of each instruction set.</p>

    {% if instruction_benchmark_variants %}
      <h3>Instruction sets</h3>
      {% for v in instruction_benchmark_variants %}
        <details>
          <summary>{{ v.name }}</summary>
          {% if v.description %}<p>{{ v.description }}</p>{% endif %}
          {% if v.n_samples_requested %}<p><strong>Variant samples per (test, model):</strong> {{ v.n_samples_requested }}</p>{% endif %}
          {% if v.generation_mode %}<p><strong>Generation mode:</strong> {{ v.generation_mode }}</p>{% endif %}
          {% if v.agent_sandbox %}<p><strong>Sandbox:</strong> {{ v.agent_sandbox }}</p>{% endif %}
          {% if v.agent_limits %}<pre class="prompt-block">{{ v.agent_limits|tojson(indent=2) }}</pre>{% endif %}
          {% if v.custom_instructions_markdown %}
            <pre class="prompt-block">{{ v.custom_instructions_markdown|e }}</pre>
          {% else %}
            <p><em>No custom instructions markdown available.</em></p>
          {% endif %}
        </details>
      {% endfor %}
    {% endif %}

    <h3>Results</h3>
    <table>
      <thead>
        <tr>
          <th>Model</th>
          <th>Instruction Set</th>
          <th>Control Pass Rate*</th>
          <th>Instruction Set Pass Rate*</th>
          <th>Δ Pass Rate*</th>
        </tr>
      </thead>
      <tbody>
        {% for row in instruction_benchmark_rows %}
        <tr>
          <th>{{ row.model_display }}</th>
          <td>{{ row.variant_name }}</td>
          <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(row.control_pass_rate) }}">{{ '%.0f%%'|format(row.control_pass_rate * 100) }}</td>
          <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(row.variant_pass_rate) }}">{{ '%.0f%%'|format(row.variant_pass_rate * 100) }}</td>
          <td>{{ '%+.1fpp'|format(row.delta_pass_rate * 100) }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {{ pass_rate_note() }}
</section>
{% endif %}

  {% if instruction_set_analysis %}
  <section id="instruction-set-analysis">
    <details>
      <summary><h2>Instruction set analysis vs control</h2></summary>
      <p>This section highlights where each instruction set helped (or hurt) compared to the control, aggregated across all samples for that instruction set.</p>
      {{ pass_rate_note() }}

      {% for a in instruction_set_analysis %}
        <details>
          <summary>
            {{ a.variant_name }} — overall Δ pass rate {{ '%+.1fpp'|format(a.delta_overall_pass_rate * 100) }}
          </summary>

        <p>
          <strong>Overall:</strong>
          Control {{ '%.0f%%'|format(a.control_overall_pass_rate * 100) }} (n={{ a.control_total_samples }}) →
          Variant {{ '%.0f%%'|format(a.variant_overall_pass_rate * 100) }} (n={{ a.variant_total_samples }}).
          Avg WCAG failures/sample: {{ '%.2f'|format(a.control_avg_wcag_failures) }} → {{ '%.2f'|format(a.variant_avg_wcag_failures) }}
          (Δ {{ '%+.2f'|format(a.delta_avg_wcag_failures) }}).
        </p>

        {% if a.most_improved_tests %}
          <h3>Most improved test cases</h3>
          <table>
            <thead>
              <tr>
                <th>Test case</th>
                <th>Control pass rate*</th>
                <th>Variant pass rate*</th>
                <th>Δ pass rate*</th>
                <th>Δ avg WCAG failures</th>
              </tr>
            </thead>
            <tbody>
              {% for t in a.most_improved_tests %}
              <tr>
                <th>{{ t.test_name }}</th>
                <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(t.control_pass_rate) }}">{{ '%.0f%%'|format(t.control_pass_rate * 100) }}</td>
                <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(t.variant_pass_rate) }}">{{ '%.0f%%'|format(t.variant_pass_rate * 100) }}</td>
                <td>{{ '%+.1fpp'|format(t.delta_pass_rate * 100) }}</td>
                <td>{{ '%+.2f'|format(t.delta_avg_wcag_failures) }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        {% endif %}

        {% if a.most_regressed_tests %}
          <h3>Most regressed test cases</h3>
          <table>
            <thead>
              <tr>
                <th>Test case</th>
                <th>Control pass rate*</th>
                <th>Variant pass rate*</th>
                <th>Δ pass rate*</th>
                <th>Δ avg WCAG failures</th>
              </tr>
            </thead>
            <tbody>
              {% for t in a.most_regressed_tests %}
              <tr>
                <th>{{ t.test_name }}</th>
                <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(t.control_pass_rate) }}">{{ '%.0f%%'|format(t.control_pass_rate * 100) }}</td>
                <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(t.variant_pass_rate) }}">{{ '%.0f%%'|format(t.variant_pass_rate * 100) }}</td>
                <td>{{ '%+.1fpp'|format(t.delta_pass_rate * 100) }}</td>
                <td>{{ '%+.2f'|format(t.delta_avg_wcag_failures) }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        {% endif %}

        {% if a.most_reduced_axe_rules %}
          <h3>Most reduced axe WCAG rules</h3>
          <table>
            <thead>
              <tr>
                <th>Rule</th>
                <th>Control rate</th>
                <th>Variant rate</th>
                <th>Δ rate</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {% for r in a.most_reduced_axe_rules %}
              <tr>
                <th>{{ r.id }}</th>
                <td>{{ '%.1f%%'|format(r.control_rate * 100) }}</td>
                <td>{{ '%.1f%%'|format(r.variant_rate * 100) }}</td>
                <td>{{ '%+.1fpp'|format(r.delta_rate * 100) }}</td>
                <td>{{ r.description|e or '' }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        {% endif %}

        {% if a.most_increased_axe_rules %}
          <h3>Most increased axe WCAG rules</h3>
          <table>
            <thead>
              <tr>
                <th>Rule</th>
                <th>Control rate</th>
                <th>Variant rate</th>
                <th>Δ rate</th>
                <th>Description</th>
              </tr>
            </thead>
            <tbody>
              {% for r in a.most_increased_axe_rules %}
              <tr>
                <th>{{ r.id }}</th>
                <td>{{ '%.1f%%'|format(r.control_rate * 100) }}</td>
                <td>{{ '%.1f%%'|format(r.variant_rate * 100) }}</td>
                <td>{{ '%+.1fpp'|format(r.delta_rate * 100) }}</td>
                <td>{{ r.description|e or '' }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        {% endif %}

        {% if a.most_improved_assertions or a.most_regressed_assertions or a.assertion_deltas_by_test %}
          <h3>Assertion analysis (vs control)</h3>
          <p>Failure rates are computed per assertion (within each test case) and compared between the variant and control.</p>

          {% if a.most_improved_assertions %}
            <h4>Most improved assertions</h4>
            <table>
              <thead>
                <tr>
                  <th>Test case</th>
                  <th>Assertion</th>
                  <th>Type</th>
                  <th>Control fail rate</th>
                  <th>Variant fail rate</th>
                  <th>Δ fail rate</th>
                  <th>Control failures/total</th>
                  <th>Variant failures/total</th>
                </tr>
              </thead>
              <tbody>
                {% for r in a.most_improved_assertions %}
                <tr>
                  <td>{{ r.test_name }}</td>
                  <th>{{ r.assertion_name }}</th>
                  <td>{{ r.type }}</td>
                  <td>{% if r.control_fail_rate is not none %}{{ '%.0f%%'|format(r.control_fail_rate * 100) }}{% else %}-{% endif %}</td>
                  <td>{% if r.variant_fail_rate is not none %}{{ '%.0f%%'|format(r.variant_fail_rate * 100) }}{% else %}-{% endif %}</td>
                  <td>{% if r.delta_fail_rate is not none %}{{ '%+.1fpp'|format(r.delta_fail_rate * 100) }}{% else %}-{% endif %}</td>
                  <td>{{ r.control_fail_count }} / {{ r.control_total }}</td>
                  <td>{{ r.variant_fail_count }} / {{ r.variant_total }}</td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
          {% endif %}

          {% if a.most_regressed_assertions %}
            <h4>Most regressed assertions</h4>
            <table>
              <thead>
                <tr>
                  <th>Test case</th>
                  <th>Assertion</th>
                  <th>Type</th>
                  <th>Control fail rate</th>
                  <th>Variant fail rate</th>
                  <th>Δ fail rate</th>
                  <th>Control failures/total</th>
                  <th>Variant failures/total</th>
                </tr>
              </thead>
              <tbody>
                {% for r in a.most_regressed_assertions %}
                <tr>
                  <td>{{ r.test_name }}</td>
                  <th>{{ r.assertion_name }}</th>
                  <td>{{ r.type }}</td>
                  <td>{% if r.control_fail_rate is not none %}{{ '%.0f%%'|format(r.control_fail_rate * 100) }}{% else %}-{% endif %}</td>
                  <td>{% if r.variant_fail_rate is not none %}{{ '%.0f%%'|format(r.variant_fail_rate * 100) }}{% else %}-{% endif %}</td>
                  <td>{% if r.delta_fail_rate is not none %}{{ '%+.1fpp'|format(r.delta_fail_rate * 100) }}{% else %}-{% endif %}</td>
                  <td>{{ r.control_fail_count }} / {{ r.control_total }}</td>
                  <td>{{ r.variant_fail_count }} / {{ r.variant_total }}</td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
          {% endif %}

          {% if a.assertion_deltas_by_test %}
            <details>
              <summary>All assertion deltas (per test case)</summary>
              {% for test_name, rows in a.assertion_deltas_by_test.items() %}
                {% if rows %}
                  <h4>{{ test_name }}</h4>
                  <table>
                    <thead>
                      <tr>
                        <th>Assertion</th>
                        <th>Type</th>
                        <th>Control fail rate</th>
                        <th>Variant fail rate</th>
                        <th>Δ fail rate</th>
                        <th>Control failures/total</th>
                        <th>Variant failures/total</th>
                      </tr>
                    </thead>
                    <tbody>
                      {% for r in rows %}
                      <tr>
                        <th>{{ r.assertion_name }}</th>
                        <td>{{ r.type }}</td>
                        <td>{% if r.control_fail_rate is not none %}{{ '%.0f%%'|format(r.control_fail_rate * 100) }}{% else %}-{% endif %}</td>
                        <td>{% if r.variant_fail_rate is not none %}{{ '%.0f%%'|format(r.variant_fail_rate * 100) }}{% else %}-{% endif %}</td>
                        <td>{% if r.delta_fail_rate is not none %}{{ '%+.1fpp'|format(r.delta_fail_rate * 100) }}{% else %}-{% endif %}</td>
                        <td>{{ r.control_fail_count }} / {{ r.control_total }}</td>
                        <td>{{ r.variant_fail_count }} / {{ r.variant_total }}</td>
                      </tr>
                      {% endfor %}
                    </tbody>
                  </table>
                {% endif %}
              {% endfor %}
            </details>
          {% endif %}
        {% endif %}
        </details>
      {% endfor %}
    </details>
  </section>
  {% endif %}
  </section>
  {% endif %}

  {% if skill_benchmark_tables %}
  <section id="skills" data-report-section="skills">
  <section id="skill-benchmark-summary">
    <h2>Skills (vs Control)</h2>
    <p>Skills are self-contained packages (a directory containing <code>SKILL.md</code> and any support files) that are mounted into the sandboxed agent at runtime. Each skill defines its own multi-turn conversation; the agent's submission at the end of each turn is evaluated separately so we can compare how each turn performs against control.</p>
    <p><strong>Note on interpretation.</strong> Turn&nbsp;1 is a single-turn generation directly comparable to control. Later turns operate on prior context, so their Δ reflects both the skill package content <em>and</em> the effect of having a review opportunity.</p>
    {{ pass_rate_note() }}
    {% for skill in skill_benchmark_tables %}
    <h3>{{ skill.name }}</h3>
    {% if skill.description %}<p>{{ skill.description }}</p>{% endif %}
    <table>
      <thead>
        <tr>
          <th>Rank</th>
          <th>Model</th>
          <th>Control*</th>
          {% for t in skill.turns %}
            <th>{{ t.name or t.id }}*</th>
          {% endfor %}
          <th>Δ last&nbsp;vs&nbsp;control*</th>
          {% if skill.turns|length >= 2 %}<th>Δ last&nbsp;vs&nbsp;turn&nbsp;1*</th>{% endif %}
        </tr>
      </thead>
      <tbody>
        {% for row in skill.rows %}
        <tr>
          <td>{{ row.rank }}</td>
          <th>{{ row.model_display }}</th>
          <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(row.control_pass_rate) }}">{{ '%.0f%%'|format(row.control_pass_rate * 100) }}</td>
          {% for tp in row.turn_pass_rates %}
            <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(tp.pass_rate) }}">{{ '%.0f%%'|format(tp.pass_rate * 100) }}</td>
          {% endfor %}
          <td>{{ '%+.1fpp'|format(row.delta_last_vs_control * 100) }}</td>
          {% if skill.turns|length >= 2 %}<td>{{ '%+.1fpp'|format(row.delta_last_vs_first * 100) }}</td>{% endif %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% endfor %}
  </section>

  <section id="skill-benchmark-details">
    <h2>Skill details</h2>
    <p>Each skill's mounted package, sandbox location, and per-turn prompt templates.</p>
    {% for v in skill_benchmark_variants %}
      <details>
        <summary>{{ v.name }}</summary>
        {% if v.description %}<p>{{ v.description }}</p>{% endif %}
        {% if v.n_samples_requested %}<p><strong>Samples per (test, model):</strong> {{ v.n_samples_requested }}</p>{% endif %}
        {% if v.agent_sandbox %}<p><strong>Sandbox:</strong> {{ v.agent_sandbox }}</p>{% endif %}
        {% if v.skill_path %}<p><strong>Skill package:</strong> <code>{{ v.skill_path }}</code></p>{% endif %}
        {% if v.agent_limits %}<pre class="prompt-block">{{ v.agent_limits|tojson(indent=2) }}</pre>{% endif %}
        {% if v.turns %}
          <h4>Turn prompts</h4>
          <ol>
            {% for t in v.turns %}
              <li>
                <strong>{{ t.name or t.id }}</strong> <code>({{ t.id }})</code>
                <pre class="prompt-block">{{ t.prompt|e }}</pre>
              </li>
            {% endfor %}
          </ol>
        {% endif %}
        {% if v.skill_md_preview %}
          <h4>SKILL.md</h4>
          <pre class="prompt-block">{{ v.skill_md_preview|e }}</pre>
        {% endif %}
      </details>
    {% endfor %}
  </section>
  </section>
  {% endif %}

  <section id="detailed-results" data-report-section="details">
<section>
<h2 id="details-h2">Detailed Results</h2>
<div class="filters" role="region" aria-label="Detailed results filters">
  <label>
    Model
    <select id="model-filter">
      <option value="">All models</option>
      {% for opt in model_filter_options %}
        <option value="{{ opt.value }}">{{ opt.label }}</option>
      {% endfor %}
    </select>
  </label>
  <label>
    Instruction set
    <select id="variant-filter">
      <option value="control" selected>Control</option>
      <option value="">All instruction sets</option>
      {% for pv in (prompt_variants or []) %}
        {% if pv.id and pv.id != 'control' %}
          <option value="{{ pv.id }}">{{ pv.name or pv.id }}</option>
        {% endif %}
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
    {% if test_data.base_test_name %}
    <p><strong>Base test:</strong> {{ test_data.base_test_name }}</p>
    {% endif %}
    {% if test_data.prompt_dimensions %}
    <p>
      <strong>Prompt dimensions:</strong>
      {% for dim in test_data.prompt_dimensions %}
        {{ dim.label }}: {{ dim.value_label }}{% if not loop.last %} | {% endif %}
      {% endfor %}
    </p>
    {% endif %}
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
          <option value="na">Not applicable</option>
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
    <details data-model-group="{{ group.model_name }}">
      <summary>
        <h4>
          {{ model_display_names.get(group.model_name, group.model_name) }}
          {% for vid, agg in (group.aggregates_by_variant or {}).items() %}
            {% if agg and agg.n_samples %}
              <span class="variant-only" data-variant="{{ vid }}">&nbsp;—&nbsp;{{ '%.0f%%'|format((agg.n_pass / agg.n_samples) * 100) }}</span>
            {% endif %}
          {% endfor %}
        </h4>
      </summary>
      <div class="model-aggregates">
        <p class="variant-aggregate-note" hidden><em>Aggregates are shown when filtering to a specific instruction set.</em></p>
        {% for vid, agg in (group.aggregates_by_variant or {}).items() %}
          {% if agg %}
            <div class="variant-only" data-variant="{{ vid }}">
              <p>Samples: {{ agg.n_samples }} | Passes: {{ agg.n_pass }}</p>
              <table>
                <thead><tr>{% for k,v in agg.pass_at_k.items() %}<th>pass@{{ k }}*</th>{% endfor %}</tr></thead>
                <tbody><tr>{% for k,v in agg.pass_at_k.items() %}
                  <td class="pass-at-k-cell" data-pass-at-k="{{ k }}" data-pass="{% if agg.n_samples %}{{ '%.4f'|format(v) }}{% endif %}">{% if agg.n_samples %}{{ '%.0f%%'|format(v * 100) }}{% else %}-{% endif %}</td>
                {% endfor %}</tr></tbody>
              </table>
              {% set _percent = (100.0 * (agg.n_pass / agg.n_samples)) if agg.n_samples else 0 %}
              <div class="pass-rate-bar" role="img" aria-label="Pass ratio - {{ _percent }} percent"><span style="width: {{ _percent }}%"></span></div>
            </div>
          {% endif %}
        {% endfor %}
      </div>
      <div class="samples">
      {% for r in group.samples %}
        {% set vid = r.prompt_variant_id if r.prompt_variant_id is not none else 'control' %}
        <div class="sample-card" data-model="{{ r.model_name }}" data-result="{{ r.result }}" data-variant="{{ vid }}"{% if r.prompt_variant_kind == 'skill' %} data-variant-kind="skill" data-turn-id="{{ r.turn_id }}" data-turn-index="{{ r.turn_index }}"{% endif %}>
          {# Trim the first two path segments (e.g., 'runs/<run_id>/...') #}
          {% set _parts = r.generation_html_path.split('/') %}
          {% set _trimmed = '/'.join(_parts[2:]) %}
          <h4>
            <a href="{{ _trimmed }}">
              Sample {{ r.sample_index if r.sample_index is not none else loop.index0 }}{% if r.prompt_variant_kind == 'skill' %} &middot; Turn {{ (r.turn_index or 0) + 1 }}{% if r.turn_count_total %}/{{ r.turn_count_total }}{% endif %}{% if r.turn_id %} ({{ r.turn_id }}){% endif %}{% endif %} ({{ model_display_names.get(r.model_name, r.model_name) }})
            </a>
          </h4>
          <p>
            {% if r.prompt_variant_kind == 'skill' %}
              <strong>Skill:</strong> {{ prompt_variant_names.get(vid, vid) }}
              {% if r.turn_id %} &middot; <strong>Turn:</strong> {{ (r.turn_index or 0) + 1 }}{% if r.turn_count_total %}/{{ r.turn_count_total }}{% endif %} ({{ r.turn_id }}){% endif %}
            {% else %}
              <strong>Instruction set:</strong>
              {% if vid == 'control' %}
                Control
              {% else %}
                {{ prompt_variant_names.get(vid, vid) }}
              {% endif %}
            {% endif %}
          </p>
          <p><span class="badge-{{ 'pass' if r.result=='PASS' else 'fail' }}">{{ r.result }}</span> | Latency {{ '%.2f'|format(r.generation.latency_s) }}s{% if r.generation.cached %} cached{% endif %}</p>
          <p>Axe WCAG: {{ r.axe.failure_count if r.axe else 'n/a' }}{% if r.axe and r.axe.best_practice_count > 0 %} | BP: {{ r.axe.best_practice_count }}{% endif %}{% if r.generation.cost_usd is not none %} | ${{ '%.4f'|format(r.generation.cost_usd) }}{% endif %}{% if r.generation.total_tokens is defined and r.generation.total_tokens is not none %} | Tokens: {{ '{:,}'.format(r.generation.total_tokens) }}{% if r.generation.tokens_in is defined and r.generation.tokens_out is defined and r.generation.tokens_in is not none and r.generation.tokens_out is not none %} ({{ '{:,}'.format(r.generation.tokens_in) }} in / {{ '{:,}'.format(r.generation.tokens_out) }} out){% endif %}{% endif %}</p>
          {% if r.generation.generation_mode %}
          <p><strong>Generation mode:</strong> {{ r.generation.generation_mode }}{% if r.generation.agent_sandbox %} | <strong>Sandbox:</strong> {{ r.generation.agent_sandbox }}{% endif %}{% if r.generation_eval_path_relative %} | <a href="{{ r.generation_eval_path_relative }}">Copilot session log</a>{% endif %}{% if r.generation_conversation_path_relative %} | <a href="{{ r.generation_conversation_path_relative }}">Conversation JSON</a>{% endif %}</p>
          {% endif %}
          {% if r.screenshot_path %}
            {# Trim the first two path segments (e.g., 'runs/<run_id>/...') #}
            {% set _parts = r.screenshot_path.split('/') %}
            {% set _trimmed = '/'.join(_parts[2:]) %}
            <figure>
              <img src="{{ _trimmed }}" alt="Screenshot sample {{ r.sample_index }} for {{ r.test_name }} / {{ model_display_names.get(r.model_name, r.model_name) }}" style="max-width:320px;">
            </figure>
          {% endif %}
          {% if r.generation_conversation %}
          <details class="transcript-summary">
            <summary>Agent conversation ({{ r.generation_conversation.message_count }} messages{% if r.generation_conversation.entry_count is not none %}, {{ r.generation_conversation.entry_count }} entries{% endif %}{% if r.generation.agent_limit_error %}, limit: {{ r.generation.agent_limit_error }}{% endif %})</summary>
            {% if r.generation_conversation.turns %}
              <div class="transcript-turns">
                {% for turn in r.generation_conversation.turns %}
                  <div class="transcript-turn transcript-turn-{{ turn.role }}">
                    <p class="transcript-turn-header">{{ turn.role_label }}</p>
                    {% for msg in turn.messages %}
                      {% if msg.label == 'Prompt' %}
                        <pre class="prompt-block transcript-turn-prompt">{{ msg.content|e }}</pre>
                      {% else %}
                        <p class="transcript-turn-msg"><span class="transcript-turn-msg-label">{{ msg.label }}:</span> {{ msg.content|e }}</p>
                      {% endif %}
                    {% endfor %}
                    {% if turn.tool_calls %}
                      <p class="transcript-tool-list">{% for tc in turn.tool_calls %}{{ tc|e }}{% if not loop.last %}<br>{% endif %}{% endfor %}</p>
                    {% endif %}
                  </div>
                {% endfor %}
              </div>
            {% else %}
              <p><em>No transcript preview available.</em></p>
            {% endif %}
          </details>
          {% endif %}
          <details>
            <summary>
              Assertions
              {% if r.test_function.status == "fail" %}
                <span role="img" aria-label="Fail">❌</span>
              {% elif r.test_function.status == "na" %}
                <span role="img" aria-label="Not applicable">➖</span>
              {% elif r.test_function.status == "pass" %}
                <span role="img" aria-label="Pass">✅</span>
              {% endif %}
            </summary>
            <ul>
              {% for a in r.test_function.assertions %}
              <li data-assertion-name="{{ a.name|e }}" data-assertion-status="{{ a.status|e }}">
                {% if a.status == "fail" %}
                  <span role="img" aria-label="Fail">❌</span>:
                {% elif a.status == "na" %}
                  <span role="img" aria-label="Not applicable">➖</span>:
                {% elif a.status == "pass" %}
                  <span role="img" aria-label="Pass">✅</span>:
                {% endif %}
                {{ a.name|e }} ({{ a.type if a.type else 'R' }}): {{ a.status|e }}
                {% if a.message_parts %}
                  {% if a.message_parts['title'] %}
                  - <span>{{ a.message_parts['title']|e }}</span>
                  {% else %}
                  -
                  {% endif %}
                  <div class="assertion-message-block">
                    <ul class="assertion-message-list">
                      {% for item in a.message_parts['items'] %}
                        <li>{{ item|e }}</li>
                      {% endfor %}
                    </ul>
                  </div>
                {% elif a.message %}
                  - {{ a.message|e }}
                {% endif %}
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
              <li>({{ v.nodes|length }}x) - <strong>{{ v.id|e }}</strong> ({{ v.impact|e }}): {{ v.description|e }}</li>
              {% endfor %}
            </ul>
          </details>
          {% endif %}
          {% if r.axe.best_practice_count > 0 %}
          <details>
            <summary>Axe Best Practice Issues ({{ r.axe.best_practice_count }}) <span role="img" aria-label="Warning">⚠️</span></summary>
            <ul>
              {% for v in r.axe.best_practice_failures %}
              <li><strong>{{ v.id|e }}</strong> ({{ v.impact|e }}): {{ v.description|e }} <em>(Best Practice - does not affect pass/fail)</em></li>
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
  </section>
</main>
<footer>
<p>GitHub Project: <a href="https://github.com/microsoft/a11y-llm-eval">a11y-llm-eval</a>. Run ID: {{ run_id }}</p>
{{ footer_content|safe }}
</footer>
<script>
document.addEventListener('DOMContentLoaded', function () {
  function initReportSectionNav() {
    const nav = document.querySelector('.report-nav');
    if (!nav) return;

    const links = Array.from(nav.querySelectorAll('a[data-report-nav]'));
    if (!links.length) return;

    const sections = Array.from(document.querySelectorAll('[data-report-section]'));
    if (!sections.length) return;

    const sectionByKey = new Map();
    sections.forEach(function (section) {
      const key = section.getAttribute('data-report-section');
      if (key) sectionByKey.set(key, section);
    });

    function keyFromHash() {
      const hash = (window.location.hash || '').replace('#', '');
      if (!hash) return null;

      // First: direct mapping for known ids.
      if (hash === 'control-summary' || hash === 'control-section') return 'control';
      if (hash === 'instruction-sets') return 'instructions';
      if (hash === 'skills' || hash === 'skill-benchmark-summary' || hash === 'skill-benchmark-details') return 'skills';
      if (hash === 'details-h2' || hash === 'detailed-results') return 'details';
      if (hash === 'methodology' || hash === 'glossary' || hash === 'report-about') return 'about';

      // Otherwise: find which major section contains the target.
      const target = document.getElementById(hash);
      if (target) {
        for (const entry of sectionByKey.entries()) {
          const key = entry[0];
          const section = entry[1];
          if (section.contains(target)) return key;
        }
      }
      return null;
    }

    function setCurrentLink(key) {
      links.forEach(function (a) {
        const k = a.getAttribute('data-report-nav');
        if (k === key) {
          a.setAttribute('aria-current', 'page');
        } else {
          a.removeAttribute('aria-current');
        }
      });
    }

    function showSection(key, opts) {
      const options = opts || {};
      const section = sectionByKey.get(key);
      if (!section) return;

      sections.forEach(function (s) {
        s.hidden = (s !== section);
      });
      setCurrentLink(key);

      // If the current hash points to an element, scroll it into view.
      if (options.scrollToHash) {
        const hash = (window.location.hash || '').replace('#', '');
        if (hash) {
          const target = document.getElementById(hash);
          if (target) {
            target.scrollIntoView({ block: 'start' });
          }
        }
      }
    }

    // Default selection: control.
    const initialKey = keyFromHash() || 'control';
    showSection(initialKey, { scrollToHash: false });

    links.forEach(function (a) {
      a.addEventListener('click', function (e) {
        const key = a.getAttribute('data-report-nav');
        if (!key) return;

        // Switch immediately; allow the browser to handle the anchor navigation.
        showSection(key, { scrollToHash: false });
      });
    });

    window.addEventListener('hashchange', function () {
      const key = keyFromHash();
      if (key) showSection(key, { scrollToHash: true });
    });
  }

  initReportSectionNav();

  const modelFilter = document.getElementById('model-filter');
  const variantFilter = document.getElementById('variant-filter');
  const resultFilter = document.getElementById('result-filter');
  const resetButton = document.getElementById('reset-filters');
  const modelSections = Array.from(document.querySelectorAll('[data-model-group]'));
  const allCards = Array.from(document.querySelectorAll('.sample-card'));
  const noResultsMessage = document.getElementById('no-results-message');
  const countEl = document.getElementById('filter-count');
  const totalCardCount = allCards.length;

  function applyVariantVisibility() {
    const variantValue = variantFilter ? variantFilter.value : 'control';
    const variantEls = Array.from(document.querySelectorAll('.variant-only[data-variant]'));
    const notes = Array.from(document.querySelectorAll('.variant-aggregate-note'));

    // When viewing "All instruction sets", hide aggregates to avoid confusion.
    if (!variantValue) {
      variantEls.forEach(function (el) { el.style.display = 'none'; });
      notes.forEach(function (el) { el.hidden = false; });
      return;
    }

    notes.forEach(function (el) { el.hidden = true; });
    variantEls.forEach(function (el) {
      const elVariant = el.getAttribute('data-variant');
      el.style.display = (elVariant === variantValue) ? '' : 'none';
    });
  }

  function applyFilters() {
    const modelValue = modelFilter ? modelFilter.value : '';
    const variantValue = variantFilter ? variantFilter.value : 'control';
    const resultValue = resultFilter ? resultFilter.value : '';
    let anyVisible = false;
    let visibleCardCount = 0;

    modelSections.forEach(function (section) {
      const cards = Array.from(section.querySelectorAll('.sample-card'));
      const sectionModel = section.getAttribute('data-model-group');
      let sectionHasVisibleCard = false;

      cards.forEach(function (card) {
        const cardModel = card.getAttribute('data-model');
        const cardVariant = card.getAttribute('data-variant') || 'control';
        const cardResult = card.getAttribute('data-result');
        const matchesModel = !modelValue || cardModel === modelValue;
        const matchesVariant = !variantValue || cardVariant === variantValue;
        const matchesResult = !resultValue || cardResult === resultValue;
        const hiddenByAssertion = card.classList.contains('hidden-by-assertion');
        const shouldShowCard = matchesModel && matchesVariant && matchesResult && !hiddenByAssertion;

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

    applyVariantVisibility();
    updateAssertionCounts();
  }

  if (modelFilter) {
    modelFilter.addEventListener('change', applyFilters);
  }
  if (variantFilter) {
    variantFilter.addEventListener('change', applyFilters);
  }
  if (resultFilter) {
    resultFilter.addEventListener('change', applyFilters);
  }
  if (resetButton) {
    resetButton.addEventListener('click', function () {
      if (modelFilter) {
        modelFilter.value = '';
      }
      if (variantFilter) {
        variantFilter.value = 'control';
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

  def _read_json_for_report(path_str: str | None):
    """Read a JSON file for embedding in the report.

    Only files that resolve to a location *under* the run directory are
    read.  Paths that escape the run directory (via ``../`` traversals
    or unrelated absolute locations) are silently ignored to prevent
    local-file disclosure when ``results.json`` comes from an untrusted
    source.
    """
    if not path_str:
      return None
    raw_path = Path(path_str)
    run_dir = run_json_path.parent
    resolved_run_dir = run_dir.resolve()

    # Build candidates: try run_dir-relative first, then CWD-relative
    # for paths stored relative to the repo root.  Absolute paths are
    # used directly.
    if raw_path.is_absolute():
      candidates = [raw_path.resolve()]
    else:
      candidates = [
        (run_dir / raw_path).resolve(),
        (Path.cwd() / raw_path).resolve(),
      ]

    for candidate in candidates:
      # Ensure the resolved path is under the run directory.
      try:
        candidate.relative_to(resolved_run_dir)
      except ValueError:
        continue
      try:
        if candidate.is_file():
          return orjson.loads(candidate.read_bytes())
      except Exception:
        continue
    return None

  def _conversation_preview(conversation: dict | None) -> tuple[list[dict[str, str]], int, int | None]:
    if not isinstance(conversation, dict):
      return [], 0, None

    def _looks_like_html(text):
      normalized = text.lstrip().lower()
      return (
        normalized.startswith("<!doctype html")
        or normalized.startswith("<html")
        or normalized.startswith("<body")
      )

    def _text_value(value):
      if isinstance(value, str):
        text = value.strip()
        return text or None
      if isinstance(value, (int, float, bool)):
        return str(value)
      return None

    def _is_noise(text):
      lowered = text.lower()
      if len(text) > 1000:
        return True
      if "opaque" in lowered and "reasoning" in lowered:
        return True
      if "chain-of-thought" in lowered or "chain of thought" in lowered:
        return True
      if "here's the result of running `cat -n`" in lowered or lowered.startswith("```bash"):
        return True
      return False

    def _append_entry(entries, seen, kind, label, content):
      text = _text_value(content)
      if not text:
        return
      if _looks_like_html(text):
        return
      if _is_noise(text):
        return
      key = (kind, label, text)
      if key in seen:
        return
      seen.add(key)
      entries.append({"kind": kind, "label": label, "content": text})

    # Argument keys we don't want to dump verbatim in tool-call summaries
    # because their values are usually long file contents / patches / huge text.
    _BULKY_ARG_KEYS = {
      "file_text", "new_file_contents", "contents", "content",
      "diff", "patch", "input", "stdin", "body", "text",
    }
    _ARG_VALUE_PREVIEW_LIMIT = 200

    def _format_arg_value(value):
      if isinstance(value, str):
        text = value.strip()
        if len(text) > _ARG_VALUE_PREVIEW_LIMIT:
          return text[:_ARG_VALUE_PREVIEW_LIMIT].rstrip() + " …"
        return text
      if isinstance(value, (int, float, bool)) or value is None:
        return str(value)
      try:
        rendered = orjson.dumps(value).decode("utf-8")
      except (TypeError, ValueError):
        rendered = str(value)
      if len(rendered) > _ARG_VALUE_PREVIEW_LIMIT:
        rendered = rendered[:_ARG_VALUE_PREVIEW_LIMIT].rstrip() + " …"
      return rendered

    def _summarize_tool_call(call):
      if not isinstance(call, dict):
        return None
      function_name = (
        call.get("tool_name")
        or call.get("function")
        or call.get("name")
        or "tool"
      )
      arguments = call.get("arguments")
      intention = (
        _text_value(call.get("intention_summary"))
        or _text_value(call.get("intention"))
      )

      lines = [f"→ {function_name}"]
      if intention:
        lines.append(f"  why: {intention}")
      if isinstance(arguments, dict) and arguments:
        priority_keys = ("command", "cmd", "path", "file_name", "url", "intent", "query")
        seen_keys = set()
        for key in priority_keys:
          if key in arguments and arguments[key] not in (None, ""):
            value = _format_arg_value(arguments[key])
            if value:
              lines.append(f"  {key}: {value}")
              seen_keys.add(key)
        for key, value in arguments.items():
          if key in seen_keys or key in _BULKY_ARG_KEYS:
            continue
          if value in (None, "", [], {}):
            continue
          formatted = _format_arg_value(value)
          if formatted:
            lines.append(f"  {key}: {formatted}")
        # Indicate (without dumping) that bulky payloads were sent.
        bulky_present = sorted(k for k in arguments if k in _BULKY_ARG_KEYS and arguments[k])
        if bulky_present:
          lines.append(f"  ({', '.join(bulky_present)} omitted)")
      return "\n".join(lines)

    def _content_blocks(content):
      if content is None:
        return []
      if isinstance(content, str):
        text = content.strip()
        return [text] if text and not _looks_like_html(text) and not _is_noise(text) else []
      if isinstance(content, list):
        parts = []
        for item in content:
          if isinstance(item, str):
            text = item.strip()
            if text and not _looks_like_html(text) and not _is_noise(text):
              parts.append(text)
            continue
          if not isinstance(item, dict):
            continue
          item_type = item.get("type")
          if item_type == "reasoning":
            summary = _text_value(item.get("summary"))
            if summary and not _is_noise(summary):
              parts.append(summary)
            continue
          if item_type == "text":
            text = _text_value(item.get("text"))
            if text and not _looks_like_html(text) and not _is_noise(text):
              parts.append(text)
            continue
          if item_type == "tool_result":
            text = _text_value(item.get("content")) or _text_value(item.get("output")) or _text_value(item.get("result"))
            if text and not _looks_like_html(text) and not _is_noise(text):
              parts.append(text)
        return parts
      if isinstance(content, dict):
        text = _text_value(content.get("text")) or _text_value(content.get("content"))
        if text and not _looks_like_html(text) and not _is_noise(text):
          return [text]
      return []

    entries = []
    seen = set()
    messages = conversation.get("messages") or []
    for message in messages:
      if not isinstance(message, dict):
        continue
      role = str(message.get("role") or "message").lower()

      if role == "assistant":
        for call in message.get("tool_calls") or []:
          summary = _summarize_tool_call(call)
          if summary:
            _append_entry(entries, seen, "assistant", "Agent action", summary)

      blocks = _content_blocks(message.get("content"))
      if not blocks:
        blocks = _content_blocks(message.get("text"))
      if not blocks:
        blocks = _content_blocks(message.get("summary"))

      if not blocks:
        continue

      label = {
        "system": "Instructions",
        "user": "Prompt",
        "assistant": "Agent",
        "tool": "Tool result",
      }.get(role, role.capitalize())
      kind = role if role in {"system", "user", "assistant"} else "assistant"
      for block in blocks:
        _append_entry(entries, seen, kind, label, block)

    events = conversation.get("events") or []
    # SDK session events (github-copilot-sdk) use a {type, data} envelope where
    # ``type`` looks like ``user.message`` / ``assistant.message`` / ``assistant.tool.use``.
    # We recognize those explicitly so the report can show real prompt/response
    # content; otherwise we fall back to the legacy generic event summarizer.
    SDK_MESSAGE_TYPES = {
      "system.message": ("system", "Instructions"),
      "user.message": ("user", "Prompt"),
      "assistant.message": ("assistant", "Agent"),
    }
    SDK_SKIP_PREFIXES = (
      "session.", "pending.", "assistant.turn.", "assistant.usage",
      "assistant.reasoning", "hook.", "permission.completed",
      "tool.execution.partial",
    )
    _RESULT_PREVIEW_LIMIT = 400

    def _extract_tool_result_text(data):
      result = data.get("result")
      # SDK serializes the result as ``ToolExecutionCompleteResult(content='...', ...)``
      if isinstance(result, str):
        match = re.search(r"content=(['\"])(.*?)\1", result, flags=re.DOTALL)
        if match:
          return match.group(2)
        return result
      if isinstance(result, dict):
        return (
          _text_value(result.get("content"))
          or _text_value(result.get("output"))
          or _text_value(result.get("result"))
        )
      return None

    def _truncate(text, limit=_RESULT_PREVIEW_LIMIT):
      if not isinstance(text, str):
        return None
      stripped = text.strip()
      if not stripped:
        return None
      if len(stripped) > limit:
        return stripped[:limit].rstrip() + " …"
      return stripped

    sdk_message_count = 0
    for event in events:
      if not isinstance(event, dict):
        continue
      ev_type = event.get("type") or event.get("event") or event.get("name")
      data = event.get("data") if isinstance(event.get("data"), dict) else None

      # SDK-shaped events: route by type.
      if isinstance(ev_type, str) and data is not None and "." in ev_type:
        if ev_type in SDK_MESSAGE_TYPES:
          kind, label = SDK_MESSAGE_TYPES[ev_type]
          # Prefer the user-authored content over the harness-transformed one.
          content_text = _text_value(data.get("content"))
          for block in _content_blocks(content_text):
            _append_entry(entries, seen, kind, label, block)
            sdk_message_count += 1
          # Note: ``tool_requests`` on assistant.message are stringified
          # ``AssistantMessageToolRequest(...)`` reprs; we surface tool calls
          # via the structured ``tool.execution.start`` events instead.
          continue
        if ev_type == "tool.execution.start":
          summary = _summarize_tool_call(data)
          if summary:
            _append_entry(entries, seen, "assistant", "Agent action", summary)
          continue
        if ev_type == "tool.execution.complete":
          tool_name = data.get("tool_name") or "tool"
          if data.get("error"):
            err_text = _text_value(data.get("error")) or "tool execution failed"
            _append_entry(entries, seen, "assistant", f"{tool_name} error", _truncate(err_text))
          else:
            result_text = _extract_tool_result_text(data)
            preview = _truncate(result_text)
            if preview and not _looks_like_html(preview) and not _is_noise(preview):
              _append_entry(entries, seen, "assistant", f"{tool_name} result", preview)
          continue
        if ev_type == "permission.requested":
          req = data.get("permission_request")
          if isinstance(req, str):
            intention = re.search(r"intention=(['\"])(.*?)\1", req)
            file_name = re.search(r"file_name=(['\"])(.*?)\1", req)
            command = re.search(r"full_command_text=(['\"])(.*?)\1", req)
            kind_match = re.search(r"kind=<[^:]+:\s*(['\"])(.*?)\1", req)
            bits = []
            if kind_match:
              bits.append(f"[{kind_match.group(2)}]")
            if intention:
              bits.append(intention.group(2))
            target = (file_name.group(2) if file_name else None) or (
              command.group(2) if command else None
            )
            if target:
              bits.append(target)
            if bits:
              _append_entry(entries, seen, "assistant", "Permission requested", " ".join(bits))
          continue
        if ev_type in {"assistant.tool.use", "assistant.tool.call", "tool.call", "tool.use"}:
          summary = _summarize_tool_call(data) or f"Used {data.get('name') or ev_type}."
          _append_entry(entries, seen, "assistant", "Agent action", summary)
          continue
        if ev_type in {"assistant.tool.result", "tool.result"}:
          result_text = (
            _text_value(data.get("human_readable_result"))
            or _text_value(data.get("output"))
            or _text_value(data.get("content"))
            or _text_value(data.get("result"))
          )
          preview = _truncate(result_text)
          if preview and not _looks_like_html(preview) and not _is_noise(preview):
            _append_entry(entries, seen, "assistant", "Tool result", preview)
          continue
        if any(ev_type.startswith(p) for p in SDK_SKIP_PREFIXES):
          continue
        # Unknown SDK event: fall through to generic handling below.

      name = event.get("name") or event.get("tool") or ev_type or "event"
      args = event.get("arguments") or event.get("args") or event.get("input") or event.get("payload") or {}
      if not isinstance(args, dict):
        args = {}
      command = args.get("command") or event.get("command")
      path = args.get("path") or event.get("path")
      bits = []
      command_text = _text_value(command)
      path_text = _text_value(path)
      if command_text:
        bits.append(command_text)
      if path_text:
        bits.append(path_text)
      if bits:
        _append_entry(entries, seen, "assistant", "Agent action", f"Used {name}: {' | '.join(bits)}")
      else:
        _append_entry(entries, seen, "assistant", "Agent action", f"Used {name}.")

      result_text = (
        _text_value(event.get("human_readable_result"))
        or _text_value(event.get("message"))
        or _text_value(event.get("result"))
        or _text_value(event.get("summary"))
      )
      if result_text and not _looks_like_html(result_text) and not _is_noise(result_text):
        _append_entry(entries, seen, "assistant", f"{name} result", result_text)

    output = conversation.get("output") or {}
    if isinstance(output, dict):
      completion = _text_value(output.get("completion") or output.get("text") or output.get("content"))
      if completion:
        if _looks_like_html(completion):
          _append_entry(entries, seen, "assistant", "Final answer", "Submitted final HTML document.")
        else:
          _append_entry(entries, seen, "assistant", "Final answer", completion)

    event_count = len(events) if isinstance(events, list) else None
    message_count = len(messages) + sdk_message_count
    return entries, message_count, event_count

  def _build_turns(entries: list[dict[str, str]]) -> list[dict]:
    """Group flat entries into role-based turns for compact rendering."""
    turns: list[dict] = []
    current: dict | None = None
    for entry in entries:
      kind = entry["kind"]
      label = entry["label"]
      content = entry["content"]
      if current is None or current["role"] != kind:
        current = {
          "role": kind,
          "role_label": {"system": "System", "user": "User", "assistant": "Agent"}.get(kind, kind.capitalize()),
          "messages": [],
          "tool_calls": [],
        }
        turns.append(current)
      if label == "Agent action":
        current["tool_calls"].append(content)
      else:
        current["messages"].append({"label": label, "content": content})
    return turns

  run_dir = run_json_path.parent

  def _flatten_skill_conversation(conv: dict, turn_index: int | None) -> dict | None:
    """The skill multi-turn sidecar has shape {turns: [{conversation:{messages,events}}, ...]}.

    For a given result row (which is scoped to a single turn), return the
    per-turn inner conversation so ``_conversation_preview`` sees a standard
    messages/events dict. When ``turn_index`` is ``None`` (older records or
    aggregate views), stitch all turns back to back.
    """
    if not isinstance(conv, dict):
      return conv
    if "turns" not in conv or not isinstance(conv.get("turns"), list):
      return conv
    turns = conv["turns"]
    if turn_index is not None:
      for t in turns:
        if isinstance(t, dict) and t.get("turn_index") == turn_index:
          inner = t.get("conversation") or {}
          if isinstance(inner, dict):
            return inner
      return None
    # Aggregate: concatenate messages/events across turns.
    merged_messages = []
    merged_events = []
    for t in turns:
      inner = (t or {}).get("conversation") or {}
      if not isinstance(inner, dict):
        continue
      merged_messages.extend(inner.get("messages") or [])
      merged_events.extend(inner.get("events") or [])
    return {"messages": merged_messages, "events": merged_events}

  for result in all_results:
    conversation_path = result.get("generation_conversation_path")
    conversation = _read_json_for_report(conversation_path)
    if conversation_path:
      conv_p = Path(conversation_path)
      try:
        result["generation_conversation_path_relative"] = str(conv_p.resolve().relative_to(run_dir.resolve()))
      except ValueError:
        pass
    if not conversation:
      continue
    # For skill turns, select only the matching turn's inner transcript.
    if result.get("prompt_variant_kind") == "skill":
      conversation = _flatten_skill_conversation(conversation, result.get("turn_index"))
      if not isinstance(conversation, dict):
        continue
    entries, message_count, event_count = _conversation_preview(conversation)
    result["generation_conversation"] = {
      "path": conversation_path,
      "entries": entries,
      "turns": _build_turns(entries),
      "entry_count": len(entries),
      "message_count": message_count,
      "event_count": event_count,
    }

  # Compute report-relative paths for eval log files so the template can
  # link directly to them.  The stored path may be absolute or a file:// URI.
  for result in all_results:
    eval_path_raw = result.get("generation_eval_path")
    if not eval_path_raw:
      continue
    # Strip file:// scheme if present
    if eval_path_raw.startswith("file://"):
      eval_path_raw = eval_path_raw[len("file://"):]
    eval_p = Path(eval_path_raw)
    try:
      result["generation_eval_path_relative"] = str(eval_p.resolve().relative_to(run_dir.resolve()))
    except ValueError:
      # Fall back: if the eval file is not under the run dir, use the
      # filename only and hope it lives in copilot_logs/.
      result["generation_eval_path_relative"] = f"copilot_logs/{eval_p.name}"

  # Shorten absolute sandbox paths (e.g. "docker:/full/path/compose.yaml" → "docker:compose.yaml")
  def _shorten_sandbox(val: str | None) -> str | None:
    if not val or ":" not in val:
      return val
    provider, path_part = val.split(":", 1)
    if "/" in path_part or "\\" in path_part:
      return f"{provider}:{Path(path_part).name}"
    return val

  for result in all_results:
    gen = result.get("generation") or {}
    if gen.get("agent_sandbox"):
      gen["agent_sandbox"] = _shorten_sandbox(gen["agent_sandbox"])

  def _split_message_items(text: str) -> list[str]:
    items = []
    current = []
    quote_char = None
    bracket_depth = 0

    for char in text:
      if quote_char:
        current.append(char)
        if char == quote_char:
          quote_char = None
        continue

      if char in {'"', "'"}:
        quote_char = char
        current.append(char)
        continue

      if char in "([{":
        bracket_depth += 1
        current.append(char)
        continue

      if char in ")]}":
        if bracket_depth > 0:
          bracket_depth -= 1
        current.append(char)
        continue

      if char == "," and bracket_depth == 0:
        item = "".join(current).strip()
        if item:
          items.append(item)
        current = []
        continue

      current.append(char)

    tail = "".join(current).strip()
    if tail:
      items.append(tail)

    return items

  def _split_repeated_entity_items(text: str) -> list[str]:
    pattern = re.compile(r'(?i)\b(?:text input|checkbox group|radio group|checkbox|radio|input)\b\s')
    matches = list(pattern.finditer(text))
    if len(matches) < 2:
      return []

    items = []
    for index, match in enumerate(matches):
      start = match.start()
      end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
      item = text[start:end].strip()
      if item:
        items.append(item)
    return items

  def _split_message_title(message: str) -> tuple[str, str] | None:
    current = []
    quote_char = None
    bracket_depth = 0

    for index, char in enumerate(message):
      if quote_char:
        if char == quote_char:
          quote_char = None
        continue

      if char in {'"', "'"}:
        quote_char = char
        continue

      if char in "([{" :
        bracket_depth += 1
        continue

      if char in ")]}":
        if bracket_depth > 0:
          bracket_depth -= 1
        continue

      if char == ":" and bracket_depth == 0:
        title = message[:index].strip()
        remainder = message[index + 1:].strip()
        if title and remainder:
          return title, remainder
        return None

    return None

  def _format_assertion_message(message: str | None) -> dict | None:
    if not message:
      return None

    message = str(message).strip()
    if not message:
      return None

    split_message = _split_message_title(message)
    if not split_message:
      repeated_items = _split_repeated_entity_items(message)
      if repeated_items:
        return {
          "title": None,
          "items": repeated_items,
        }
      return None

    title, remainder = split_message

    items = [part.strip() for part in _split_message_items(remainder) if part.strip()]
    if len(items) <= 1:
      repeated_items = _split_repeated_entity_items(remainder)
      if repeated_items:
        items = repeated_items
    if not items:
      return None

    normalized_items = [re.sub(r"^and\s+", "", item, flags=re.IGNORECASE) for item in items]
    return {
      "title": f"{title}:" if title else None,
      "items": normalized_items,
    }

  for result in all_results:
    test_function = result.get("test_function") or {}
    assertions = test_function.get("assertions") or []
    for assertion in assertions:
      if isinstance(assertion, dict):
        assertion["message_parts"] = _format_assertion_message(assertion.get("message"))

  def _variant_id(r: dict) -> str:
    return (r.get("prompt_variant_id") or "control")

  control_results = [r for r in all_results if _variant_id(r) == "control"]
  results_by_variant = defaultdict(list)
  for r in all_results:
    results_by_variant[_variant_id(r)].append(r)

  all_aggregates = data.get("aggregates", []) or []
  control_aggregates = [a for a in all_aggregates if (a.get("prompt_variant_id") or "control") == "control"]

  prompt_variants_meta = meta_block.get("prompt_variants") or []
  prompt_cases_meta = meta_block.get("prompt_cases") or []
  prompt_variant_meta_by_id = {}
  for pv in prompt_variants_meta:
    if isinstance(pv, dict) and pv.get("id"):
      prompt_variant_meta_by_id[pv.get("id")] = pv

  prompt_case_meta_by_test_name = {}
  for prompt_case in prompt_cases_meta:
    if isinstance(prompt_case, dict) and prompt_case.get("test_name"):
      prompt_case_meta_by_test_name[prompt_case.get("test_name")] = prompt_case

  prompt_variant_names = {"control": "Control"}
  for pv in prompt_variants_meta:
    if isinstance(pv, dict) and pv.get("id"):
      prompt_variant_names[pv.get("id")] = pv.get("name") or pv.get("id")

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

  # Model filter options should only include each model once.
  # model_display_names may include alias keys (e.g. full name and short name)
  # which can cause duplicate labels in the dropdown.
  _model_ids_in_results = sorted({r.get("model_name") for r in all_results if r.get("model_name")})
  model_filter_options = [
    {"value": mid, "label": model_display_names.get(mid, mid.split('/')[-1])}
    for mid in sorted(
      _model_ids_in_results,
      key=lambda m: (model_display_names.get(m, m).casefold(), m.casefold()),
    )
  ]
  
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
    "applicable_total": 0,
    "na": 0,
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
      if a.get("status") == "na":
        a_stats["na"] += 1
      else:
        a_stats["applicable_total"] += 1
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
      "n_generated": s["total"],
      "total_assertion_failures": total_assertion_failures,
      "total_assertion_bp_failures": total_assertion_bp_failures,
      "avg_assertion_failures": avg_assertion_failures,
      "avg_bp_failures": avg_bp_failures,
      "total_failures": total_failures,
      "avg_failures": avg_failures,
    }

  # Detailed results include control + all prompt variants.
  grouped = {}
  for r in all_results:
    key = (r.get("test_name"), r.get("model_name"))
    grouped.setdefault(key, []).append(r)
  grouped_results = OrderedDict()

  # Index aggregates by variant (and include control).
  agg_index_by_variant = {}
  for a in (all_aggregates or []):
    vid = (a.get("prompt_variant_id") or "control")
    agg_index_by_variant[(vid, a.get("test_name"), a.get("model_name"))] = a

  prompts_map = (data.get("prompts") or {})
  for (test_name, model_name), samples in sorted(grouped.items()):
    def _sample_sort_key(x: dict):
      vid = (x.get("prompt_variant_id") or "control")
      si = x.get("sample_index")
      return (vid != "control", vid, si is None, si or 0)

    samples_sorted = sorted(samples, key=_sample_sort_key)
    prompt_case_meta = prompt_case_meta_by_test_name.get(test_name) or {}
    sample_meta = samples_sorted[0] if samples_sorted else {}
    test_entry = grouped_results.setdefault(test_name, {
      "prompt": prompts_map.get(test_name),
      "base_test_name": prompt_case_meta.get("base_test_name") or sample_meta.get("base_test_name"),
      "prompt_dimensions": prompt_case_meta.get("prompt_dimensions") or sample_meta.get("prompt_dimensions") or [],
      "models": [],
    })

    aggregates_by_variant = {}
    for pv in (prompt_variants_meta or []):
      pid = pv.get("id") if isinstance(pv, dict) else None
      if pid:
        agg = agg_index_by_variant.get((pid, test_name, model_name))
        if agg:
          aggregates_by_variant[pid] = agg
    # Always include control aggregate when present (for older runs that might not have prompt_variants meta)
    control_agg = agg_index_by_variant.get(("control", test_name, model_name))
    if control_agg:
      aggregates_by_variant.setdefault("control", control_agg)

    test_entry["models"].append({
      "model_name": model_name,
      "samples": samples_sorted,
      "aggregates_by_variant": aggregates_by_variant,
    })

  # Control aggregate index (used by pass@k tables elsewhere in the report)
  agg_index = {}
  for a in (control_aggregates or []):
    agg_index[(a.get("test_name"), a.get("model_name"))] = a

  summary = OrderedDict(sorted(summary.items(), key=lambda item: (-item[1]["pass_rate"], item[1]["avg_failures"])) )

  # Variant comparisons (instruction sets) vs control
  instruction_benchmark_variants = []
  instruction_benchmark_rows = []
  instruction_benchmark_summary = []
  instruction_set_analysis = []
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

    def _compute_overall_stats(sub_results):
      total = 0
      total_passes = 0
      total_wcag_failures = 0
      for rr in (sub_results or []):
        total += 1
        if rr.get("result") == "PASS":
          total_passes += 1
        tf = rr.get("test_function") or {}
        axe = rr.get("axe") or {}
        total_wcag_failures += (tf.get("total_assertion_failures") or 0)
        total_wcag_failures += (axe.get("failure_count") or 0)
      return {
        "total": total,
        "pass_rate": (total_passes / total) if total else 0.0,
        "avg_wcag_failures": (total_wcag_failures / total) if total else 0.0,
      }

    def _compute_test_stats(sub_results):
      by_test = defaultdict(lambda: {"total": 0, "passes": 0, "total_wcag_failures": 0})
      for rr in (sub_results or []):
        test_name = rr.get("test_name")
        if not test_name:
          continue
        s = by_test[test_name]
        s["total"] += 1
        if rr.get("result") == "PASS":
          s["passes"] += 1
        tf = rr.get("test_function") or {}
        axe = rr.get("axe") or {}
        s["total_wcag_failures"] += (tf.get("total_assertion_failures") or 0)
        s["total_wcag_failures"] += (axe.get("failure_count") or 0)
      out = {}
      for t, s in by_test.items():
        total = s["total"] or 0
        out[t] = {
          "total": total,
          "pass_rate": (s["passes"] / total) if total else 0.0,
          "avg_wcag_failures": (s["total_wcag_failures"] / total) if total else 0.0,
        }
      return out

    def _compute_axe_rule_rates(sub_results):
      total = 0
      counts = defaultdict(int)
      meta = {}
      for rr in (sub_results or []):
        total += 1
        axe = rr.get("axe") or {}
        for f in (axe.get("failures") or []):
          rid = f.get("id")
          if not rid:
            continue
          counts[rid] += 1
          if rid not in meta:
            meta[rid] = {
              "impact": f.get("impact"),
              "description": f.get("description"),
            }
      out = {}
      for rid, c in counts.items():
        out[rid] = {
          "count": c,
          "rate": (c / total) if total else 0.0,
          "impact": (meta.get(rid) or {}).get("impact"),
          "description": (meta.get(rid) or {}).get("description"),
        }
      return {"total": total, "rules": out}

    def _compute_assertion_stats(sub_results):
      by_test = defaultdict(lambda: defaultdict(lambda: {"applicable_total": 0, "fail": 0, "na": 0, "type": "R"}))
      for rr in (sub_results or []):
        test_name = rr.get("test_name")
        if not test_name:
          continue
        tf = rr.get("test_function") or {}
        for a in (tf.get("assertions") or []):
          name = a.get("name")
          if not name:
            continue
          typ = (a.get("type") or "R").upper()
          status = a.get("status")
          if status not in ("pass", "fail", "na"):
            continue
          s = by_test[test_name][name]
          s["type"] = typ
          if status == "na":
            s["na"] += 1
          else:
            s["applicable_total"] += 1
          if status == "fail":
            s["fail"] += 1
      return by_test

    def _read_text_if_available(path_str: str | None) -> str | None:
      if not path_str:
        return None
      raw_path = Path(path_str)
      run_dir = run_json_path.parent
      candidates = []
      if raw_path.is_absolute():
        candidates.append(raw_path)
      else:
        candidates.append(run_dir / raw_path)
        candidates.append(Path.cwd() / raw_path)
        # Prefer repo-root-relative resolution when report is generated from a run dir.
        repo_root = run_dir.parent.parent
        candidates.append(repo_root / raw_path)

      for p in candidates:
        try:
          if p.exists() and p.is_file():
            return p.read_text(encoding="utf-8")
        except Exception:
          continue
      return None

    control_summary_simple = _compute_summary_simple(control_results)
    control_overall = _compute_overall_stats(control_results)
    control_test_stats = _compute_test_stats(control_results)
    control_rules = _compute_axe_rule_rates(control_results)
    control_assertions = _compute_assertion_stats(control_results)

    # Prefer stable ordering based on meta.prompt_variants when present.
    ordered_variant_ids = []
    for pv in (data.get("meta") or {}).get("prompt_variants") or []:
      pid = pv.get("id")
      if pid and pid in variant_ids:
        ordered_variant_ids.append(pid)
    for vid in sorted(variant_ids):
      if vid not in ordered_variant_ids:
        ordered_variant_ids.append(vid)

    # Skill variants are handled in their own section below; skip them here so the
    # instruction-set benchmark doesn't average per-turn records together.
    ordered_instruction_variant_ids = [
      vid for vid in ordered_variant_ids
      if ((prompt_variant_meta_by_id.get(vid) or {}).get("kind") or "instruction_set") != "skill"
    ]

    for vid in ordered_instruction_variant_ids:
      v_results = results_by_variant.get(vid) or []
      v_summary_simple = _compute_summary_simple(v_results)
      pv = prompt_variant_meta_by_id.get(vid) or {}
      variant_name = pv.get("name") or vid

      # Instruction-set analysis (deltas vs control)
      v_overall = _compute_overall_stats(v_results)
      v_test_stats = _compute_test_stats(v_results)
      v_rules = _compute_axe_rule_rates(v_results)
      v_assertions = _compute_assertion_stats(v_results)

      tests_union = sorted(set(control_test_stats.keys()) | set(v_test_stats.keys()))
      test_delta_rows = []
      for test_name in tests_union:
        c = control_test_stats.get(test_name)
        v = v_test_stats.get(test_name)
        if not c or not v:
          continue
        if not c.get("total") or not v.get("total"):
          continue
        test_delta_rows.append({
          "test_name": test_name,
          "control_pass_rate": c.get("pass_rate", 0.0),
          "variant_pass_rate": v.get("pass_rate", 0.0),
          "delta_pass_rate": v.get("pass_rate", 0.0) - c.get("pass_rate", 0.0),
          "control_avg_wcag_failures": c.get("avg_wcag_failures", 0.0),
          "variant_avg_wcag_failures": v.get("avg_wcag_failures", 0.0),
          "delta_avg_wcag_failures": v.get("avg_wcag_failures", 0.0) - c.get("avg_wcag_failures", 0.0),
          "control_total": c.get("total", 0),
          "variant_total": v.get("total", 0),
        })

      # Prefer pass-rate deltas for "helped"/"hurt"; break ties with failures delta.
      interesting_test_rows = [
        r for r in test_delta_rows
        if (abs(r["delta_pass_rate"]) > 1e-12) or (abs(r["delta_avg_wcag_failures"]) > 1e-12)
      ]
      improved_candidates = [
        r for r in interesting_test_rows
        if (r["delta_pass_rate"] > 1e-12) or (abs(r["delta_pass_rate"]) <= 1e-12 and r["delta_avg_wcag_failures"] < -1e-12)
      ]
      regressed_candidates = [
        r for r in interesting_test_rows
        if (r["delta_pass_rate"] < -1e-12) or (abs(r["delta_pass_rate"]) <= 1e-12 and r["delta_avg_wcag_failures"] > 1e-12)
      ]
      improved_tests = sorted(
        improved_candidates,
        key=lambda x: (-x["delta_pass_rate"], x["delta_avg_wcag_failures"], x["test_name"]),
      )[:5]
      regressed_tests = sorted(
        regressed_candidates,
        key=lambda x: (x["delta_pass_rate"], -x["delta_avg_wcag_failures"], x["test_name"]),
      )[:5]

      # Axe WCAG rule deltas (rate per sample)
      rules_union = sorted(set((control_rules.get("rules") or {}).keys()) | set((v_rules.get("rules") or {}).keys()))
      rule_delta_rows = []
      for rid in rules_union:
        c_info = (control_rules.get("rules") or {}).get(rid) or {"count": 0, "rate": 0.0}
        v_info = (v_rules.get("rules") or {}).get(rid) or {"count": 0, "rate": 0.0}
        rule_delta_rows.append({
          "id": rid,
          "control_count": c_info.get("count", 0),
          "variant_count": v_info.get("count", 0),
          "control_rate": c_info.get("rate", 0.0),
          "variant_rate": v_info.get("rate", 0.0),
          "delta_rate": v_info.get("rate", 0.0) - c_info.get("rate", 0.0),
          "impact": v_info.get("impact") or c_info.get("impact"),
          "description": v_info.get("description") or c_info.get("description"),
        })

      reduced_rule_candidates = [r for r in rule_delta_rows if r["delta_rate"] < -1e-12]
      increased_rule_candidates = [r for r in rule_delta_rows if r["delta_rate"] > 1e-12]
      most_reduced_axe_rules = sorted(reduced_rule_candidates, key=lambda x: (x["delta_rate"], x["id"]))[:5]
      most_increased_axe_rules = sorted(increased_rule_candidates, key=lambda x: (-x["delta_rate"], x["id"]))[:5]

      # Assertion deltas (per test)
      assertion_deltas_by_test = OrderedDict()
      assertion_delta_rows_all = []
      tests_with_any_assertions = sorted(set(control_assertions.keys()) | set(v_assertions.keys()))
      for test_name in tests_with_any_assertions:
        c_map = control_assertions.get(test_name) or {}
        v_map = v_assertions.get(test_name) or {}
        assertion_names = sorted(set(c_map.keys()) | set(v_map.keys()))
        rows = []
        for assertion_name in assertion_names:
          c = c_map.get(assertion_name) or {"applicable_total": 0, "fail": 0, "na": 0, "type": "R"}
          v = v_map.get(assertion_name) or {"applicable_total": 0, "fail": 0, "na": 0, "type": c.get("type") or "R"}
          c_total = int(c.get("applicable_total") or 0)
          v_total = int(v.get("applicable_total") or 0)
          c_fail = int(c.get("fail") or 0)
          v_fail = int(v.get("fail") or 0)
          c_na = int(c.get("na") or 0)
          v_na = int(v.get("na") or 0)
          c_fail_rate = (c_fail / c_total) if c_total else None
          v_fail_rate = (v_fail / v_total) if v_total else None
          delta_fail_rate = (v_fail_rate - c_fail_rate) if (c_fail_rate is not None and v_fail_rate is not None) else None
          row = {
            "test_name": test_name,
            "assertion_name": assertion_name,
            "type": (v.get("type") or c.get("type") or "R"),
            "control_total": c_total,
            "control_fail_count": c_fail,
            "control_na_count": c_na,
            "control_fail_rate": c_fail_rate,
            "variant_total": v_total,
            "variant_fail_count": v_fail,
            "variant_na_count": v_na,
            "variant_fail_rate": v_fail_rate,
            "delta_fail_rate": delta_fail_rate,
          }
          rows.append(row)
          if delta_fail_rate is not None:
            assertion_delta_rows_all.append(row)
        # Sort by worst-to-best within the test (variant fail rate desc, then delta)
        rows.sort(key=lambda x: (
          -(x["variant_fail_rate"] if x["variant_fail_rate"] is not None else -1.0),
          -(x["delta_fail_rate"] if x["delta_fail_rate"] is not None else -1.0),
          x["assertion_name"],
        ))
        assertion_deltas_by_test[test_name] = rows

      improved_assertion_candidates = [r for r in assertion_delta_rows_all if (r.get("delta_fail_rate") is not None and r["delta_fail_rate"] < -1e-12)]
      regressed_assertion_candidates = [r for r in assertion_delta_rows_all if (r.get("delta_fail_rate") is not None and r["delta_fail_rate"] > 1e-12)]
      most_improved_assertions = sorted(improved_assertion_candidates, key=lambda x: (x["delta_fail_rate"], x["test_name"], x["assertion_name"]))[:10]
      most_regressed_assertions = sorted(regressed_assertion_candidates, key=lambda x: (-x["delta_fail_rate"], x["test_name"], x["assertion_name"]))[:10]

      instruction_set_analysis.append({
        "variant_id": vid,
        "variant_name": variant_name,
        "control_total_samples": control_overall.get("total", 0),
        "variant_total_samples": v_overall.get("total", 0),
        "control_overall_pass_rate": control_overall.get("pass_rate", 0.0),
        "variant_overall_pass_rate": v_overall.get("pass_rate", 0.0),
        "delta_overall_pass_rate": v_overall.get("pass_rate", 0.0) - control_overall.get("pass_rate", 0.0),
        "control_avg_wcag_failures": control_overall.get("avg_wcag_failures", 0.0),
        "variant_avg_wcag_failures": v_overall.get("avg_wcag_failures", 0.0),
        "delta_avg_wcag_failures": v_overall.get("avg_wcag_failures", 0.0) - control_overall.get("avg_wcag_failures", 0.0),
        "most_improved_tests": improved_tests,
        "most_regressed_tests": regressed_tests,
        "most_reduced_axe_rules": most_reduced_axe_rules,
        "most_increased_axe_rules": most_increased_axe_rules,
        "most_improved_assertions": most_improved_assertions,
        "most_regressed_assertions": most_regressed_assertions,
        "assertion_deltas_by_test": assertion_deltas_by_test,
      })

      custom_instructions_path = pv.get("custom_instructions_path")
      custom_instructions_markdown = _read_text_if_available(custom_instructions_path)
      if not custom_instructions_markdown:
        # Fallback to the embedded meta (if present) in any evaluated sample.
        for rr in v_results:
          gen_meta = rr.get("generation") or {}
          ci = gen_meta.get("custom_instructions")
          if ci:
            custom_instructions_markdown = ci
            break

      instruction_benchmark_variants.append({
        "id": vid,
        "name": variant_name,
        "description": pv.get("description"),
        "n_samples_requested": pv.get("n_samples_requested"),
        "generation_mode": pv.get("generation_mode"),
        "agent_sandbox": _shorten_sandbox(pv.get("agent_sandbox")),
        "agent_limits": pv.get("agent_limits"),
        "custom_instructions_path": custom_instructions_path,
        "custom_instructions_markdown": custom_instructions_markdown,
      })

      model_union = sorted(set(control_summary_simple.keys()) | set(v_summary_simple.keys()))
      if model_union:
        avg_control = sum((control_summary_simple.get(m) or {"pass_rate": 0.0}).get("pass_rate", 0.0) for m in model_union) / len(model_union)
        avg_variant = sum((v_summary_simple.get(m) or {"pass_rate": 0.0}).get("pass_rate", 0.0) for m in model_union) / len(model_union)
      else:
        avg_control = 0.0
        avg_variant = 0.0
      instruction_benchmark_summary.append({
        "variant_id": vid,
        "variant_name": variant_name,
        "avg_control_pass_rate": avg_control,
        "avg_variant_pass_rate": avg_variant,
        "delta_avg_pass_rate": avg_variant - avg_control,
        "n_models": len(model_union),
      })
      for model in model_union:
        c = control_summary_simple.get(model) or {"pass_rate": 0.0, "avg_failures": 0.0}
        v = v_summary_simple.get(model) or {"pass_rate": 0.0, "avg_failures": 0.0}
        instruction_benchmark_rows.append({
          "model_name": model,
          "model_display": model_display_names.get(model, model),
          "variant_id": vid,
          "variant_name": variant_name,
          "control_pass_rate": c["pass_rate"],
          "variant_pass_rate": v["pass_rate"],
          "delta_pass_rate": v["pass_rate"] - c["pass_rate"],
        })

    instruction_benchmark_rows.sort(key=lambda r: (r["model_display"], r["variant_name"]))
    instruction_benchmark_summary.sort(key=lambda r: (-r["avg_variant_pass_rate"], r["variant_name"]))
    for idx, row in enumerate(instruction_benchmark_summary, start=1):
      row["rank"] = idx

  # Build skill benchmark tables. A skill variant emits one results[] record
  # per (sample, turn) so we compute per-turn pass rates separately and compare
  # against control. One table per skill.
  skill_benchmark_tables = []
  skill_benchmark_variants_list = []
  skill_variant_ids_ordered = []
  for pv in prompt_variants_meta or []:
    pid = pv.get("id") if isinstance(pv, dict) else None
    if not pid or pid == "control":
      continue
    if ((pv.get("kind") or "") == "skill") and pid in variant_ids:
      skill_variant_ids_ordered.append(pid)
  # Append skill variants that appear in results but not in meta (defensive).
  for vid in sorted(variant_ids):
    if vid in skill_variant_ids_ordered:
      continue
    if ((prompt_variant_meta_by_id.get(vid) or {}).get("kind") or "") == "skill":
      skill_variant_ids_ordered.append(vid)
  if skill_variant_ids_ordered:
    from collections import defaultdict as _dd
    # Build per-test-per-model pass rates keyed by (variant_id, turn_id).
    # Pass rate is n_pass / n_samples for that (test, model, variant, turn).
    test_stats_by_key = _dd(lambda: {"n_samples": 0, "n_pass": 0})
    for r in all_results:
      vid = (r.get("prompt_variant_id") or "control")
      if vid == "control":
        continue
      pv_kind = ((prompt_variant_meta_by_id.get(vid) or {}).get("kind") or "")
      if pv_kind != "skill":
        continue
      key = (vid, r.get("turn_id"), r.get("test_name"), r.get("model_name"))
      entry = test_stats_by_key[key]
      entry["n_samples"] += 1
      if r.get("result") == "PASS":
        entry["n_pass"] += 1

    # Control stats per (test, model), reused across skills.
    control_stats_by_test_model = _dd(lambda: {"n_samples": 0, "n_pass": 0})
    for r in control_results:
      key = (r.get("test_name"), r.get("model_name"))
      entry = control_stats_by_test_model[key]
      entry["n_samples"] += 1
      if r.get("result") == "PASS":
        entry["n_pass"] += 1

    for vid in skill_variant_ids_ordered:
      pv = prompt_variant_meta_by_id.get(vid) or {}
      turns_meta = pv.get("turns") or []
      if not turns_meta:
        continue

      # Which models appear in this skill's results?
      skill_models = sorted({
        r.get("model_name") for r in results_by_variant.get(vid) or []
        if r.get("model_name")
      })
      # Fallback to all models if none found.
      if not skill_models:
        skill_models = list(model_display_names.keys())

      table_rows = []
      for model_name in skill_models:
        # Per-model control pass rate = mean over tests of n_pass/n_samples.
        ctrl_rates = []
        for test_name in (data.get("tests") or []):
          c = control_stats_by_test_model.get((test_name, model_name))
          if c and c["n_samples"] > 0:
            ctrl_rates.append(c["n_pass"] / c["n_samples"])
        ctrl_pass_rate = (sum(ctrl_rates) / len(ctrl_rates)) if ctrl_rates else 0.0

        turn_pass_rates = []
        for turn in turns_meta:
          tid = turn.get("id")
          per_test_rates = []
          for test_name in (data.get("tests") or []):
            e = test_stats_by_key.get((vid, tid, test_name, model_name))
            if e and e["n_samples"] > 0:
              per_test_rates.append(e["n_pass"] / e["n_samples"])
          turn_rate = (sum(per_test_rates) / len(per_test_rates)) if per_test_rates else 0.0
          turn_pass_rates.append({
            "turn_id": tid,
            "turn_name": turn.get("name") or tid,
            "pass_rate": turn_rate,
            "delta_vs_control": turn_rate - ctrl_pass_rate,
          })

        delta_last_vs_control = (turn_pass_rates[-1]["pass_rate"] - ctrl_pass_rate) if turn_pass_rates else 0.0
        delta_last_vs_first = (
          turn_pass_rates[-1]["pass_rate"] - turn_pass_rates[0]["pass_rate"]
        ) if len(turn_pass_rates) >= 2 else 0.0

        table_rows.append({
          "model_name": model_name,
          "model_display": model_display_names.get(model_name, model_name),
          "control_pass_rate": ctrl_pass_rate,
          "turn_pass_rates": turn_pass_rates,
          "delta_last_vs_control": delta_last_vs_control,
          "delta_last_vs_first": delta_last_vs_first,
        })

      table_rows.sort(key=lambda r: (-(r["turn_pass_rates"][-1]["pass_rate"] if r["turn_pass_rates"] else 0.0), r["model_display"]))
      for idx, row in enumerate(table_rows, start=1):
        row["rank"] = idx

      # Load SKILL.md preview when the skill_path is present in meta.
      skill_md_preview = None
      skill_path = pv.get("skill_path")
      if skill_path:
        skill_md_file = Path(skill_path) / "SKILL.md"
        try:
          if skill_md_file.exists():
            skill_md_preview = skill_md_file.read_text(encoding="utf-8")
        except Exception:
          skill_md_preview = None

      skill_benchmark_tables.append({
        "id": vid,
        "name": pv.get("name") or vid,
        "description": pv.get("description"),
        "turns": turns_meta,
        "rows": table_rows,
      })
      skill_benchmark_variants_list.append({
        "id": vid,
        "name": pv.get("name") or vid,
        "description": pv.get("description"),
        "n_samples_requested": pv.get("n_samples_requested"),
        "agent_sandbox": _shorten_sandbox(pv.get("agent_sandbox")),
        "agent_limits": pv.get("agent_limits"),
        "skill_path": skill_path,
        "skill_md_preview": skill_md_preview,
        "turns": turns_meta,
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
    total = 0
    for _rid, info in (src_dict or {}).items():
      try:
        total += int(info.get("count", 0) or 0)
      except (TypeError, ValueError):
        continue
    items = []
    for rid, info in src_dict.items():
      count = info.get("count", 0)
      try:
        count_int = int(count or 0)
      except (TypeError, ValueError):
        count_int = 0
      items.append({
        "id": rid,
        "count": count_int,
        "percent": (count_int / total) if total else None,
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
      if not s["applicable_total"] and not s["na"]:
        continue
      fail_rate = (s["fail"] / s["applicable_total"]) if s["applicable_total"] else None
      rows.append({
        "name": name,
        "type": s.get("type") or "R",
        "fail_rate": fail_rate,
        "fail_count": s["fail"],
        "applicable_total": s["applicable_total"],
        "na_count": s["na"],
      })
    rows.sort(key=lambda x: (-(x["fail_rate"] if x["fail_rate"] is not None else -1.0), -x["fail_count"], -x["na_count"], x["name"]))
    analysis_assertions_by_test[test_name] = rows[:5]

  html = Template(TEMPLATE).render(
    run_id=data.get("run_id", "unknown"),
    models=data.get("models", []),
    model_display_names=model_display_names,
    model_filter_options=model_filter_options,
    tests=data.get("tests", []),
    summary=summary,
    results=results,
    aggregates=control_aggregates,
    aggregates_by_test=aggregates_by_test,
    grouped_results=grouped_results,
    assertion_names_by_test=assertion_names_by_test,
    prompt_variants=prompt_variants_meta,
    prompt_variant_names=prompt_variant_names,
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
    instruction_benchmark_variants=instruction_benchmark_variants,
    instruction_benchmark_rows=instruction_benchmark_rows,
    instruction_benchmark_summary=instruction_benchmark_summary,
    instruction_set_analysis=instruction_set_analysis,
    skill_benchmark_tables=skill_benchmark_tables,
    skill_benchmark_variants=skill_benchmark_variants_list,
  )
  out_html.write_text(html, encoding="utf-8")
