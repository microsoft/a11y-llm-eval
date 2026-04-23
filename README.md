# A11y LLM Evaluation Harness and Dataset

This is a research project to evaluate how well various LLM models generate accessible HTML content.

## Problem
LLMs currently generate code with accessibility bugs, resulting in blockers for people with disabilities and costly re-work and fixes downstream. 

## Goal
Create a public test suite which can be used to benchmark how well various LLMs generates accessible HTML code. Eventually, it could also be used to help train models to generate more accessible code by default.

## Methdology
- Each test case contains a prompt to generate an HTML page to demonstrate a specific pattern or component.
- This page is rendered in a real browser using Playwright (Chromium). Tests are executed against this rendered page.
- The HTML is evaluated against axe-core, one of the most popular automated accessibility testing engines.
- The HTML is also evaluated against a manually defined set of assertions, customized for the specific test case. This allows for more robust testing than just using axe-core.
- Tests only pass if zero axe-core failures are found AND all *requirement* assertions pass. Best Practice (BP) assertion failures do not fail the test but are tracked separately.

## Features
- Python orchestrator with Inspect AI-backed generation
- Node.js Playwright + axe-core evaluation
- Per-test prompts & injected JS assertions
- HTML report summarizing performance
- Token + cost tracking (tokens in/out/total, per-generation cost, aggregated per model)
- Multi-sample generation with pass@k metrics (probability at least one passing generation in k draws)
- Additive Inspect runtime JSONL logs under each run directory

## Sampling & pass@k Metrics
You can request multiple independent generations ("samples") per (test, model). This enables computation of pass@k metrics similar to code evaluation benchmarks.

### CLI Usage

Step 1: Send prompts to the LLMs and generate HTML
```bash
python -m a11y_llm_tests.cli run \
  --models-file config/models.yaml \
  --out runs \
  --samples 20 \
```

Step 2: Run the eval and generate the report
```bash
python -m a11y_llm_tests.cli evaluate \
  <path to run directory>
  --k 1,5,10
```

Artifacts:
- Each sample's HTML: `runs/<ts>/raw/<test>/<model>__s<idx>.html` (single-sample keeps legacy `<model>.html`)
- Screenshots with analogous naming
- `results.json` now includes per-sample records + an `aggregates` array with pass@k stats.
- Report includes an aggregate pass@k table and grouped per-sample cards.

Tips:
- Increase `temperature` (or other diversity params) to reduce sample correlation.
- Use `--disable-cache` if you want fresh generations even when prompt/model/seed repeat.

### Custom instruction benchmarking (instruction sets)

You can optionally benchmark multiple **custom instruction sets** against the **control** using the same test cases.

- **Control**: the base system prompt with **no custom instructions**.
- **Each instruction set is run separately** (instruction sets are not combined).
- Instruction sets can use a **different sample count** than the control.

Step 0: Start from the default instruction sets file

- Use `config/default_instruction_sets.yaml` as a starting point.
- The default set references `config/instructions/accessible-minimal.md` (a minimal hint that all output must be accessible).

You can also create your own instruction sets YAML file.

```yaml
instruction_sets:
  - id: accessible_minimal
    name: Accessible Minimal
    description: Minimal reminder that all output must be accessible.
    system_prompt_append_markdown: config/instructions/accessible-minimal.md
    # samples: 10

  - id: aria_guardrails
    name: ARIA Guardrails
    description: Strong ARIA guidance; avoid invalid ARIA.
    system_prompt_append_markdown: config/instructions/aria_guardrails.md
    samples: 20

  - id: agentic_accessibility
    name: Agentic Accessibility
    description: Use a sandboxed Inspect ReAct agent to iteratively refine the page.
    system_prompt_append_markdown: config/instructions/accessible-minimal.md
    samples: 5
    agent:
      sandbox:
        - docker
        - config/inspect_agent_sandbox/compose.yaml
      limits:
        message_limit: 50
        token_limit: 120000
        time_limit: 600
        working_limit: 420
```

Instruction sets always use Inspect AI's sandboxed ReAct agent path instead of the direct completion path. The instruction-set YAML format does not support `generation_mode`. If you specify `agent.sandbox`, use the Inspect two-item form `[docker, <compose file>]`. If `agent.sandbox` is omitted, the harness defaults to `config/inspect_agent_sandbox/compose.yaml`. `agent.limits.cost_limit` is optional and should only be set when model pricing is configured for every model in the run.

Step 1: Generate control + instruction set variants

```bash
python -m a11y_llm_tests.cli run \
  --samples 5 \
  --instruction-sets-file default_instruction_sets.yaml
```

Step 2: Evaluate and generate the report

