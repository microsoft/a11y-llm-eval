# Features & Acceptance Criteria (Backwards-Compatibility Contract)

This document describes the **current, user-visible behavior** of the A11y LLM Evaluation Harness.

It is intended to prevent accidental behavior changes. If you change behavior intentionally, you must:

1. Update this document.
2. Update/add tests that lock the new behavior.
3. Note any migration steps if the change is breaking.

---

## Scope

This document covers:

- CLI commands and expected artifacts on disk.
- Run directory structure and `results.json` shape.
- How pass/fail is determined.
- Sampling semantics (multi-generation) and `pass@k` aggregates.
- Prompting + caching semantics that affect reproducibility and costs.
- Node/Playwright runner contract (inputs/outputs).

It does **not** attempt to specify the internal HTML report layout pixel-perfect; instead it specifies the report output location and key data it summarizes.

Inspect runtime logs may be written as additive metadata and files under the run directory. Current implementations may write structured JSONL generation logs under `inspect_logs/`. These logs are not part of the compatibility-critical artifact contract unless explicitly documented otherwise.

---

## Glossary

- **Base test case**: a folder under `test_cases/<name>/` containing `prompt.yaml` and `test.js`.
- **Prompt case**: one concrete composed prompt produced from a base test case plus the selected local and global prompt dimensions.
- **Model name**: the string used as `models[].name` in `config/models.yaml` (also used in filenames).
- **Sample**: one independent generation for a (prompt case, model). Samples are indexed 0-based.
- **Requirement assertion** (`type: "R"`): affects pass/fail.
- **Best Practice assertion** (`type: "BP"`): tracked, but does not affect pass/fail.
- **Not applicable assertion** (`status: "na"`): an assertion that does not apply to that sample. Requirement N/A assertions exclude the sample from denominator-based pass metrics.
- **WCAG failures**: the subset of axe violations that are *not* tagged `best-practice`.

---

## Feature: Two-phase workflow (Generate → Evaluate)

### Behavior

The harness supports a two-phase workflow:

1. `run` generates HTML artifacts and a stub `results.json` (no evaluation performed).
2. `evaluate` runs Playwright + axe-core + per-test assertions against the generated HTML, writes evaluated `results.json`, and optionally generates `index.html`.

### Acceptance criteria

- `python -m a11y_llm_tests.cli run ...`:
  - Creates a timestamped run directory at `<out>/<YYYY-MM-DD_HH-MM-SS>/`.
  - Creates `<run_dir>/raw/` and `<run_dir>/screenshots/`.
  - Writes `<run_dir>/results.json` with:
    - `meta.status == "GENERATED_ONLY"`.
    - `aggregates == []` (must be empty pre-evaluation).
  - `--test-cases single-checkbox,modal-dialog` limits generation to only the named base test cases. All dimension variants of the selected tests are still generated. Defaults to all test cases when omitted.
    - Unknown test case names produce a clear error listing available names.
- `python -m a11y_llm_tests.cli evaluate <run_dir> ...`:
  - Requires an existing run directory.
  - Writes/overwrites `<run_dir>/results.json` with:
    - `meta.status == "EVALUATED"`.
    - `results` containing evaluated records.
    - `aggregates` containing pass@k records (see Sampling section).
  - If report generation is enabled (default), writes `<run_dir>/index.html`.
  - `--test-cases single-checkbox,modal-dialog` limits evaluation to only the named base test cases from the existing run. Defaults to all test cases when omitted.

---

## Feature: Test case structure

### Behavior

A test case directory is considered runnable if:

- It is a subdirectory of `test_cases/`.
- It contains `prompt.yaml`.

During evaluation, `test.js` is loaded and executed by the Node runner.

### Acceptance criteria

- `prompt.yaml` is treated as the canonical prompt specification for the base test case.
- `prompt.yaml` must include at least:
  - `base_prompt`
  - optional `name`
  - optional `common_requirements`
  - optional local `dimensions`
- The harness composes one user prompt per cross-product combination of:
  - local dimensions from the base test case
  - global dimensions from `config/prompt_dimensions.yaml` or the file passed via `run --prompt-dimensions-file`
