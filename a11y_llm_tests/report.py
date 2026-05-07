"""HTML reporting for evaluation runs."""
from pathlib import Path
from math import sqrt
import re
import orjson
from jinja2 import Template
from collections import OrderedDict
# importing os module for environment variables
import os

from .report_detail_assets import (
  CONVERSATION_FRAGMENT_TEMPLATE,
  DETAIL_BROWSER_SCRIPT,
  DETAIL_FRAGMENT_TEMPLATE,
  DETAIL_PAGE_SCRIPT,
  DETAIL_PAGE_STYLE,
  DETAIL_PAGE_TEMPLATE,
)
from .report_conversation import (
  _build_turns,
  _conversation_preview,
  _flatten_skill_conversation,
  _read_json_for_report,
)
from .report_file_utils import _read_text_if_available
from .report_pages import (
  _prepare_report_pages,
  _write_conversation_fragment,
  _write_detail_page_artifacts,
)
from .report_stats import (
  _build_skill_per_test_rows,
  _compute_assertion_stats,
  _compute_axe_rule_rates,
  _compute_overall_stats,
  _compute_summary_simple,
  _compute_test_stats,
  _prepare_axe_list,
  _variant_id,
)
from .report_text_utils import _format_assertion_message, _shorten_sandbox

_DEFAULT_PROMPT_VARIANT_URLS = {
  "accessible_minimal": "https://github.com/microsoft/a11y-llm-eval/blob/main/config/instructions/accessible-minimal.md",
  "accessible_basic": "https://github.com/microsoft/a11y-llm-eval/blob/main/config/instructions/accessible-basic.md",
  "building-accessible-ui": "https://github.com/microsoft/a11y-llm-eval/tree/main/config/skills/building-accessible-ui",
}


def _prompt_variant_url(prompt_variant: dict | None) -> str | None:
  if not isinstance(prompt_variant, dict):
    return None
  url = (prompt_variant.get("url") or "").strip()
  if url:
    return url
  return _DEFAULT_PROMPT_VARIANT_URLS.get(prompt_variant.get("id"))


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
.detail-page-card summary h3 {
  display: inline-flex;
  margin: 0;
}
.lazy-load-status {
  margin: 0.75rem 0 0;
  color: var(--text-secondary);
}
.lazy-detail-container {
  margin-top: 1rem;
}
.lazy-detail-container[hidden] {
  display: none;
}
.sample-card h4 {
  margin-top: 0;
  margin-bottom: 0.25rem;
  font-size: 1.05rem;
  color: var(--text-primary);
}
.sample-card h5 {
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
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1rem;
  margin: 1rem 0 1.5rem;
}
.detail-page-grid {
  grid-template-columns: 1fr;
}
.overview-card {
  border: 1px solid var(--border-subtle);
  border-radius: 0.9rem;
  padding: 1rem;
  background: var(--surface);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.12);
}
.overview-card h3,
.overview-subsection h3 {
  margin: 0 0 0.5rem;
  color: var(--text-primary);
}
.overview-stat {
  margin: 0;
  font-size: 1.75rem;
  line-height: 1.1;
  font-weight: 700;
  color: var(--text-primary);
}
.overview-label,
.overview-caption {
  margin: 0.3rem 0 0;
  color: var(--text-secondary);
  font-size: 0.95rem;
}
.overview-subsection {
  margin-top: 1.5rem;
}
.overview-list {
  margin: 0;
  padding-left: 1.15rem;
}
.overview-list li {
  margin-bottom: 0.35rem;
}
.delta-positive { color: #86efac; }
.delta-negative { color: #fca5a5; }
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
/* Conversation modal dialog */
.conversation-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.75rem;
  padding: 0.4rem 0.75rem;
  font-size: 0.88rem;
  font-weight: 600;
  border-radius: 0.5rem;
  border: 1px solid var(--border-strong);
  background: var(--surface-muted);
  color: var(--text-primary);
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.conversation-btn:hover {
  background: var(--surface);
  border-color: var(--accent-strong);
}
.conversation-btn:focus-visible {
  box-shadow: var(--focus-ring);
}
.conversation-dialog {
  max-width: min(56rem, 90vw);
  max-height: 85vh;
  border: 1px solid var(--border-strong);
  border-radius: 0.85rem;
  background: var(--bg-surface);
  color: var(--text-primary);
  padding: 0;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
  overflow: hidden;
}
.conversation-dialog[open] {
  display: flex;
  flex-direction: column;
}
.conversation-dialog::backdrop {
  background: rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(4px);
}
.conversation-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 1rem 1.25rem;
  border-bottom: 1px solid var(--border-subtle);
  background: var(--surface);
  flex-shrink: 0;
}
.conversation-dialog-header h2 {
  margin: 0;
  font-size: 1.1rem;
}
.conversation-dialog-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  border: none;
  border-radius: 0.5rem;
  background: transparent;
  color: var(--text-secondary);
  font-size: 1.25rem;
  cursor: pointer;
}
.conversation-dialog-close:hover {
  background: var(--surface-muted);
  color: var(--text-primary);
}
.conversation-dialog-close:focus-visible {
  box-shadow: var(--focus-ring);
}
.conversation-dialog-body {
  overflow-y: auto;
  padding: 1.25rem;
  flex: 1;
}
body.dialog-open {
  overflow: hidden;
}
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
.skip-link {
  position: absolute;
  left: 1rem;
  top: 1rem;
  z-index: 100;
  transform: translateY(-150%);
  padding: 0.55rem 0.85rem;
  border-radius: 0.5rem;
  background: var(--accent);
  color: var(--text-on-accent);
  font-weight: 700;
  text-decoration: none;
  box-shadow: var(--focus-ring);
}
.skip-link:focus,
.skip-link:focus-visible {
  transform: translateY(0);
  outline: none;
}
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
<a class="skip-link" href="#overview">Skip to report content</a>
{% macro pass_rate_note() -%}
<p class="pass-rate-note"><strong>* Pass rate</strong> reflects only this harness's automated checks (a curated set of axe-core WCAG rules plus hand-written assertions per test case). Automated testing can detect only a subset of accessibility issues: 100% here means the sample passed every check that was run, <strong>not</strong> that the page is WCAG conformant or fully accessible.</p>
{%- endmacro %}
<header>
<h1>{{ site_name }}</h1>
</header>
<main id=\"main\">

