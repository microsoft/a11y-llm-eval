# Features & Acceptance Criteria (Backwards-Compatibility Contract)

This document describes the **current, user-visible behavior** of the A11y LLM Evaluation Harness.

> **Migration: GitHub Copilot SDK (breaking).** The harness has migrated off
> [Inspect AI](https://inspect.ai-safety-institute.org.uk/) and onto the
> [`github-copilot-sdk`](https://pypi.org/project/github-copilot-sdk/). All
> generations are now Copilot agent sessions; there is no direct
> chat-completion path or batch API. Concrete changes:
>
> - **Engine.** `meta.runtime.engine` is now `"copilot_sdk"` (was
>   `"inspect_ai"`). Logs land under `<run_dir>/copilot_logs/` (was
>   `inspect_logs/`).
> - **Generation mode.** Records carry `generation.generation_mode == "copilot_agent"`
>   (was `"direct"` for control or `"inspect_react_agent"` for variants).
> - **CLI.** `run` exposes `--concurrency / -c` (number of in-flight
>   sessions) instead of `--processes / -p`. `evaluate --processes` is
>   unchanged.
> - **Removed flags / config.**
>   - `providers.<provider>.batch.*` — batch generation no longer exists.
>   - `providers.<provider>.auth.mode = default_azure_credential` —
>     unsupported; use BYOK with an explicit `api_key` / `api_key_env`.
>   - Per-request `temperature` / `seed` are silently dropped for
>     first-party Copilot routes; BYOK provider configs may still honor
>     them.
> - **Schema.** `ResultRecord.generation_eval_path` keeps its name but now
>   points at a `*.session.jsonl` log (the Copilot agent session
>   transcript). The internal generator key `agent_session_log_path` is
>   mapped to this field; it does not appear in the serialized schema.
> - **Cache.** Filenames now use `_copilot_agent.html` (was `_agent.html`);
>   pre-migration cache entries will not hit and should be removed.
> - **Skills.** Skill directories are exposed via the SDK's
>   `skill_directories=[…]` parameter; the harness no longer mounts them
>   into a Docker sandbox or injects a `system_prompt_preamble`.
> - **Sandbox.** The Inspect Docker sandbox is gone. The Copilot CLI now
>   runs **inside a sandbox container we own** (`config/copilot_sandbox/`).
>   The harness brings per-workspace sandbox containers up automatically at
>   the start of `run` and tears them down automatically when the run ends.
>   Docker is therefore a hard dependency. First-party Copilot authentication
>   uses a named Docker volume (`copilot-auth`) so credentials stay
>   inside the container and are not exposed to the host. On first run
>   the harness verifies CLI connectivity and — if needed — runs
>   `copilot login` interactively in the user's terminal; the resulting
>   token persists across container rebuilds. `GH_TOKEN` / `GITHUB_TOKEN`
>   are forwarded per-`docker exec` as a CI/headless fallback.
>   Override the workspace mount with the `COPILOT_WORKSPACE` environment
>   variable. `meta.runtime.engine` remains `"copilot_sdk"`;
>   per-record sandbox labels now read
>   `docker:config/copilot_sandbox/compose.yaml`.

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

Copilot session logs are written under `<run_dir>/copilot_logs/` as JSONL files (one event per line, one file per session). These logs are not part of the compatibility-critical artifact contract unless explicitly documented otherwise.

### Per-sample agent sandbox working directory

Each generation runs the Copilot agent with an isolated working directory under `<run_dir>/sandbox/`:

- Control: `<run_dir>/sandbox/control/<prompt_case_id>/<model>__s<sample_index>/`
- Instruction-set variants: `<run_dir>/sandbox/variants/<variant_id>/<prompt_case_id>/<model>__s<sample_index>/`
- Skill variants: `<run_dir>/sandbox/skills/<skill_id>/<prompt_case_id>/<model>__s<sample_index>/`

The harness instructs the agent (via `DEFAULT_OUTPUT_FORMAT_INSTRUCTIONS`, appended to the user prompt) to write its final HTML to `index.html` in that directory, and reads it back after `session.idle`. The agent may also create sibling files (CSS, JavaScript, images) referenced from `index.html` via relative paths. The directory is also passed to the SDK's `working_directory`, so any tool the agent invokes (e.g. `write`, `bash`, test runners) operates inside the per-sample directory and cannot collide with other concurrent samples sharing the workspace mount.

If the agent does not produce an `index.html` (e.g. because it answered inline), the harness falls back to extracting the final assistant message. The `transcript` carries `output_source: "disk" | "message"` and the absolute working directory path so reports can show provenance.

These sandbox directories are intentionally part of the run output: they contain the artifacts a real dev would have on disk (auxiliary files, scratch installs, etc.). By default `<run_dir>/sandbox/` is **deleted at the end of generation** because the artifacts the harness needs (`index.html` plus any sibling files) have already been copied into `<run_dir>/raw[_variants|_skills]/...`. Pass `--keep-sandbox` to `run` to preserve the tree for debugging tool use. The sandbox tree is not part of the compatibility-critical artifact contract.

### Multi-file output

The default output-format instructions encourage the agent to split CSS and JavaScript into separate files when the output is large. Each sample's output is stored in its own subdirectory (e.g. `<model>__s<sample_index>/index.html`) to prevent filename collisions between samples. At generation time, all non-hidden files the agent wrote in the sandbox working directory (except `index.html` itself, which the harness writes from the canonical HTML string) are copied into that per-sample subdirectory.

At evaluation time, the Node runner serves the per-sample directory over a localhost HTTP server and loads `index.html` via `http://127.0.0.1:<port>/index.html` (not `page.setContent()`). This allows `<link>`, `<script src>`, and other relative references to resolve the way they would in a normal hosted deployment while still evaluating the exact generated artifact directory.

### Security model

The harness runs the Copilot CLI inside a Docker container (`config/copilot_sandbox/`). The agent can invoke tools (file writes, shell commands) within the container. A **scoped permission handler** restricts file-write tools to the per-sample sandbox working directory; writes targeting paths outside that directory are denied. Non-write tools (shell, read, browser, etc.) are approved.

**Trust boundary:** The workspace is bind-mounted read-write into the container at `/workspace`. This means:

- The agent can *read* any file in the workspace but can only *write* within its per-sample sandbox directory (enforced by the permission handler at the SDK layer).
- The agent cannot access the host filesystem outside the workspace mount.

**Authentication:** Copilot CLI authentication uses a named Docker volume (`copilot-auth`) so credentials stay inside the container and are not exposed to the host Python process. On first run (or after deleting the container), the harness runs a pre-flight check: it brings up the sandbox, verifies the CLI can reach the Copilot API, and — if not — runs `copilot login` interactively in the user's terminal. The resulting token persists in the Docker volume across container teardowns and rebuilds. `GH_TOKEN` / `GITHUB_TOKEN` environment variables are forwarded per-`docker exec` as a CI/headless fallback. BYOK provider keys (e.g. `ANTHROPIC_API_KEY`) are forwarded the same way.

**Concurrent runs:** Each workspace uses a unique container name (derived from the workspace path hash), so two harness instances on the same host do not collide.

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
- `python -m a11y_llm_tests.cli serve <run_dir> ...`:
  - Requires an existing run directory.
  - Serves the run directory over localhost HTTP until interrupted.
  - Prints the base URL and, when `<run_dir>/index.html` exists, the report URL.
  - `--port 0` chooses an ephemeral port automatically.
  - `--open` opens the report URL in the default browser when `index.html` exists.

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

Generation uses the GitHub Copilot SDK agent runtime:

- The composed prompt case text built from `prompt.yaml` plus the configured global prompt dimensions, **suffixed** with the **base output-format instructions** (the "save your answer to `index.html`" task instructions). The harness does not send a custom `system_message` to the agent SDK; the SDK's default agent system prompt is left intact.
- **Custom instructions** (from `defaults.custom_instructions_markdown` or an instruction-set variant) are delivered the way real Copilot users supply them: the harness writes the markdown to `<sandbox_workdir>/.github/copilot-instructions.md` before the SDK session starts, so the Copilot agent auto-discovers them from its `working_directory`. They are **not** appended to the user prompt. The text is still mixed into the local cache key so changes invalidate cached generations correctly.

All generations are Copilot agent sessions. Concurrency is controlled by `--concurrency` (default 4). Each session has a wall-clock timeout (default 600 s / 10 min); if the agent does not complete within the limit the session is terminated and the result is recorded as a limit error. The timeout can be overridden globally with `--agent-timeout <seconds>` or per-variant via `agent.limits.timeout_s` in the instruction-set / skills YAML (the YAML value takes precedence over the CLI flag).

The SDK's per-turn output-token limit is overridden to **64 000 tokens** by default (the Copilot CLI default is 16 000, which can cause tool-call truncation on large HTML pages). This can be configured per-variant via `agent.limits.max_output_tokens` in the YAML.

The effective output-format instructions are:

- `DEFAULT_OUTPUT_FORMAT_INSTRUCTIONS`, unless overridden.
- Optionally combined with custom instructions text for **provenance only** (recorded in `results.json` under `effective_output_format_instructions`). At generation time only the base output-format instructions are appended to the user prompt; custom instructions are delivered as `.github/copilot-instructions.md` (see above).

`config/models.yaml` supports defaults:

- `defaults.output_format_instructions` (string) — the legacy alias `defaults.system_prompt` is still accepted.
- `defaults.custom_instructions_markdown` (path to a markdown file)
- `defaults.temperature` (float)

`config/models.yaml` may also define provider-level configuration under `providers.<provider>`.

- `providers.<provider>.auth.mode` may be omitted or set to `env` to preserve the runtime's existing environment-based behavior.
- `auth.mode = default_azure_credential` is no longer supported after the migration to the Copilot SDK. Configure a BYOK provider with an explicit `api_key` (or `api_key_env`), or use Copilot's first-party routing.
- `providers.<provider>.api_key_cmd` (string) — a shell command whose stdout is used as the `api_key`. The result is cached for 30 minutes and automatically refreshed, making it suitable for short-lived tokens (e.g. `gcloud auth print-access-token` for Vertex AI). Takes effect only when neither `api_key` nor `api_key_env` resolves a value.

If `run --temperature` is not provided, the effective temperature defaults to `defaults.temperature` if present.

If neither `run --temperature` nor `defaults.temperature` is provided, the harness omits `temperature` from the generation request so the provider/model default temperature is used.

Note: some Codex-style deployments (e.g., certain `*-codex` models) do not accept sampling parameters like `temperature`. For these models, the harness omits `temperature` from the generation request to avoid provider errors.

Prompt caching for Anthropic / Claude models is handled by the Copilot SDK and the provider. The harness's local `.cache/generations/` cache is independent of any provider-side prompt caching.

### Acceptance criteria

- Generated output is a **single standalone HTML document**, written by the agent to `index.html` inside its per-sample sandbox working directory and read back by the harness. If the agent does not write that file, the harness falls back to extracting the final assistant message.
- The generator normalizes model output by:
  - Stripping Markdown fences if present.
  - Extracting the first `<html> ... </html>` block if present.
- After a successful fresh generation, the harness runs a lightweight browser smoke check against the artifact under the same localhost HTTP serving conditions used by evaluation. The resulting metadata is stored on `generation.browser_smoke` with at least `rendered`, `reason`, `page_errors`, `request_failures`, and `dom_state`. Artifacts whose smoke check reports `rendered: false` are not admitted into the generation cache.
- If the agent hits a limit (timeout, token, message) during generation, the harness logs the error prominently and continues with remaining tasks. A summary of all limit errors is printed at the end of generation.
- If the agent produces empty or invalid HTML (no `<html>…</html>` block, fewer than 50 characters, or missing `<body>`) without a pre-existing limit error, the harness records a synthetic `agent_limit_error` of `"empty_generation"`. This flows through the same limit-error reporting pipeline so the post-run summary is explicit. The empty artifact is still written to disk and evaluates to `FAIL`.
- Prompt hashing:
  - `compute_prompt_hash(user_prompt)` depends on the configured output-format instructions, custom instructions, and the user prompt.
  - Changing output-format instructions or custom instructions changes the hash.

---

## Feature: Generation caching

### Behavior

Generated HTML is cached under `.cache/generations/`.

Agent-backed generations use a separate cache identity from direct generations. When an agent generation is cached, the harness also caches the agent conversation payload needed to recreate the per-run `.agent.json` sidecar. Cached agent hits do not create a fresh Copilot session log for the new run.

Cache identity includes:

- Model name
- Prompt hash
- Seed (if provided)
- Sample iteration index
- Generation mode (agent)

On cache hits, the generator returns `cached: True` and can optionally load token/cost metadata from a `.meta.json` file.

### Acceptance criteria

- Cache files are created at:
  - `.cache/generations/<model>_<promptHash>_s<seed>_i<iteration>_copilot_agent.html` (when seed is provided)
  - `.cache/generations/<model>_<promptHash>_i<iteration>_copilot_agent.html` (when seed is not provided)
- The cache directory may also contain sidecar integrity files (e.g., `.sha256`) alongside cached HTML.
- Agent-mode cache entries may additionally include a cached transcript sidecar used to recreate the run-local `.agent.json` artifact on cache hits.
- Agent-mode cache metadata may include `browser_smoke`. If an older cache entry is missing this field, the harness performs a one-time browser smoke check during cache validation and writes the result back to the cache metadata. Cache entries whose smoke metadata reports `rendered: false` are treated as cache misses and regenerated.
- If a cached HTML file is incomplete/corrupted, it is treated as a cache miss and a fresh generation is performed.
- The `--disable-cache` flag forces fresh generation even if a cache entry exists.

---

## Feature: Run directory artifacts and naming

### Behavior

During `run`, each sample's generated HTML is written as `index.html` inside a per-sample subdirectory under:

- `<run_dir>/raw/<prompt_case_id>/`

Naming depends on `--samples`:

- Multi-sample (`samples > 1`): `<model>__s<sample_index>/index.html`
- Legacy single-sample (`samples == 1`): `<model>/index.html`

The subdirectory may also contain sibling files (CSS, JS, images) that the agent created alongside `index.html`. These are copied from the per-sample sandbox working directory.

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
- Instruction sets always use the Copilot agent path.
- Instruction-set YAML does not support `generation_mode`; configs that specify it are invalid.
- Instruction sets may declare `agent.limits` overrides (e.g., `timeout_s`, `excluded_tools`). Only `timeout_s` (default 600) and `excluded_tools` (list of tool names) are currently consumed; other keys are stored as metadata.
- Concurrent agent generations default to at most 4 in parallel when `--concurrency` is not specified. Pass `--concurrency` explicitly to override.

Artifacts for variants are written under separate directories:

- Variant HTML: `<run_dir>/raw_variants/<variant_id>/<prompt_case_id>/<model>__s<sample_index>/index.html`
- Agent conversation sidecar for agent-mode variants: `<run_dir>/raw_variants/<variant_id>/<prompt_case_id>/<model>__s<sample_index>.agent.json`
- Variant screenshots: `<run_dir>/screenshots_variants/<variant_id>/<prompt_case_id>__<model>__s<sample_index>.png`

Schema additions:

- Each `results[]` record includes `prompt_variant_id` ("control" or the instruction set id).
- Each `results[]` record includes `base_test_name`, `prompt_case_id`, and `prompt_dimensions` for the composed prompt case.
- Each `results[]` record may include `generation_conversation_path` for any agentic sample (control, instruction-set, or skill). The sidecar is written to `<run_dir>/raw/<prompt_case_id>/<model>[__s<idx>].agent.json` for control samples and `<run_dir>/raw_variants/<variant_id>/<prompt_case_id>/<model>__s<idx>.agent.json` for instruction-set samples.
- Each `results[]` record may include `generation_eval_path` for any agentic sample when a Copilot session log file is produced or restored from cache.
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
  - Instruction-set variants use the default generation cache across runs; on cache hits they still write the conversation JSON sidecar. When a cached session log exists, it is restored into the run's `copilot_logs/` directory and `generation_eval_path` is populated so the report can link to it. If no cached session log is available, `generation_eval_path` is left unset.
  - `results.json` includes `meta.prompt_variants` with at least:
    - a `control` entry
    - one entry per configured instruction set

- When `--instruction-sets-file` is not provided:
  - No `raw_variants/` or `screenshots_variants/` outputs are required.
  - No instruction sets section is rendered in the HTML report (and its report-nav link is omitted).
  - Existing single-run behavior remains unchanged.

---

## Feature: Skills benchmark (multi-turn)

### Behavior

The harness can benchmark **skills** — self-contained packages of files (at minimum a `SKILL.md`) that are mounted into the agent sandbox at runtime. Unlike instruction sets, a skill declares a sequence of user **turns**, and the agent's submission at the end of each turn is evaluated **independently** so the report can compare control vs turn 1 vs turn 2 vs … per (test, model).

This is enabled via `run --skills-file <path>` and is independent of `--instruction-sets-file` (both may be supplied in the same run).

- Each skill declares `id`, `name`, optional `description`, a `skill_dir` (directory containing `SKILL.md`, relative to the skills YAML file or absolute), `agent` settings (same shape as instruction-set `agent`), and a required **non-empty** `turns` list.
- Each turn declares `id`, `name` (optional), and a `prompt` template.
- Exactly **one** turn prompt in a skill must contain the token `{{test_case_prompt}}`. Other supported tokens: `{{skill_id}}`, `{{skill_path}}`, `{{previous_submission}}`.
- Turn ids must be unique within the skill; skill ids must be unique across skills and must not collide with instruction-set ids or the reserved id `control`.
- Skills always use the Copilot agent path; `generation_mode` is not supported.
- The skill directory is exposed to the Copilot agent via the SDK's `skill_directories` parameter. The harness translates host-side paths to container paths automatically.
- Each turn is a separate user message; earlier turns' assistant replies are preserved as seed messages for subsequent turns.
- Per-turn generation caching: the cache key for turn k includes the model, seed, iteration, skill id, hash of all skill files, turn index, and a cumulative hash of all rendered turn prompts up to and including turn k. Changing turn 2's prompt invalidates turn 2's cache but not turn 1's.
- Partial failure: if a turn errors or hits a model/agent limit, that turn's record is written with an empty HTML artifact and its `generation.agent_limit_error` populated with the failure reason. Subsequent turns for that sample are short-circuited with the same empty HTML and `generation.agent_limit_error` set (the sidecar conversation entry is marked `skipped: true` with a `skip_reason`). Empty HTML fails the node-runner checks, so those turns evaluate to `result = "FAIL"`. Earlier turns in the same sample remain evaluated normally.

Artifacts for skills are written under separate directories:

- Skill HTML: `<run_dir>/raw_skills/<skill_id>/<prompt_case_id>/<model>__s<sample_index>__t<turn_index>/index.html`
- Skill agent conversation sidecar (one per sample, stitched across turns): `<run_dir>/raw_skills/<skill_id>/<prompt_case_id>/<model>__s<sample_index>.agent.json`
- Skill screenshots: `<run_dir>/screenshots_skills/<skill_id>/<prompt_case_id>__<model>__s<sample_index>__t<turn_index>.png`

Schema additions:

- Each `results[]` record for a skill turn includes `prompt_variant_kind = "skill"`, `turn_id`, `turn_index` (0-based), and `turn_count_total`.
- Each `aggregates[]` record for a skill turn includes `prompt_variant_kind`, `turn_id`, and `turn_index`. Aggregates are grouped by `(test_name, base_test_name, prompt_case_id, model, prompt_variant_id, prompt_variant_kind, turn_id)` so every turn has its own pass@k row.
- `meta.prompt_variants` entries for skills carry `kind: "skill"`, `skill_path`, and `turns` (the resolved list of `{id, name, prompt}` objects).

### Acceptance criteria

- When `--skills-file` is provided:
  - Control samples are still written to `<run_dir>/raw/` using existing naming rules.
  - For every configured skill, every (test, model, sample) produces one subdirectory per turn named `…__s<idx>__t<turn_index>/index.html`, plus one stitched `.agent.json` sidecar per sample.
  - `results.json` includes one result record per (test, model, sample, turn) with `prompt_variant_kind = "skill"`.
  - `results.json` includes one aggregate per (test, model, skill, turn).
  - `meta.prompt_variants` includes an entry per skill with `kind: "skill"` and a non-empty `turns` list.
  - The generated HTML report renders a **Skills** section with one table per skill and dynamic columns for control + each turn, plus the SKILL.md preview under skill details.

- When `--skills-file` is not provided:
  - No `raw_skills/` or `screenshots_skills/` outputs are required.
  - No skill section is rendered in the HTML report (and its report-nav link is omitted).

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
- The methodology section includes an approximate minimum detectable WCAG pass-rate gap for a two-model comparison, derived from the run's prompt-case count and `samples_per_case` metadata. This heuristic assumes independent samples and may be optimistic when repeated samples for the same prompt case are correlated.

When prompt variants exist:

- The main tables reflect the **control** results.
- The report includes an additional section that compares each variant against control.
- Each composed prompt case is displayed as its own test entry and surfaces the base test name plus applied prompt dimensions.
- If a sample includes `generation_conversation_path`, the sample details show an agent conversation section with a transcript preview.
- For agent-mode (Copilot SDK) samples, the transcript preview surfaces structured tool activity from the captured `*.agent.json` events:
  - `tool.execution.start` events render as `Agent action` entries with the tool name, the assistant's `intention_summary` (when present), and a compact list of arguments. Bulky payloads (`file_text`, `new_file_contents`, `diff`, `patch`, `content`, etc.) are not dumped — their presence is noted as `(file_text omitted)`.
  - `tool.execution.complete` events render as `<tool_name> result` entries with the tool's `content` (truncated to ~400 chars). Errors render as `<tool_name> error`.
  - `permission.requested` events render as `Permission requested` entries with the request kind, intention, and target file/command.
  - `assistant.message.tool_requests` (stringified `AssistantMessageToolRequest(...)` reprs) are intentionally skipped to avoid duplication; the structured `tool.execution.start` events are the source of truth.
  - The following SDK event prefixes are skipped from the preview to reduce noise: `session.`, `pending.`, `assistant.turn.`, `assistant.usage`, `assistant.reasoning`, `hook.`, `permission.completed`, `tool.execution.partial`.

### Acceptance criteria

- Report output path is stable: `<run_dir>/index.html`.
- The report renderer derives model display names from (in order):
  1. `meta.models_info` in `results.json`
  2. the provided models config
  3. fall back to the last path segment of the model name
- When `meta.sampling.samples_per_case` is present and greater than zero, the methodology section reports the corresponding prompt-case count, samples per model, and approximate minimum detectable WCAG pass-rate gap for a two-model comparison.
- Assertion-level `na` results remain visible in detailed report sections and assertion analysis, but report pass-rate and pass@k denominators use all samples.

---

## Feature: Node runner contract

### Behavior

The Python orchestrator invokes the Node runner with:

- `node node_runner/runner.js <htmlPathOrUrl> <testJsPath> <outJsonPath> [screenshotPath]`

The runner:

- Launches Playwright Chromium headless by default.
- Navigates to a localhost HTTP URL for the artifact directory, so relative CSS/JS references resolve the same way they would under normal static hosting.
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