- Each composed prompt becomes its own prompt case with a stable `prompt_case_id` and a user-visible `test_name`.
- `test.js` is expected to export `module.exports.run = async ({ page, assert, utils }) => { ... }`.
- If `test.js` does not export a `run` function, the Node runner returns an error in `testFunctionResult.error`.

---

## Feature: Generation (LLM) + prompt configuration

### Behavior

Generation uses the Inspect-backed harness runtime with:

- A system message that is the **effective system prompt**.
- A user message that is the composed prompt case text built from `prompt.yaml` plus the configured global prompt dimensions.

For providers that do not opt out, generation may submit multiple uncached prompts together for the same model when their effective request settings match.

Mixed direct-plus-agent runs may batch eligible non-agent requests while agent requests execute per-request.

The effective system prompt is:

- `DEFAULT_SYSTEM_PROMPT`, unless overridden.
- Optionally appended with custom instructions text.

`config/models.yaml` supports defaults:

- `defaults.system_prompt` (string)
- `defaults.custom_instructions_markdown` (path to a markdown file)
- `defaults.temperature` (float)

`config/models.yaml` may also define provider-level configuration under `providers.<provider>`.

- `providers.<provider>.auth.mode` may be omitted or set to `env` to preserve the runtime's existing environment-based behavior.
- `providers.<provider>.batch.enabled` may be omitted or set to `true` to allow grouped batch submission for eligible generation groups; set it to `false` to force per-request generation for that provider.
- `providers.azure.auth.mode`, `providers.azure_ai.auth.mode`, and `providers.azureai.auth.mode` may be set to `default_azure_credential`.
- For `azure`, the harness reads `api_base` from `api_base_env` and optionally reads `api_version` from `api_version_env`, defaulting to `AZURE_API_BASE` / `AZURE_API_VERSION`, and passes an Azure bearer token provider into the runtime.
- For `azure_ai` and `azureai`, the harness reads the base URL from `api_base_env`, defaulting to `AZUREAI_BASE_URL`, and sets the Inspect Azure AI managed-identity audience via `audience_env`, defaulting to `AZUREAI_AUDIENCE`.
- When `default_azure_credential` is configured, `azure-identity` must be installed; otherwise generation fails with a clear error.

If `run --temperature` is not provided, the effective temperature defaults to `defaults.temperature` if present.

If neither `run --temperature` nor `defaults.temperature` is provided, the harness omits `temperature` from the generation request so the provider/model default temperature is used.

Note: some Codex-style deployments (e.g., certain `*-codex` models) do not accept sampling parameters like `temperature`. For these models, the harness omits `temperature` from the generation request to avoid provider errors.

### Acceptance criteria

- Generated output is a **single standalone HTML document**.
- The generator normalizes model output by:
  - Stripping Markdown fences if present.
  - Extracting the first `<html> ... </html>` block if present.
- If the provider indicates the output was truncated due to an output token limit (e.g., `finish_reason == "length"`), generation exits early with a non-zero exit code to avoid incurring additional generation costs.
- Prompt hashing:
  - `compute_prompt_hash(user_prompt)` depends on the configured system prompt, custom instructions, and the user prompt.
  - Changing system prompt or custom instructions changes the hash.

---

## Feature: Generation caching

### Behavior

Generated HTML is cached under `.cache/generations/`.

Agent-backed generations use a separate cache identity from direct generations. When an agent generation is cached, the harness also caches the agent conversation payload needed to recreate the per-run `.agent.json` sidecar. Cached agent hits do not create a fresh Inspect eval log for the new run.

Cache identity includes:

- Model name
- Prompt hash
- Seed (if provided)
- Sample iteration index
- Generation mode (agent vs. direct)

On cache hits, the generator returns `cached: True` and can optionally load token/cost metadata from a `.meta.json` file.

When batch generation is enabled for a provider, cache identity and cache validation remain per request. Cached requests are not submitted to grouped batch generation; only cache misses are sent.

### Acceptance criteria