<nav class="report-nav" aria-label="Report sections">
  <a href="index.html#overview" data-report-nav="overview">Overview</a>
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

<section id="overview-section" data-report-section="overview">

<section id="overview">
<h2>Overview</h2>
<p>The A11y LLM Eval report provides a summary of accessibility evaluation results for different models, instruction sets, and skills. It can help identify how different approaches impact accessibility outcomes and highlight areas for improvement. All content is generated using GitHub Copilot SDK and results are based on automated checks and curated test cases.</p>
<p class="overview-caption">Run scope: {{ overview.run.model_count }} models | {{ overview.run.prompt_case_count }} prompt cases | {{ overview.run.total_control_samples }} control samples | {{ overview.run.instruction_variant_count }} instruction sets | {{ overview.run.skill_variant_count }} skills</p>

<div class="overview-grid">
  <div class="overview-card">
    <h3>Control baseline</h3>
    <p class="overview-stat">{{ '%.0f%%'|format(overview.control_baseline.pass_rate * 100) }}</p>
    <p class="overview-label">Overall control pass rate*{% if overview.control_leader %}; best model {{ overview.control_leader.display_name }} at {{ '%.0f%%'|format(overview.control_leader.pass_rate * 100) }}{% endif %}</p>
  </div>
  <div class="overview-card">
    <h3>Hardest case</h3>
    {% if overview.hardest_case %}
    <p class="overview-stat">{{ overview.hardest_case.test_name }}</p>
    <p class="overview-label">{{ '%.0f%%'|format(overview.hardest_case.pass_rate * 100) }} pass rate*, {{ '%.2f'|format(overview.hardest_case.avg_wcag_failures) }} avg WCAG failures</p>
    {% else %}
    <p class="overview-stat">None</p>
    <p class="overview-label">No failing control cases were found</p>
    {% endif %}
  </div>
  <div class="overview-card">
    <h3>Best instruction lift</h3>
    <p class="overview-stat">{% if overview.top_instruction %}{{ overview.top_instruction.variant_name }}{% else %}None{% endif %}</p>
    <p class="overview-label">{% if overview.top_instruction %}Best delta {{ '%+.1fpp'|format(overview.top_instruction.delta_avg_pass_rate * 100) }} vs control{% else %}No instruction-set variants in this run{% endif %}</p>
  </div>
  <div class="overview-card">
    <h3>Best skill lift</h3>
    <p class="overview-stat">{% if overview.top_skill %}{{ overview.top_skill.name }}{% else %}None{% endif %}</p>
    <p class="overview-label">{% if overview.top_skill %}Best final-turn delta {{ '%+.1fpp'|format(overview.top_skill.best_delta_last_vs_control * 100) }} vs control{% if overview.top_skill.best_delta_last_vs_first is not none %}; {{ '%+.1fpp'|format(overview.top_skill.best_delta_last_vs_first * 100) }} vs turn 1{% endif %}{% else %}No skill variants in this run{% endif %}</p>
  </div>
</div>

{{ pass_rate_note() }}

<div class="overview-subsection">
  <h3>Control snapshot</h3>
  <p>Control results show how well models produce accessible code with no instructions or prompts to specifically create accessible code.</p>
  <table>
    <thead>
      <tr><th>Model</th><th>Rank</th><th>Pass rate*</th><th>Avg Total WCAG Failures</th></tr>
    </thead>
    <tbody>
      {% for row in overview.control_rows %}
      <tr>
        <th>{{ row.display_name }}</th>
        <td>{{ row.rank }}</td>
        <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(row.pass_rate) }}">{{ '%.0f%%'|format(row.pass_rate * 100) }}</td>
        <td>{{ '%.2f'|format(row.avg_failures) }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>

{% if overview.instruction_rows %}
<div class="overview-subsection">
  <h3>Instruction-set snapshot</h3>
  <p>Instruction-set results show how well models produce accessible code when given specific guidance at the system/instruction level. Instructions guide the agent's behavior throughout the generation session and can improve accessibility outcomes, but they also consume context, especially when they are lengthy or combined with other instructions.</p>
  <table>
    <thead>
      <tr><th>Instruction set</th><th>Rank</th><th>Variant pass rate*</th><th>Delta vs control</th></tr>
    </thead>
    <tbody>
      {% for row in overview.instruction_rows %}
      <tr>
        <th>{% if row.url %}<a href="{{ row.url|e }}">{{ row.variant_name }}</a>{% else %}{{ row.variant_name }}{% endif %}</th>
        <td>{{ row.rank }}</td>
        <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(row.avg_variant_pass_rate) }}">{{ '%.0f%%'|format(row.avg_variant_pass_rate * 100) }}</td>
        <td class="{% if row.delta_avg_pass_rate > 0 %}delta-positive{% elif row.delta_avg_pass_rate < 0 %}delta-negative{% endif %}">{{ '%+.1fpp'|format(row.delta_avg_pass_rate * 100) }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}