```bash
python -m a11y_llm_tests.cli evaluate \
  <path to run directory> \
  --k 1,5,10
```

Variant artifacts:

- Variant HTML: `runs/<ts>/raw_variants/<variant_id>/<test>/<model>__s<idx>.html`
- Agent conversation sidecar for instruction-set variants: `runs/<ts>/raw_variants/<variant_id>/<test>/<model>__s<idx>.agent.json`
- Variant screenshots: `runs/<ts>/screenshots_variants/<variant_id>/<test>__<model>__s<idx>.png`

Report:

- The main tables reflect the **control** results.
- Each instruction-set sample card shows a transcript preview and links to the saved conversation JSON.
- If variants are present, the report includes an **“Instruction Benchmarks (vs Control)”** section with side-by-side metrics and deltas.


### Skills benchmarking

A **skill** is a self-contained package (a directory containing at minimum a `SKILL.md` plus any support files) that is mounted into the sandboxed agent at runtime. Unlike instruction sets, a skill declares a sequence of user **turns**, and the agent's submission at the end of each turn is evaluated **independently** so the report can compare `control | turn 1 | turn 2 | …` per (test, model).

- Skills always use the sandboxed Inspect ReAct agent path. `generation_mode` is not supported.
- The skill directory is mounted at `/workspace/.skills/<skill_id>/` inside the sandbox.
- Exactly one turn prompt must contain `{{test_case_prompt}}` (typically turn 1). Other supported tokens: `{{skill_id}}`, `{{skill_path}}`, `{{previous_submission}}`.
- Skills and instruction sets share an id namespace and can be enabled together in the same run.
- Per-turn caching: changing turn 2's prompt invalidates turn 2's cache but not turn 1's.

Step 0: Start from the default skills file

- Use `config/default_skills.yaml` as a starting point. It defines a single `a11y-wizard` skill that first generates a page (turn 1) and then is asked to review and remediate its own HTML (turn 2), using `config/skills/a11y-wizard/SKILL.md` as guidance.

Example `skills.yaml`:

```yaml
skills:
  - id: a11y-wizard
    name: Accessibility Wizard
    description: Generate, then self-review using SKILL.md guidance.
    skill_dir: skills/a11y-wizard
    # samples: 10                     # optional; defaults to --samples
    agent:                            # optional; same shape as instruction sets
      sandbox: [docker, config/inspect_agent_sandbox/compose.yaml]
      limits:
        message_limit: 50
        token_limit: 120000
        time_limit: 600
    turns:
      - id: generate
        name: Generate
        prompt: |
          {{test_case_prompt}}
      - id: review
        name: Review & remediate
        prompt: |
          Review the HTML you just produced against the accessibility checklist
          in {{skill_path}}/SKILL.md. Fix any issues you find and output the
          complete, updated HTML document.
```

Step 1: Generate control + skill turns

```bash
python -m a11y_llm_tests.cli run \
  --samples 5 \
  --skills-file config/default_skills.yaml
```

Step 2: Evaluate and generate the report

```bash
python -m a11y_llm_tests.cli evaluate \
  <path to run directory> \
  --k 1,5,10
```

Skill artifacts:

- Per-turn HTML: `runs/<ts>/raw_skills/<skill_id>/<test>/<model>__s<idx>__t<turn_index>.html`
- One stitched conversation sidecar per sample: `runs/<ts>/raw_skills/<skill_id>/<test>/<model>__s<idx>.agent.json`
- Per-turn screenshots: `runs/<ts>/screenshots_skills/<skill_id>/<test>__<model>__s<idx>__t<turn_index>.png`
- `results.json` emits one record per (test, model, sample, turn) with `prompt_variant_kind = "skill"`, `turn_id`, `turn_index`, and `turn_count_total`, plus one aggregate per (test, model, skill, turn).

Report:

- A new **Skills** section renders one table per configured skill with dynamic columns: `Control | turn 1 | … | turn N | Δ last vs control | Δ last vs turn 1`.
- The skill details panel previews each turn's prompt template and the mounted `SKILL.md`.

### Combined run (instruction sets + skills)

Both flags can be supplied at once; each variant is benchmarked separately against the same control, and each renders its own section in the report.

```bash
python -m a11y_llm_tests.cli run \
  --samples 5 \
  --instruction-sets-file config/default_instruction_sets.yaml \
  --skills-file config/default_skills.yaml

python -m a11y_llm_tests.cli evaluate \
  <path to run directory> \
  --k 1,5
```

This produces, in a single run directory:

- `raw/…` — control samples
- `raw_variants/<instruction_set_id>/…` — instruction-set samples (one HTML + `.agent.json` per sample)
- `raw_skills/<skill_id>/…` — skill samples (one HTML per turn + one stitched `.agent.json` per sample)
- A report with three comparison sections: Control summary, **Instruction Benchmarks (vs Control)**, and **Skills (vs Control)**.


