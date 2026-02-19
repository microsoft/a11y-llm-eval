# Proposal: Benchmark Custom Instructions vs Control

## Goal

Add an **optional**, additive benchmark capability that compares multiple *system-level custom instruction sets* against the **control** (the existing evaluation with no custom instructions), using the **same test cases**.

This proposal is designed to preserve the existing workflow and artifacts by default.

---

## Requirements (from request)

- The benchmark is **in addition** to the existing eval (control) and uses the **same eval test cases**.
- Several custom instructions can be defined; each is benchmarked **separately** (no combining instruction sets).
- Custom instructions are applied at the **system prompt level**.
- Each custom instruction has **metadata** (name/description/etc.) available in the report.
- The number of samples for instruction benchmarks **may differ** from the control sample count.
- If instruction benchmarks are included in a run, the HTML report includes a section comparing **each instruction set vs control**.

---

## Recommendation

Implement instruction benchmarks as a first-class **prompt variant** dimension (Control + N instruction sets), rather than encoding instruction sets into model names.

Why:

- Keeps model identity stable.
- Supports clean comparisons (variant vs control) without string parsing.
- Avoids confusing downstream consumers of `results.json`.

However, this is a schema + CLI + report change, so it must follow the backwards-compatibility contract in `docs/features-and-acceptance.md`.

---

## User experience and CLI

### Proposed CLI (additive)

Extend `run` with optional flags:

- `--instruction-sets-file <path>`: YAML file defining instruction sets + per-set sample counts.
- `--control-samples <int>`: sample count for control (defaults to existing `--samples` or 1).
- `--instruction-samples <int>`: optional default sample count for instruction sets lacking per-set override.

Alternatively (cleaner): keep `--samples` as *control samples*, and specify per instruction set samples in the YAML.

### Example usage

Control only (current behavior):

- `python -m a11y_llm_tests.cli run --models-file config/models.yaml --out runs --samples 5`

Control + instruction benchmarks:

- `python -m a11y_llm_tests.cli run --models-file config/models.yaml --out runs --samples 5 --instruction-sets-file config/instruction_sets.yaml`

Evaluate + report (current):

- `python -m a11y_llm_tests.cli evaluate runs/<id> --k 1,5,10`

---

## Instruction sets configuration

### Proposed file format: `config/instruction_sets.yaml`

```yaml
instruction_sets:
  - id: concise
    name: Concise
    description: Prefer minimal HTML, avoid extra text.
    system_prompt_append_markdown: config/instructions/concise.md
    samples: 10

  - id: aria_guardrails
    name: ARIA Guardrails
    description: Strong ARIA guidance; avoid invalid ARIA.
    system_prompt_append_markdown: config/instructions/aria_guardrails.md
    samples: 20
```

Notes:

- Each set is applied **alone** (never combined).
- `id` is a stable identifier used in file paths, schema, and report.
- The `system_prompt_append_markdown` content is appended to the base system prompt (same behavior as today’s `defaults.custom_instructions_markdown`, but per set).

---

## Data model / schema changes (results.json)

### New top-level block (additive)

Add `meta.prompt_variants` (or `meta.instruction_sets`) describing the control + instruction sets:

```json
{
  "meta": {
    "prompting": { ... },
    "prompt_variants": [
      {
        "id": "control",
        "name": "Control",
        "description": "Base system prompt; no custom instructions",
        "custom_instructions_path": null,
        "n_samples_requested": 5
      },
      {
        "id": "concise",
        "name": "Concise",
        "description": "Prefer minimal HTML, avoid extra text",
        "custom_instructions_path": "config/instructions/concise.md",
        "n_samples_requested": 10
      }
    ]
  }
}
```

### Per-result record

Add `prompt_variant_id` to each result record:

- `"prompt_variant_id": "control" | "<instruction_set_id>"`

This allows grouping and computing aggregates by (test, model, variant).

### Aggregates

Extend `AggregateRecord` to include `prompt_variant_id`.

- Current: aggregate is for (test_name, model_name).
- Proposed: aggregate is for (test_name, model_name, prompt_variant_id).

Backwards compatibility:

- Keep existing keys in JSON.
- Add fields additively.
- Ensure report still renders older runs without prompt variants.

---

## Run directory layout

We need to preserve the existing layout for control artifacts, while adding a stable location for variants.

### Proposed layout (additive)

- Control (unchanged):
  - `runs/<id>/raw/<test>/<model>__s<idx>.html` (or legacy `<model>.html`)

- Variant outputs (new):
  - `runs/<id>/raw_variants/<variant_id>/<test>/<model>__s<idx>.html`

- Screenshots (new for variants):
  - `runs/<id>/screenshots_variants/<variant_id>/<test>__<model>__s<idx>.png`

Rationale:

- Avoids mixing variant HTML with control HTML.
- Avoids breaking `evaluate`’s current file discovery/parsing logic.
- Makes it easy to delete/regenerate a single variant.

---

## Execution model

### Generation

For each prompt variant (control + each instruction set):

1. Configure the generator with base system prompt + optional instructions.
2. Generate `n_samples` HTML per (test, model).
3. Record generation metadata per record (existing `generation.*` fields).

Important implementation detail:

- Current multiprocessing uses spawn (macOS) and relies on module-level prompt configuration.
- To support multiple variants reliably in parallel, refactor generation to **pass effective prompts explicitly** in each task (or configure within the worker), rather than relying on global mutable module state.

### Evaluation

Evaluate control and variants, producing results tagged with `prompt_variant_id`.

Aggregates are computed per (test, model, variant).

---

## Report changes

### New report section: “Instruction Benchmarks”

If (and only if) prompt variants beyond control exist, include a section that:

- Lists each instruction set (name + description).
- Shows side-by-side summary metrics vs control:
  - Pass rate (WCAG pass rate)
  - Avg total failures
  - Avg axe WCAG failures
  - Avg assertion requirement failures
  - Avg best practice failures
  - pass@k (for requested k values)

### Comparison presentation

For each instruction set, show:

- Absolute metrics for control and variant.
- Delta vs control ($\Delta$):
  - $\Delta$ pass rate (percentage points)
  - $\Delta$ avg failures

Optional (nice-to-have):

- Per-test “wins/losses/ties” count vs control.

---

## Testing plan

Add tests that lock the new behavior without touching external APIs:

- CLI generation with variants:
  - Creates variant directories.
  - Writes `results.json` including `prompt_variant_id` and `meta.prompt_variants`.
  - Allows different sample counts per variant.

- CLI evaluation with variants:
  - Produces aggregates per (test, model, variant).

- Report rendering:
  - Renders baseline section as today.
  - Renders the “Instruction Benchmarks” section only when variants exist.

---

## Rollout and compatibility

- Default behavior remains identical when `--instruction-sets-file` is not used.
- Existing runs without prompt variants must still render in the report.
- Document the finalized behavior in `docs/features-and-acceptance.md` when implemented.

---

## Open questions

- Should instruction benchmarks apply to all models, or allow model filtering per instruction set?
- Should variants have their own `--k` list (or inherit from evaluation `--k`)?
- Should control always be required, or allow “variants only” runs? (Proposal assumes control is always present for comparisons.)