{% if overview.skill_rows %}
<div class="overview-subsection">
  <h3>Skill snapshot</h3>
  <p>Skills are reusable, task-specific packages that can include guidance, examples, supporting files, scripts, and tool-use workflows, while instruction sets are always-on guidance added to the agent's context for a run. Use instructions for broad behavior you want applied consistently across tasks; use a skill when the guidance is specialized, larger, procedural, or depends on files, scripts, or a focused sequence of tool-assisted steps. Skills keep general instructions lighter and can guide the model through a process, such as generating an answer and then reviewing it against a checklist.</p>
  <table>
    <thead>
      <tr><th>Skill</th><th>Best model</th><th>Final turn pass rate*</th><th>Delta vs control</th></tr>
    </thead>
    <tbody>
      {% for row in overview.skill_rows %}
      <tr>
        <th>{% if row.url %}<a href="{{ row.url|e }}">{{ row.name }}</a>{% else %}{{ row.name }}{% endif %}</th>
        <td>{{ row.best_model_display }}</td>
        <td class="pass-at-k-cell" data-pass="{{ '%.4f'|format(row.best_final_turn_pass_rate) }}">{{ '%.0f%%'|format(row.best_final_turn_pass_rate * 100) }}</td>
        <td class="{% if row.best_delta_last_vs_control > 0 %}delta-positive{% elif row.best_delta_last_vs_control < 0 %}delta-negative{% endif %}">{{ '%+.1fpp'|format(row.best_delta_last_vs_control * 100) }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}

</section>
</section>

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
  <ul>
    <li>This report is not used for model training, and the testing is not comprehensive. Results should be interpreted as a targeted accessibility evaluation of the included prompt cases, not a complete assessment of model quality or accessibility behavior.</li>
    <li>Each test uses a prompt to generate HTML. The generated HTML is then tested for accessibility.</li>
    {% if not report_include_generated_html_samples %}
    <li>This report intentionally omits direct links to the generated HTML samples. Screenshots and evaluation artifacts remain embedded here, and the generated content is available upon request from <a href="mailto:mfairchild@microsoft.com">mfairchild@microsoft.com</a>.</li>
    {% endif %}
    <li>The prompts intentionally do not include specific accessibility instructions. The goal is to see if the LLMs produce accessible HTML by default.</li>
    <li><strong>All generations are agentic:</strong> Every sample (control, variant, and skill) is generated by the <a href="https://pypi.org/project/github-copilot-sdk/">GitHub Copilot SDK</a> as an agentic session running inside a Docker sandbox. The agent can call built-in tools (e.g. file writes, shell commands) and iteratively refine its output before submitting a final result.</li>
    <li><strong>Control:</strong> The model receives the test prompt with no custom accessibility instructions. This measures baseline accessibility out of the box.</li>
    <li><strong>Instruction-set variants:</strong> The same test prompt is used, but the agent session includes custom instructions (delivered via <code>.github/copilot-instructions.md</code> in the sandbox working directory). This measures how much custom guidance improves accessibility.</li>
    <li><strong>Skills:</strong> The agent runs a multi-turn conversation with explicit turn prompts (e.g. generate, then self-review). A skill directory containing a <code>SKILL.md</code> is mounted so the agent can reference it.</li>
    <li>The resulting HTML is rendered in a browser via Playwright (Chromium). This allows the HTML's JavaScript and CSS to execute, which can impact accessibility.</li>
    <li>The rendered HTML is evaluated using <a href="https://github.com/dequelabs/axe-core">axe-core</a> to identify common accessibility issues.</li>
    <li>A custom test script (JavaScript) is executed against the rendered page to check for accessibility requirements that are specific to the test case and not covered by axe-core. These tests look for <a href="https://www.w3.org/WAI/WCAG22/quickref/">WCAG 2.2</a> failures and best practices. Best practices do not impact pass/fail results.</li>
    <li>Each test case is run multiple times (samples) to evaluate the consistency and reliability of the LLM's output.</li>
    <li>By default, the harness does not explicitly set a temperature, so each provider/model uses its own default sampling behavior.</li>
  </ul>
  {% if methodology_stats.samples_per_model and methodology_stats.detectable_difference_points is not none %}
  <p>
    Based on {{ methodology_stats.prompt_case_count }} prompt cases and {{ methodology_stats.samples_per_case }} samples per case
    ({{ methodology_stats.samples_per_model }} samples per model), this run is roughly powered to detect model WCAG pass-rate
    differences of about {% if methodology_stats.low_power %}more than 100{% else %}{{ '%.1f'|format(methodology_stats.detectable_difference_points) }}{% endif %}
    percentage points or larger in a two-model comparison (approximate 95% confidence, 80% power; assumes independent samples).
  </p>
  <p><small>
    This is a planning heuristic, not a confidence interval reported by the harness. Repeated samples within the same prompt case are correlated,
    so the true detectable difference may be somewhat larger.
  </small></p>
  {% endif %}
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
<h2>Contributors</h2>
  <p>This report and evaluation harness are maintained by Michael Fairchild. For questions about methodology, generated samples, or report interpretation, contact <a href="mailto:mfairchild@microsoft.com">mfairchild@microsoft.com</a>. Contributors include Scott O'hara, Aaron Gustafson, Shawn Lauriat, Dylan Isaac, and Cameron Cundiff. This project would not be possible without the support of the Microsoft Accessibility team and the GitHub Copilot SDK team.</p>
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
  <h3>5/2026 Update</h3>
  <ul>
    <li><strong>Runtime</strong>: Migrated the harness to the GitHub Copilot SDK. All generations now run as agentic Copilot sessions inside the project-owned Docker sandbox, with Copilot session logs captured per run.</li>
    <li><strong>Artifacts &amp; Evaluation</strong>: Added per-sample working directories and multi-file output support, and now evaluate generated artifacts by serving each sample over localhost HTTP so relative CSS, JavaScript, and other assets render under real browser conditions. Empty or invalid HTML is surfaced earlier as a generation failure.</li>
    <li><strong>Skills &amp; Report</strong>: Added multi-turn skills benchmarking, expanded the HTML report with richer agent conversation inspection and skill-specific summaries, and improved report detail visibility for generated samples.</li>
    <li><strong>Providers &amp; Portability</strong>: Improved BYOK provider support with dynamic credential commands such as api_key_cmd, refreshed auth and model documentation, and replaced bash-only helper scripts with Python equivalents for better cross-platform support.</li>
    <li><strong>Test Coverage</strong>: Expanded and tightened accessibility assertions across grouped controls, modal dialogs, disclosure widgets, helper text, required-state detection, skip links, and assistive-technology visibility checks.</li>
  </ul>
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
          {% if v.url %}<p><a href="{{ v.url|e }}">Full instruction set</a></p>{% endif %}
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
    {% if skill.per_test_rows %}
    <details>
      <summary><strong>Pass rate by test case</strong></summary>
      {% for test_row in skill.per_test_rows %}
      <table class="agg-table">
        <caption>{{ test_row.test_name }}</caption>
        <thead>
          <tr>
            <th>Model</th>
            <th>Control*</th>
            {% for t in skill.turns %}
              <th>{{ t.name or t.id }}*</th>
            {% endfor %}
            <th>Δ last vs control*</th>
          </tr>
        </thead>
        <tbody>
          {% for mr in test_row.models %}
          <tr>
            <td>{{ mr.model_display }}</td>
            <td class="pass-at-k-cell" {% if mr.control_pass_rate is not none %}data-pass="{{ '%.4f'|format(mr.control_pass_rate) }}"{% endif %}>{% if mr.control_pass_rate is not none %}{{ '%.0f%%'|format(mr.control_pass_rate * 100) }}{% else %}&mdash;{% endif %}</td>
            {% for tp in mr.turn_pass_rates %}
              <td class="pass-at-k-cell" {% if tp.pass_rate is not none %}data-pass="{{ '%.4f'|format(tp.pass_rate) }}"{% endif %}>{% if tp.pass_rate is not none %}{{ '%.0f%%'|format(tp.pass_rate * 100) }}{% else %}&mdash;{% endif %}</td>
            {% endfor %}
            <td>{% if mr.delta_last_vs_control is not none %}{{ '%+.1fpp'|format(mr.delta_last_vs_control * 100) }}{% else %}&mdash;{% endif %}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      {% endfor %}
      {{ pass_rate_note() }}
    </details>
    {% endif %}
    {% endfor %}
  </section>

  <section id="skill-benchmark-details">
    <h2>Skill details</h2>
    <p>Each skill's mounted package, sandbox location, and per-turn prompt templates.</p>
    {% for v in skill_benchmark_variants %}
      <details>
        <summary>{{ v.name }}</summary>
        {% if v.description %}<p>{{ v.description }}</p>{% endif %}
        {% if v.url %}<p><a href="{{ v.url|e }}">Full skill</a></p>{% endif %}
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
  <p>The detailed sample browser is split into per-test sections. Expand a test below to lazy-load its sample details.</p>
{% if detail_pages %}
<div class="filters" role="region" aria-label="Detailed results global filters">
  <label>
    Model
    <select id="detail-model-filter">
      <option value="">All models</option>
      {% for opt in model_filter_options %}
        <option value="{{ opt.value }}">{{ opt.label }}</option>
      {% endfor %}
    </select>
  </label>
  <label>
    Instruction set
    <select id="detail-variant-filter">
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
    <select id="detail-result-filter">
      <option value="">All results</option>
      <option value="PASS">Pass</option>
      <option value="FAIL">Fail</option>
    </select>
  </label>
  <button type="button" id="detail-reset-filters">Reset</button>