- Cache files are created at:
  - `.cache/generations/<model>_<promptHash>_s<seed>_i<iteration>.html` (when seed is provided)
  - `.cache/generations/<model>_<promptHash>_i<iteration>.html` (when seed is not provided)
  - `.cache/generations/<model>_<promptHash>_s<seed>_i<iteration>_agent.html` (agent mode with seed)
  - `.cache/generations/<model>_<promptHash>_i<iteration>_agent.html` (agent mode without seed)
- The cache directory may also contain sidecar integrity files (e.g., `.sha256`) alongside cached HTML.
- Agent-mode cache entries may additionally include a cached transcript sidecar used to recreate the run-local `.agent.json` artifact on cache hits.
- Direct and agent mode cache entries are independent; running one mode does not invalidate the other.
- If a cached HTML file is incomplete/corrupted, it is treated as a cache miss and a fresh generation is performed.
- Debugging: `run --debug-truncated-cache` prints a list of truncated/corrupted cached HTML files at the end of generation and preserves them for inspection.
- The `--disable-cache` flag forces fresh generation even if a cache entry exists.
- If grouped batch generation is attempted for a group and the batch call or an individual item fails, the harness falls back to the existing per-request generation path for the affected requests.

---

## Feature: Run directory artifacts and naming

### Behavior

During `run`, generated HTML is written under:

- `<run_dir>/raw/<prompt_case_id>/`

Naming depends on `--samples`:

- Multi-sample (`samples > 1`): `<model>__s<sample_index>.html`
- Legacy single-sample (`samples == 1`): `<model>.html`

During `evaluate`, screenshots are written under:

- `<run_dir>/screenshots/`

Screenshot naming:

- Multi-sample: `<prompt_case_id>__<model>__s<sample_index>.png`
- Legacy single-sample: `<prompt_case_id>__<model>.png`

### Acceptance criteria

- Multi-sample HTML naming uses `__s` with a 0-based `sample_index`.
- For legacy single-sample runs, `sample_index` is `null` in `results.json`.
- Evaluation may reconstruct prompt cases from the stub `results[]` written during `run` and uses stored `generation_html_path` values as the source of truth for generated artifacts.

---

## Feature: Prompt variants (instruction benchmarks)

### Behavior

The harness can optionally benchmark multiple **instruction sets** (custom instructions appended at the system prompt level) against the **control** using the same test cases.

This is enabled via `run --instruction-sets-file <path>`.

- Control behavior when instruction sets are enabled:
  - Control is generated using the configured base system prompt **with no custom instructions**.
- Each instruction set is benchmarked **separately** (no combining instruction sets).
- Instruction sets may request a different number of samples than control.
- Instruction sets always use the sandboxed Inspect ReAct agent path.
- Instruction-set YAML does not support `generation_mode`; configs that specify it are invalid.
- Instruction sets may declare `agent.sandbox` as an Inspect sandbox spec (for Docker compose, a two-item value equivalent to `("docker", "compose.yaml")`) plus additive `agent.limits` overrides.
- `agent.limits` accepts a `tool_timeout` key (seconds) bounding each individual tool call (bash, text_editor, python). Defaults to 60 and is clamped to `[10, working_limit]`.
- Concurrent agent (Docker sandbox) generations default to at most 4 in parallel when `--processes` is not specified. Pass `--processes` explicitly to override.

Artifacts for variants are written under separate directories:

- Variant HTML: `<run_dir>/raw_variants/<variant_id>/<prompt_case_id>/<model>__s<sample_index>.html`
- Agent conversation sidecar for agent-mode variants: `<run_dir>/raw_variants/<variant_id>/<prompt_case_id>/<model>__s<sample_index>.agent.json`
- Variant screenshots: `<run_dir>/screenshots_variants/<variant_id>/<prompt_case_id>__<model>__s<sample_index>.png`

Schema additions:

- Each `results[]` record includes `prompt_variant_id` ("control" or the instruction set id).
- Each `results[]` record includes `base_test_name`, `prompt_case_id`, and `prompt_dimensions` for the composed prompt case.
- Each `results[]` record may include `generation_conversation_path` for instruction-set samples.
- Each `results[]` record may include `generation_eval_path` for instruction-set samples when an Inspect eval log file is produced or restored from cache.
- Each `aggregates[]` record includes `prompt_variant_id`.
- Each `aggregates[]` record includes `base_test_name`, `prompt_case_id`, and `prompt_dimensions` for the composed prompt case.
- `generation` metadata may additionally include `generation_mode`, `agent_sandbox`, `agent_limit_error`, and `agent_limits`.
- `meta.prompt_variants` describes the variants included in the run (id/name/description/custom instruction path/sample count, and agent metadata for instruction sets).
- `meta.prompt_cases` describes the expanded prompt cases included in the run.