## Quick Start
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Node deps
bash scripts/install_node_deps.sh

# Copy env and set keys
cp .env.example .env
export OPENAI_API_KEY=... # etc. or put in .env and use dotenv

# Copy model config and set API keys
cp config/models.yaml.example config/models.yaml

# Optional: for Azure provider auth via DefaultAzureCredential
# pip install azure-identity

# Run all tests against configured models
python -m a11y_llm_tests.cli run --models-file config/models.yaml --out runs
```

## Adding a Test Case
Create a new folder under `test_cases/`:
```
test_cases/
  form-labels/
    prompt.yaml
    test.js
    example-fail/
    example-pass/
```

`prompt.yaml` defines the base prompt plus any prompt dimensions for the test case. A minimal example is:

```yaml
base_prompt: |
  Build a simple form.
common_requirements:
  - Include a submit button.
dimensions:
  validation-message:
    label: Validation Message
    values:
      present:
        label: Error Message Present
        prompt_fragment: Include an inline validation message.
      absent:
        label: No Error Message
        prompt_fragment: Do not show an inline validation message on initial render.
```

Global prompt dimensions such as framework and style live in `config/prompt_dimensions.yaml` and are combined with each test case automatically.

`test.js` must export:

```js
module.exports.run = async ({ page, assert }) => {
  await assert("Has an h1", async () => {
    const count = await page.$$eval('h1', els => els.length);
    return count >= 1; // truthy => pass, falsy => fail
  });
  await assert("Sequential heading levels", async () => {
    // Return object form to include custom message
    const ok = await page.$$eval('h1 + h2', els => els.length) > 0;
    return { pass: ok, message: ok ? undefined : 'h2 does not follow h1' };
  }, { type: 'BP' });
  return {}; // assertions collected automatically
};
```

The runner injects an `assert(name, fn, opts?)` helper:

| Parameter | Description |
|-----------|-------------|
| `name` | Human-readable assertion label |
| `fn` | Async/Sync function returning boolean OR `{ pass, message? }` |
| `opts.type` | `'R'` (Requirement, default) or `'BP'` (Best Practice) |

Return shape from `run` can be empty.

### Assertion Types

Each assertion may now include a `type` field:

| Type | Meaning | Affects Test Pass/Fail | Aggregated Separately |
|------|---------|------------------------|-----------------------|
| `R`  | Requirement (default) | Yes (any failing R => test fails) | Requirement Pass Rate |
| `BP` | Best Practice | No (ignored for pass/fail) | Best Practice Pass Rate |

If `type` is omitted it defaults to `R` for backward compatibility. The HTML report shows both Requirement Pass Rate (percentage of tests whose requirement assertions passed) and Best Practice Pass Rate (percentage of tests containing BP assertions where all BP assertions passed).

Example assertion objects returned from `run`:

```js
return {
  assertions: [
    { name: 'has main landmark', status: 'pass', type: 'R' },
    { name: 'images have alt text', status: 'fail', type: 'BP', message: '1 of 5 images missing alt' }
  ]
};
```

## Report
Generated at `runs/<timestamp>/report.html` with:
- Summary stats per model
- Detailed per model/test breakdown
- Axe violations
- Assertions & statuses
- Pass@k aggregate table and per-sample cards when multiple samples are collected

## Contributing

This project welcomes contributions and suggestions.  Most contributions require you to agree to a
Contributor License Agreement (CLA) declaring that you have the right to, and actually do, grant us
the rights to use your contribution. For details, visit [Contributor License Agreements](https://cla.opensource.microsoft.com).

When you submit a pull request, a CLA bot will automatically determine whether you need to provide
a CLA and decorate the PR appropriately (e.g., status check, comment). Simply follow the instructions
provided by the bot. You will only need to do this once across all repos using our CLA.

This project has adopted the [Microsoft Open Source Code of Conduct](https://opensource.microsoft.com/codeofconduct/).
For more information see the [Code of Conduct FAQ](https://opensource.microsoft.com/codeofconduct/faq/) or
contact [opencode@microsoft.com](mailto:opencode@microsoft.com) with any additional questions or comments.

## Trademarks

This project may contain trademarks or logos for projects, products, or services. Authorized use of Microsoft
trademarks or logos is subject to and must follow
[Microsoft's Trademark & Brand Guidelines](https://www.microsoft.com/legal/intellectualproperty/trademarks/usage/general).
Use of Microsoft trademarks or logos in modified versions of this project must not cause confusion or imply Microsoft sponsorship.
Any use of third-party trademarks or logos are subject to those third-party's policies.