</div>
<p id="detail-filter-count" class="filters-summary" aria-live="polite" aria-atomic="true"></p>
<p id="detail-no-results-message" hidden>No test cases match the current filters.</p>
<div class="overview-grid detail-page-grid">
  {% for detail in detail_pages %}
  <details class="overview-card detail-page-card" data-detail-card data-detail-fragment-src="{{ detail.fragment_path }}" data-detail-models="{{ detail.sample_models|join('|') }}" data-detail-variants="{{ detail.sample_variants|join('|') }}" data-detail-results="{{ detail.sample_results|join('|') }}">
    <summary><h3>{{ detail.test_name }}</h3></summary>
    <p>Samples: {{ detail.sample_count }} | Passes: {{ detail.pass_count }} | Fails: {{ detail.fail_count }}</p>
    <p>Models: {{ detail.model_count }}</p>
    <p class="lazy-load-status" data-lazy-status>Open this panel to load the sample-level details.</p>
    <div class="lazy-detail-container" data-lazy-container></div>
  </details>
  {% endfor %}
</div>
{% else %}
<p>No detailed sample pages are available for this report.</p>
{% endif %}
</section>
  </section>
</main>
<footer>
<p>GitHub Project: <a href="https://github.com/microsoft/a11y-llm-eval">a11y-llm-eval</a>. Run ID: {{ run_id }}</p>
{{ footer_content|safe }}
</footer>
<script>
document.addEventListener('DOMContentLoaded', function () {
  function initDetailBrowsers(root) {
    const browsers = Array.from(root.querySelectorAll('[data-detail-browser]'));

    browsers.forEach(function (browser) {
      if (browser.dataset.filtersInitialized === 'true') {
        return;
      }
      browser.dataset.filtersInitialized = 'true';

      const modelFilter = browser.querySelector('[data-model-filter]');
      const variantFilter = browser.querySelector('[data-variant-filter]');
      const resultFilter = browser.querySelector('[data-result-filter]');
      const resetButton = browser.querySelector('[data-reset-filters]');
      const modelSections = Array.from(browser.querySelectorAll('[data-model-group]'));
      const allCards = Array.from(browser.querySelectorAll('.sample-card'));
      const noResultsMessage = browser.querySelector('[data-no-results-message]');
      const countEl = browser.querySelector('[data-filter-count]');
      const nameFilter = browser.querySelector('[data-assertion-name-filter]');
      const statusFilter = browser.querySelector('[data-assertion-status-filter]');
      const resetAssertionButton = browser.querySelector('[data-assertion-reset-filters]');
      const assertionCountEl = browser.querySelector('[data-assertion-filter-count]');
      const totalCardCount = allCards.length;

      function getExternalFilterValue(attrName, fallback) {
        const value = browser.getAttribute(attrName);
        return value === null ? fallback : value;
      }

      function applyFilters() {
        const modelValue = modelFilter ? modelFilter.value : getExternalFilterValue('data-global-model-filter', '');
        const variantValue = variantFilter ? variantFilter.value : getExternalFilterValue('data-global-variant-filter', 'control');
        const resultValue = resultFilter ? resultFilter.value : getExternalFilterValue('data-global-result-filter', '');
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
        });

        if (noResultsMessage) {
          noResultsMessage.hidden = visibleCardCount > 0;
        }
        if (countEl) {
          countEl.textContent = 'Showing ' + visibleCardCount + ' of ' + totalCardCount + ' samples';
        }
        if (assertionCountEl) {
          assertionCountEl.textContent = 'Showing ' + visibleCardCount + ' of ' + totalCardCount + ' samples in this test case';
        }
      }

      function applyAssertionFilters() {
        const nameValue = nameFilter ? nameFilter.value : '';
        const statusValue = statusFilter ? statusFilter.value : '';

        allCards.forEach(function (card) {
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

      browser.__applyExternalFilters = function (filters) {
        const nextFilters = filters || {};
        browser.setAttribute('data-global-model-filter', nextFilters.model || '');
        browser.setAttribute('data-global-variant-filter', Object.prototype.hasOwnProperty.call(nextFilters, 'variant') ? nextFilters.variant : 'control');
        browser.setAttribute('data-global-result-filter', nextFilters.result || '');
        applyAssertionFilters();
      };

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
          allCards.forEach(function (card) {
            card.classList.remove('hidden-by-assertion');
          });
          applyFilters();
        });
      }

      applyAssertionFilters();
    });
  }

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
      if (hash === 'overview' || hash === 'overview-section') return 'overview';
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

    // Default to overview when present; otherwise keep legacy control-first behavior.
    const initialKey = keyFromHash() || (sectionByKey.has('overview') ? 'overview' : 'control');
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

  let syncLoadedReportDetailPanelFilters = function () {};

  function initGlobalDetailFilters() {
    const modelFilter = document.getElementById('detail-model-filter');
    const variantFilter = document.getElementById('detail-variant-filter');
    const resultFilter = document.getElementById('detail-result-filter');
    const resetButton = document.getElementById('detail-reset-filters');
    const countEl = document.getElementById('detail-filter-count');
    const noResultsMessage = document.getElementById('detail-no-results-message');
    const detailCards = Array.from(document.querySelectorAll('[data-detail-card]'));
    if (!detailCards.length) {
      return;
    }

    function datasetList(card, attr) {
      const raw = card.getAttribute(attr) || '';
      return raw ? raw.split('|').filter(Boolean) : [];
    }

    function syncLoadedPanelFilters(card, modelValue, variantValue, resultValue) {
      const container = card.querySelector('[data-lazy-container]');
      if (!container || !container.children.length) {
        return;
      }
      const browser = container.querySelector('[data-detail-browser]');
      if (browser && typeof browser.__applyExternalFilters === 'function') {
        browser.__applyExternalFilters({
          model: modelValue,
          variant: variantValue,
          result: resultValue,
        });
      }
    }

    function getCurrentGlobalFilterValues() {
      return {
        modelValue: modelFilter ? modelFilter.value : '',
        variantValue: variantFilter ? variantFilter.value : 'control',
        resultValue: resultFilter ? resultFilter.value : '',
      };
    }

    syncLoadedReportDetailPanelFilters = function (card) {
      const current = getCurrentGlobalFilterValues();
      syncLoadedPanelFilters(card, current.modelValue, current.variantValue, current.resultValue);
    };

    function applyGlobalFilters() {
      const current = getCurrentGlobalFilterValues();
      const modelValue = current.modelValue;
      const variantValue = current.variantValue;
      const resultValue = current.resultValue;
      let visibleCount = 0;

      detailCards.forEach(function (card) {
        const models = datasetList(card, 'data-detail-models');
        const variants = datasetList(card, 'data-detail-variants');
        const results = datasetList(card, 'data-detail-results');
        const matchesModel = !modelValue || models.includes(modelValue);
        const matchesVariant = !variantValue || variants.includes(variantValue);
        const matchesResult = !resultValue || results.includes(resultValue);
        const shouldShow = matchesModel && matchesVariant && matchesResult;

        card.style.display = shouldShow ? '' : 'none';
        card.toggleAttribute('hidden', !shouldShow);
        if (!shouldShow) {
          card.open = false;
        } else {
          visibleCount += 1;
          syncLoadedPanelFilters(card, modelValue, variantValue, resultValue);
        }
      });

      if (countEl) {
        countEl.textContent = 'Showing ' + visibleCount + ' of ' + detailCards.length + ' test cases';
      }
      if (noResultsMessage) {
        noResultsMessage.hidden = visibleCount > 0;
      }
    }

    if (modelFilter) {
      modelFilter.addEventListener('change', applyGlobalFilters);
    }
    if (variantFilter) {
      variantFilter.addEventListener('change', applyGlobalFilters);
    }
    if (resultFilter) {
      resultFilter.addEventListener('change', applyGlobalFilters);
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
        applyGlobalFilters();
      });
    }

    applyGlobalFilters();
  }

  initGlobalDetailFilters();

  const detailPanels = Array.from(document.querySelectorAll('[data-detail-fragment-src]'));

  async function fetchHtmlFragment(url) {
    const response = await fetch(url, { credentials: 'same-origin' });
    if (!response.ok) {
      throw new Error('Failed to load report fragment: ' + response.status);
    }
    return response.text();
  }

  detailPanels.forEach(function (panel) {
    panel.addEventListener('toggle', async function () {
      if (!panel.open || panel.dataset.detailLoaded === 'true') {
        return;
      }

      const src = panel.getAttribute('data-detail-fragment-src');
      const container = panel.querySelector('[data-lazy-container]');
      const status = panel.querySelector('[data-lazy-status]');
      if (!src || !container) {
        return;
      }

      if (status) {
        status.textContent = 'Loading sample details...';
      }

      try {
        container.innerHTML = await fetchHtmlFragment(src);
        panel.dataset.detailLoaded = 'true';
        initDetailBrowsers(container);
        syncLoadedReportDetailPanelFilters(panel);
        if (status) {
          status.hidden = true;
        }
      } catch (error) {
        if (status) {
          status.textContent = (error && error.message) ? error.message : 'Failed to load sample details.';
        }
      }
    });
  });

  document.addEventListener('click', async function (e) {
    var openBtn = e.target.closest('[data-opens-dialog]');
    if (openBtn) {
      var dialogId = openBtn.getAttribute('data-opens-dialog');
      var dialog = document.getElementById(dialogId);
      if (!dialog) {
        return;
      }

      var conversationSrc = openBtn.getAttribute('data-conversation-src');
      var body = dialog.querySelector('.conversation-dialog-body');
      if (conversationSrc && body && dialog.dataset.conversationLoaded !== 'true') {
        body.innerHTML = '<p>Loading conversation…</p>';
        try {
          body.innerHTML = await fetchHtmlFragment(conversationSrc);
          dialog.dataset.conversationLoaded = 'true';
        } catch (error) {
          body.innerHTML = '<p>Unable to load conversation preview.</p>';
        }
      }

      dialog.showModal();
      document.body.classList.add('dialog-open');
      return;
    }

    var closeBtn = e.target.closest('[data-closes-dialog]');
    if (closeBtn) {
      var closeDialogId = closeBtn.getAttribute('data-closes-dialog');
      var closeDialog = document.getElementById(closeDialogId);
      if (closeDialog) {
        closeDialog.close();
      }
    }
  });

  document.addEventListener('close', function (e) {
    if (e.target.tagName === 'DIALOG') {
      document.body.classList.remove('dialog-open');
    }
  }, true);
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
  const lowRgb = hexToRgb(lowColor.replace(/\\s/g,''));
  const highRgb = hexToRgb(highColor.replace(/\\s/g,''));

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