### Acceptance criteria

- When `--instruction-sets-file` is provided:
  - Control samples are still written to `<run_dir>/raw/` using existing naming rules.
  - Variant samples are written to `<run_dir>/raw_variants/<variant_id>/...` using `__s<idx>` naming.
  - Instruction-set variants additionally write a conversation JSON sidecar beside each generated HTML file.
  - Instruction-set variants use the default generation cache across runs; on cache hits they still write the conversation JSON sidecar. When a cached `.eval` log exists, it is restored into the run's `inspect_logs/` directory and `generation_eval_path` is populated so the report can link to it. If no cached eval log is available, `generation_eval_path` is left unset.
  - `results.json` includes `meta.prompt_variants` with at least:
    - a `control` entry
    - one entry per configured instruction set

- When `--instruction-sets-file` is not provided:
  - No `raw_variants/` or `screenshots_variants/` outputs are required.
  - Existing single-run behavior remains unchanged.

---

## Feature: Skills benchmark (multi-turn)

### Behavior

The harness can benchmark **skills** — self-contained packages of files (at minimum a `SKILL.md`) that are mounted into the agent sandbox at runtime. Unlike instruction sets, a skill declares a sequence of user **turns**, and the agent's submission at the end of each turn is evaluated **independently** so the report can compare control vs turn 1 vs turn 2 vs … per (test, model).

This is enabled via `run --skills-file <path>` and is independent of `--instruction-sets-file` (both may be supplied in the same run).

- Each skill declares `id`, `name`, optional `description`, a `skill_path` (directory containing `SKILL.md`), `agent` settings (same shape as instruction-set `agent`), and a required **non-empty** `turns` list.
- Each turn declares `id`, `name` (optional), and a `prompt` template.
- Exactly **one** turn prompt in a skill must contain the token `{{test_case_prompt}}`. Other supported tokens: `{{skill_id}}`, `{{skill_path}}`, `{{previous_submission}}`.
- Turn ids must be unique within the skill; skill ids must be unique across skills and must not collide with instruction-set ids or the reserved id `control`.
- Skills always use the sandboxed Inspect ReAct agent path; `generation_mode` is not supported.
- The skill directory is mounted at `/workspace/.skills/<skill_id>/` in the sandbox (every file under the host skill dir is mapped in).
- Each turn is a separate user message; earlier turns' assistant replies are preserved as seed messages for subsequent turns.
- Per-turn generation caching: the cache key for turn k includes the model, seed, iteration, skill id, hash of all skill files, turn index, and a cumulative hash of all rendered turn prompts up to and including turn k. Changing turn 2's prompt invalidates turn 2's cache but not turn 1's.
- Partial failure: if a turn errors or hits a model/agent limit, that turn's record is marked ERROR, subsequent turns for that sample are emitted as ERROR records with `aborted_reason` set, and earlier turns remain evaluated normally.

Artifacts for skills are written under separate directories:

- Skill HTML: `<run_dir>/raw_skills/<skill_id>/<prompt_case_id>/<model>__s<sample_index>__t<turn_index>.html`
- Skill agent conversation sidecar (one per sample, stitched across turns): `<run_dir>/raw_skills/<skill_id>/<prompt_case_id>/<model>__s<sample_index>.agent.json`
- Skill screenshots: `<run_dir>/screenshots_skills/<skill_id>/<prompt_case_id>__<model>__s<sample_index>__t<turn_index>.png`

Schema additions:

- Each `results[]` record for a skill turn includes `prompt_variant_kind = "skill"`, `turn_id`, `turn_index` (0-based), and `turn_count_total`.
- Each `aggregates[]` record for a skill turn includes `prompt_variant_kind`, `turn_id`, and `turn_index`. Aggregates are grouped by `(test_name, base_test_name, prompt_case_id, model, prompt_variant_id, prompt_variant_kind, turn_id)` so every turn has its own pass@k row.
- `meta.prompt_variants` entries for skills carry `kind: "skill"`, `skill_path`, and `turns` (the resolved list of `{id, name, prompt}` objects).

### Acceptance criteria

- When `--skills-file` is provided:
  - Control samples are still written to `<run_dir>/raw/` using existing naming rules.
  - For every configured skill, every (test, model, sample) produces one HTML file per turn named `…__s<idx>__t<turn_index>.html`, plus one stitched `.agent.json` sidecar per sample.
  - `results.json` includes one result record per (test, model, sample, turn) with `prompt_variant_kind = "skill"`.
  - `results.json` includes one aggregate per (test, model, skill, turn).
  - `meta.prompt_variants` includes an entry per skill with `kind: "skill"` and a non-empty `turns` list.
  - The generated HTML report renders a **Skills** section with one table per skill and dynamic columns for control + each turn, plus the SKILL.md preview under skill details.

- When `--skills-file` is not provided:
  - No `raw_skills/` or `screenshots_skills/` outputs are required.
  - No skill section is rendered in the HTML report.

---

## Feature: Evaluation (pass/fail logic)

### Behavior

Each evaluated record includes:

- Node runner output mapped into:
  - `test_function` (assertions)
  - `axe` (WCAG + best practice buckets)
- Overall `result` computed in Python as:

$$\text{PASS} \iff (\text{test\_function.status} = \text{"pass"}) \land (\text{axe.failure\_count} = 0)$$

### Acceptance criteria

- Assertions are normalized in Python:
  - Only dict-shaped assertions are considered.
  - `type` is normalized to uppercase and defaults to `"R"` if missing/invalid.
  - `status` accepts `"pass"`, `"fail"`, and `"na"`; legacy aliases normalize to those values.
  - Only `"R"` and `"BP"` are valid types; others become `"R"`.

### Test-case-specific assertion semantics

- Disclosure widget: `Collapsed content is hidden from everyone`
  - For button-based disclosure implementations, collapsed content must be hidden from assistive technology.
  - The visual-hidden check is evaluated against the collapsed content area, not decorative container chrome alone.
  - A collapsed disclosure container may still render decorative borders or similar non-content styling and pass, so long as the content box is collapsed/clipped and the disclosure content itself is not visually exposed.
- Shopping home page: `Has a skip navigation link`
  - The page must include at least one link whose accessible name indicates bypassing repeated navigation, such as `Skip nav`, `Skip to main`, `Skip header`, `Jump to main`, or `Go to main`.
  - The skip link must target the page's single `main` landmark or a same-page fragment target at the start of the main content.
  - The target must be keyboard focusable, either by being in the focus order or by exposing `tabindex="-1"`.
  - A target later in the main content does not satisfy this assertion.
  - If the page does not expose exactly one `main` landmark, this assertion fails.
- Assertion helpers may return `"na"` when a check has no applicable target on the page, for example when no visible labels, helper text, placeholder text, or recognizable autocomplete purpose exist for that assertion.
- Required-field assertions may treat a shared visible note such as `All questions are required.` or `All fields are required.` as a valid visual indicator for the relevant required controls or radio groups.
- For native checkbox or radio groups that visibly require choosing one or at least one option but do not expose a valid group-level programmatic required state, the programmatic required-field assertion may return `"na"` rather than failing each item individually.
- For native checkbox fieldsets where only the group label indicates the group is required, both required-field assertions may return `"na"` because the label can represent a minimum-selection rule rather than each checkbox being individually required.
- When native checkbox or radio controls conflict with ARIA required state, required-field assertions use the native `required` state while ARIA/native mismatch assertions still report the conflict.
- Best practice assertions (`BP`) do not affect overall pass/fail.
- Requirement assertions marked `na` are tracked at the assertion level and do not change sample-level pass/fail or aggregate denominators.
- Axe data handling is permissive:
  - The Python evaluator accepts `axeResult`, `axe_result`, or `axe` keys from Node output.
  - If `axe.failure_count` is missing, it is treated as `0`.