def _slugify_report_name(value: str, fallback: str = "item") -> str:
  normalized = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
  return normalized or fallback


def _unique_report_slug(value: str, seen: set[str], fallback: str = "item") -> str:
  base = _slugify_report_name(value, fallback=fallback)
  slug = base
  index = 2
  while slug in seen:
    slug = f"{base}-{index}"
    index += 1
  seen.add(slug)
  return slug


def _report_relative_href(path_str: str | None, run_dir: Path) -> str | None:
  if not path_str:
    return None
  raw_path = Path(path_str)
  if raw_path.is_absolute():
    try:
      return raw_path.resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError:
      return os.path.relpath(raw_path, start=run_dir).replace(os.sep, "/")
  parts = raw_path.as_posix().split("/")
  if len(parts) >= 2 and parts[0] == "runs" and parts[1] == run_dir.name:
    return "/".join(parts[2:])
  return raw_path.as_posix()


def _report_relative_display_path(path_str: str | None, run_dir: Path) -> str | None:
  if not path_str:
    return None
  if "://" in path_str:
    return path_str
  if ":" in path_str:
    prefix, path_part = path_str.split(":", 1)
    if path_part.startswith(("/", "\\")):
      return f"{prefix}:{_report_relative_href(path_part, run_dir)}"
    return path_str
  return _report_relative_href(path_str, run_dir)


def render_report(
  run_json_path: Path,
  out_html: Path,
  models_cfg: dict,
  *,
  include_generated_html_samples: bool = True,
):
  data = orjson.loads(run_json_path.read_bytes())
  meta_block = data.get("meta") or {}
  sampling_meta = meta_block.get("sampling") or {}
  prompting_meta = meta_block.get("prompting") or {}
  from collections import defaultdict

  all_results = data.get("results", []) or []
  run_dir = run_json_path.parent
  if isinstance(prompting_meta, dict) and prompting_meta.get("custom_instructions_path"):
    prompting_meta = dict(prompting_meta)
    prompting_meta["custom_instructions_path"] = _report_relative_display_path(prompting_meta.get("custom_instructions_path"), run_dir)
  report_pages_dir, detail_pages_dir, conversation_pages_dir = _prepare_report_pages(run_dir)

  conversation_slug_seen: set[str] = set()

  for result in all_results:
    conversation_path = result.get("generation_conversation_path")
    conversation = _read_json_for_report(conversation_path, run_dir)
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
    turns = _build_turns(entries)
    conversation_slug = _unique_report_slug(
      "-".join(
        str(part)
        for part in (
          result.get("test_name"),
          result.get("model_name"),
          result.get("prompt_variant_id") or "control",
          result.get("sample_index"),
          result.get("turn_index"),
        )
        if part is not None
      ),
      conversation_slug_seen,
      fallback="conversation",
    )
    conversation_fragment_rel = f"report_pages/conversations/{conversation_slug}.html"
    _write_conversation_fragment(run_dir, conversation_fragment_rel, turns)
    result["generation_conversation"] = {
      "path": conversation_path,
      "entry_count": len(entries),
      "message_count": message_count,
      "event_count": event_count,
      "fragment_path": conversation_fragment_rel,
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

  dialog_slug_seen: set[str] = set()
  for result in all_results:
    result["generation_html_href"] = _report_relative_href(result.get("generation_html_path"), run_dir)
    result["screenshot_href"] = _report_relative_href(result.get("screenshot_path"), run_dir)
    if result.get("generation_conversation"):
      dialog_slug = _unique_report_slug(
        "-".join(
          str(part)
          for part in (
            result.get("test_name"),
            result.get("model_name"),
            result.get("prompt_variant_id") or "control",
            result.get("sample_index"),
            result.get("turn_index"),
          )
          if part is not None
        ),
        dialog_slug_seen,
        fallback="dialog",
      )
      result["conversation_dialog_id"] = f"conv-dialog-{dialog_slug}"

  for result in all_results:
    gen = result.get("generation") or {}
    if gen.get("agent_sandbox"):
      gen["agent_sandbox"] = _report_relative_display_path(gen.get("agent_sandbox"), run_dir)

  for result in all_results:
    test_function = result.get("test_function") or {}
    assertions = test_function.get("assertions") or []
    for assertion in assertions:
      if isinstance(assertion, dict):
        assertion["message_parts"] = _format_assertion_message(assertion.get("message"))

  control_results = [r for r in all_results if _variant_id(r) == "control"]
  results_by_variant = defaultdict(list)
  for r in all_results:
    results_by_variant[_variant_id(r)].append(r)

  all_aggregates = data.get("aggregates", []) or []
  control_aggregates = [a for a in all_aggregates if (a.get("prompt_variant_id") or "control") == "control"]

  prompt_variants_meta = meta_block.get("prompt_variants") or []
  prompt_cases_meta = meta_block.get("prompt_cases") or []
  for pv in prompt_variants_meta:
    if isinstance(pv, dict):
      pv["url"] = _prompt_variant_url(pv)

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
      "sample_count": len(samples_sorted),
      "pass_count": sum(1 for sample in samples_sorted if sample.get("result") == "PASS"),
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
      custom_instructions_markdown = _read_text_if_available(custom_instructions_path, run_dir)
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
        "url": pv.get("url"),
        "n_samples_requested": pv.get("n_samples_requested"),
        "generation_mode": pv.get("generation_mode"),
        "agent_sandbox": _report_relative_display_path(pv.get("agent_sandbox"), run_dir),
        "agent_limits": pv.get("agent_limits"),
        "custom_instructions_path": _report_relative_display_path(custom_instructions_path, run_dir),
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
        "url": _prompt_variant_url(pv),
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
        "per_test_rows": _build_skill_per_test_rows(
          vid, turns_meta, skill_models, data.get("tests") or [],
          test_stats_by_key, control_stats_by_test_model, model_display_names,
        ),
      })
      skill_benchmark_variants_list.append({
        "id": vid,
        "name": pv.get("name") or vid,
        "description": pv.get("description"),
        "url": pv.get("url"),
        "n_samples_requested": pv.get("n_samples_requested"),
        "agent_sandbox": _report_relative_display_path(pv.get("agent_sandbox"), run_dir),
        "agent_limits": pv.get("agent_limits"),
        "skill_path": _report_relative_display_path(skill_path, run_dir),
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

  for test_name, test_data in grouped_results.items():
    test_data["assertion_filter_options"] = assertion_names_by_test.get(test_name, [])
    test_data["model_filter_options"] = [
      {
        "value": group["model_name"],
        "label": model_display_names.get(group["model_name"], group["model_name"]),
      }
      for group in (test_data.get("models") or [])
    ]
    variant_option_map = OrderedDict()
    for group in (test_data.get("models") or []):
      for sample in (group.get("samples") or []):
        variant_id = sample.get("prompt_variant_id") or "control"
        if variant_id == "control" or variant_id in variant_option_map:
          continue
        variant_option_map[variant_id] = prompt_variant_names.get(variant_id, variant_id)
    test_data["variant_filter_options"] = [
      {"value": variant_id, "label": label}
      for variant_id, label in variant_option_map.items()
    ]

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
  common_axe_failures = _prepare_axe_list(axe_wcag_failure_stats)
  common_axe_bp_failures = _prepare_axe_list(axe_bp_failure_stats)

  prompt_case_count = len(data.get("tests", []) or [])
  samples_per_case = int(sampling_meta.get("samples_per_case", 0) or 0)
  samples_per_model = prompt_case_count * samples_per_case
  detectable_difference = sqrt(3.92 / samples_per_model) if samples_per_model > 0 else None
  methodology_stats = {
    "prompt_case_count": prompt_case_count,
    "samples_per_case": samples_per_case,
    "samples_per_model": samples_per_model,
    "detectable_difference_points": (detectable_difference * 100.0) if detectable_difference is not None else None,
    "low_power": detectable_difference is not None and detectable_difference >= 1.0,
  }

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

  summary_rows = []
  for rank, (model_name, stats) in enumerate(summary.items(), start=1):
    summary_rows.append({
      "model_name": model_name,
      "display_name": model_display_names.get(model_name, model_name),
      "rank": rank,
      "pass_rate": stats["pass_rate"],
      "avg_failures": stats["avg_failures"],
    })

  skill_overview_rows = []
  for table in skill_benchmark_tables:
    best_row = None
    for row in table.get("rows") or []:
      if best_row is None:
        best_row = row
        continue
      best_final = best_row.get("turn_pass_rates")[-1]["pass_rate"] if best_row.get("turn_pass_rates") else 0.0
      row_final = row.get("turn_pass_rates")[-1]["pass_rate"] if row.get("turn_pass_rates") else 0.0
      if row_final > best_final:
        best_row = row
        continue
      if row_final == best_final and row.get("delta_last_vs_control", 0.0) > best_row.get("delta_last_vs_control", 0.0):
        best_row = row
    if not best_row:
      continue
    final_turn_pass_rate = best_row.get("turn_pass_rates")[-1]["pass_rate"] if best_row.get("turn_pass_rates") else 0.0
    skill_overview_rows.append({
      "id": table.get("id"),
      "name": table.get("name"),
      "url": _prompt_variant_url(prompt_variant_meta_by_id.get(table.get("id"))),
      "best_model_name": best_row.get("model_name"),
      "best_model_display": best_row.get("model_display"),
      "best_final_turn_pass_rate": final_turn_pass_rate,
      "best_delta_last_vs_control": best_row.get("delta_last_vs_control", 0.0),
      "best_delta_last_vs_first": best_row.get("delta_last_vs_first"),
    })

  skill_overview_rows.sort(key=lambda row: (-row["best_final_turn_pass_rate"], -row["best_delta_last_vs_control"], row["name"]))

  control_sample_count = len(control_results)
  control_pass_count = sum(1 for row in control_results if row.get("result") == "PASS")
  control_baseline = {
    "pass_rate": (control_pass_count / control_sample_count) if control_sample_count else 0.0,
    "sample_count": control_sample_count,
  }

  overview = {
    "run": {
      "model_count": len(summary_rows),
      "prompt_case_count": prompt_case_count,
      "total_control_samples": control_sample_count,
      "instruction_variant_count": len(instruction_benchmark_summary),
      "skill_variant_count": len(skill_overview_rows),
    },
    "control_rows": summary_rows[:5],
    "control_baseline": control_baseline,
    "control_leader": summary_rows[0] if summary_rows else None,
    "hardest_case": global_hardest_tests[0] if global_hardest_tests else None,
    "hardest_tests": global_hardest_tests[:3],
    "instruction_rows": instruction_benchmark_summary[:5],
    "skill_rows": skill_overview_rows[:5],
    "top_instruction": instruction_benchmark_summary[0] if instruction_benchmark_summary else None,
    "top_skill": skill_overview_rows[0] if skill_overview_rows else None,
  }

  detail_pages = []
  detail_slug_seen: set[str] = set()
  for test_name, test_data in grouped_results.items():
    sample_count = sum(len(group.get("samples") or []) for group in test_data.get("models") or [])
    if sample_count <= 0:
      continue
    sample_models = sorted({
      group.get("model_name")
      for group in (test_data.get("models") or [])
      if group.get("model_name")
    })
    sample_variants = []
    seen_variants = set()
    sample_results = []
    seen_results = set()
    for group in (test_data.get("models") or []):
      for sample in (group.get("samples") or []):
        variant_id = sample.get("prompt_variant_id") or "control"
        if variant_id not in seen_variants:
          sample_variants.append(variant_id)
          seen_variants.add(variant_id)
        result_value = sample.get("result")
        if result_value and result_value not in seen_results:
          sample_results.append(result_value)
          seen_results.add(result_value)
    pass_count = sum(
      1
      for group in (test_data.get("models") or [])
      for sample in (group.get("samples") or [])
      if sample.get("result") == "PASS"
    )
    detail_slug = _unique_report_slug(test_name, detail_slug_seen, fallback="detail")
    detail_fragment_rel = f"report_pages/details/{detail_slug}.fragment.html"
    detail_page_rel = f"report_pages/details/{detail_slug}.html"
    _write_detail_page_artifacts(
      run_dir=run_dir,
      detail_fragment_rel=detail_fragment_rel,
      detail_page_rel=detail_page_rel,
      test_name=test_name,
      test_data=test_data,
      model_display_names=model_display_names,
      prompt_variant_names=prompt_variant_names,
      include_generated_html_samples=include_generated_html_samples,
      site_name=os.getenv("SITE_NAME", "A11y LLM Eval"),
    )
    detail_pages.append({
      "test_name": test_name,
      "base_test_name": test_data.get("base_test_name"),
      "prompt_dimensions": test_data.get("prompt_dimensions") or [],
      "sample_count": sample_count,
      "pass_count": pass_count,
      "fail_count": max(sample_count - pass_count, 0),
      "model_count": len(test_data.get("models") or []),
      "sample_models": sample_models,
      "sample_variants": sample_variants,
      "sample_results": sample_results,
      "fragment_path": detail_fragment_rel,
      "page_path": detail_page_rel,
    })

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
    methodology_stats=methodology_stats,
    overview=overview,
    detail_pages=detail_pages,
    report_include_generated_html_samples=include_generated_html_samples,
  )
  out_html.write_text(html, encoding="utf-8")