---

## Feature: Sampling and pass@k aggregates

### Behavior

The CLI supports multiple samples per (test, model) via `--samples` and computes pass@k after evaluation.

For each (test_name, model_name) pair, `aggregates[]` contains:

- `n_samples`
- `n_applicable`
- `n_not_applicable`
- `n_pass`
- `pass_at_k` for requested k values

Pass@k uses the full sample set:

$$\text{pass@k} = 1 - \frac{\binom{n-c}{k}}{\binom{n}{k}}$$

where $n = n_{samples}$ and $c = n_{pass}$.

with edge cases:

- $c=0 \Rightarrow 0$
- $c=n \Rightarrow 1$
- $k>n$ is treated as $k=n$

### Acceptance criteria

- `--base-seed` (when provided) yields `seed = base_seed + sample_index`.
- `sample_index` values in `results.json` are 0-based and cover the full range `[0, samples-1]` for multi-sample runs.
- `pass_at_k` is stored with **string keys** (e.g. `"1"`, `"5"`) for JSON stability.
- Assertion-level `na` results do not exclude samples from `pass_rate` or `pass@k` denominators. Compatibility fields `n_applicable` and `n_not_applicable` remain available in `aggregates[]`.
- When prompt variants are present, aggregates are computed per (prompt case, model, variant) and stored with `prompt_variant_id`.

---

## Feature: Report output

### Behavior

When report generation is enabled (default):

- `evaluate` writes an HTML report to `<run_dir>/index.html`.

The report summarizes:

- Overall pass rate per model.
- Average failure counts per model.
- Requirement assertion and best-practice assertion rates.
- Axe WCAG failures and axe best-practice failures tracked separately.
- When multiple samples exist, per-prompt-case/per-model aggregates can be displayed.

When prompt variants exist:

- The main tables reflect the **control** results.
- The report includes an additional section that compares each variant against control.
- Each composed prompt case is displayed as its own test entry and surfaces the base test name plus applied prompt dimensions.
- If a sample includes `generation_conversation_path`, the sample details show an agent conversation section with a transcript preview.

### Acceptance criteria

- Report output path is stable: `<run_dir>/index.html`.
- The report renderer derives model display names from (in order):
  1. `meta.models_info` in `results.json`
  2. the provided models config
  3. fall back to the last path segment of the model name
- Assertion-level `na` results remain visible in detailed report sections and assertion analysis, but report pass-rate and pass@k denominators use all samples.

---

## Feature: Node runner contract

### Behavior

The Python orchestrator invokes the Node runner with:

- `node node_runner/runner.js <htmlPath> <testJsPath> <outJsonPath> [screenshotPath]`

The runner:

- Launches Playwright Chromium headless by default.
- Loads the HTML into a real browser page.
- Injects axe-core and runs `axe.run()`.
- Executes `test.js` assertions via an injected `assert(name, fn, opts)` helper.
- Custom form-control assertions derive accessible names and descriptions from the corresponding Chromium accessibility tree nodes for the DOM elements under test.

### Acceptance criteria

- `assert(name, fn, opts)` supports:
  - `opts.type` of `"R"` or `"BP"` (defaults to `"R"`).
  - `fn` returning either:
    - boolean, or
    - `{ pass: boolean, message?: string }`, or
    - `{ status: "pass" | "fail" | "na", message?: string }`.
  - When an assertion fails, the recorded assertion entry includes a human-readable `message`.
  - For assertion helpers that identify specific failing controls or groups, the failure `message` names those problem elements rather than only reporting a count.
- Runner output JSON contains (at minimum):
  - `testFunctionResult` with `status` and `assertions`.
    - `status` is determined by requirement assertion failures only.
  - `axeResult` with WCAG failures split from best-practice failures:
    - `failure_count`, `failures`, `best_practice_count`, `best_practice_failures`.

---

## Compatibility checklist (for contributors)

Before merging changes that touch CLI, run artifacts, schema, caching, or evaluation:

- Keep all existing tests passing under `tests/`.
- If you intentionally change behavior:
  - Update this file.
  - Add/update tests to lock the new behavior.
  - Note migration steps if file formats or CLI flags change.
