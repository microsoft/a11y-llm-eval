# A11y LLM Evaluation Harness and Dataset

This is a research project to evaluate how well various LLM models generate accessible HTML content.

## Problem
LLMs currently generate code with accessibility bugs, resulting in blockers for people with disabilities and costly re-work and fixes downstream. 

## Goal
Create a public test suite which can be used to benchmark how well various LLMs generates accessible HTML code. Eventually, it could also be used to help train models to generate more accessible code by default.

## Methodology
- Each test case contains a prompt to generate an HTML page to demonstrate a specific pattern or component.
- All generations (control, instruction-set variants, and skills) are agentic sessions powered by the [GitHub Copilot SDK](https://pypi.org/project/github-copilot-sdk/) running inside a Docker sandbox. The agent can call built-in tools (e.g. file writes, shell commands) and iteratively refine its output.
- **Control** uses the test prompt with no custom accessibility instructions, measuring baseline behavior. **Instruction-set variants** add custom instructions (delivered via `.github/copilot-instructions.md`). **Skills** use multi-turn conversations with explicit turn prompts and a mounted skill directory.
- The resulting HTML is rendered in a real browser using Playwright (Chromium). Tests are executed against this rendered page.
- The HTML is evaluated against axe-core, one of the most popular automated accessibility testing engines.
- The HTML is also evaluated against a manually defined set of assertions, customized for the specific test case. This allows for more robust testing than just using axe-core.
- Tests only pass if zero axe-core WCAG failures are found AND all *requirement* assertions pass. Best Practice (BP) assertion failures do not fail the test but are tracked separately.

## Features
- Python orchestrator built on the [GitHub Copilot SDK](https://pypi.org/project/github-copilot-sdk/)
- Every generation is an agentic Copilot session running inside a Docker sandbox we own (`config/copilot_sandbox/`)
- Node.js Playwright + axe-core evaluation
- Per-test prompts & injected JS assertions
- HTML report summarizing performance
- Token + cost tracking (tokens in/out/total, per-generation cost, aggregated per model)
- Multi-sample generation with pass@k metrics (probability at least one passing generation in k draws)
- Per-run Copilot session JSONL logs under `<run_dir>/copilot_logs/`

## Sandbox & authentication

The harness drives the official `@github/copilot` CLI inside a long-lived
Docker container (built from `config/copilot_sandbox/Dockerfile`). The
first `run` builds the image and brings the container up; subsequent runs
reuse it.

- **Docker is a hard dependency.** Install Docker Desktop (or Docker
  Engine + Compose v2) before running.
- **Authentication uses your existing dev login.** The harness
  uses a named Docker volume (`copilot-auth`) so credentials stay inside
  the container and are not exposed to the host. On first run the harness
  verifies CLI connectivity and — if needed — runs `copilot login`
  interactively in your terminal; the resulting token persists across
  container rebuilds. `GH_TOKEN` / `GITHUB_TOKEN` environment variables
  are forwarded per-`docker exec` as a CI/headless fallback.
- **BYOK keys** flow through environment variables (`ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`, `AZURE_API_KEY`, `AZURE_API_BASE`,
  `AZURE_API_VERSION`) and are forwarded into the container per session.
- Override the workspace mount with `COPILOT_WORKSPACE` (host path mounted
  as `/workspace`, which must contain any skill directories you reference).
- Stop the container with
  `docker compose -f config/copilot_sandbox/compose.yaml down`.

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
    instructions_markdown: config/instructions/accessible-minimal.md
    # samples: 10

  - id: aria_guardrails
    name: ARIA Guardrails
    description: Strong ARIA guidance; avoid invalid ARIA.
    instructions_markdown: config/instructions/aria_guardrails.md
    samples: 20

  - id: agentic_accessibility
    name: Agentic Accessibility
    description: Extra guidance for the Copilot agent.
    instructions_markdown: config/instructions/accessible-minimal.md
    samples: 5
    agent:
      limits:
        message_limit: 50
        token_limit: 120000
        time_limit: 600
        working_limit: 420
```

All generations now use the Copilot SDK's agent path inside the Docker
sandbox; the instruction-set YAML format does not support
`generation_mode`, and `agent.sandbox` is ignored (the sandbox is fixed
to `config/copilot_sandbox/compose.yaml`). `agent.limits.cost_limit` is
optional and should only be set when model pricing is configured for
every model in the run.

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

A **skill** is a self-contained package (a directory containing at minimum a `SKILL.md` plus any support files) exposed to the Copilot agent via the SDK's `skill_directories` parameter. Unlike instruction sets, a skill declares a sequence of user **turns**, and the agent's submission at the end of each turn is evaluated **independently** so the report can compare `control | turn 1 | turn 2 | …` per (test, model).

- Skills always use the Copilot agent path. `generation_mode` is not supported.
- The skill directory must live inside your workspace; the harness translates the host path to the container's `/workspace/<rel>` automatically.
- Exactly one turn prompt must contain `{{test_case_prompt}}` (typically turn 1). Other supported tokens: `{{skill_id}}`, `{{skill_path}}`, `{{previous_submission}}`.
- Skills and instruction sets share an id namespace and can be enabled together in the same run.
- Per-turn caching: changing turn 2's prompt invalidates turn 2's cache but not turn 1's.

Step 0: Start from the default skills file

- Use `config/default_skills.yaml` as a starting point. It defines a single `building-accessible-ui` skill that first generates a page (turn 1) and then is asked to review and remediate its own HTML (turn 2), using `config/skills/building-accessible-ui/SKILL.md` as guidance.

Example `skills.yaml`:

```yaml
skills:
  - id: building-accessible-ui
    name: Building Accessible UI
    description: Generate, then self-review using SKILL.md guidance.
    skill_dir: skills/building-accessible-ui
    # samples: 10                     # optional; defaults to --samples
    agent:                            # optional limits passed to the Copilot session
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

### Prerequisites

- **Python 3.11+** and **Node.js 18+**
- **Docker** — the generation step runs a Copilot sandbox container.
  Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (macOS/Windows) or Docker Engine (Linux) and make sure `docker` is on your PATH.
- **GitHub CLI** — used to authenticate the Copilot sandbox.
  Install with `brew install gh` (macOS), `winget install GitHub.cli` (Windows), or see [cli.github.com](https://cli.github.com). Then run:
  ```
  gh auth login
  ```
  Alternatively, set a `GITHUB_TOKEN` (or `GH_TOKEN`) environment variable with a token that has Copilot access.

### macOS / Linux

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/install_node_deps.py

cp config/models.yaml.example config/models.yaml   # then add your API keys

# Generate HTML samples (writes to runs/<timestamp>/)
python -m a11y_llm_tests.cli run --samples 1

# Evaluate the generated samples and build the HTML report
python -m a11y_llm_tests.cli evaluate runs/latest
```

### Windows (PowerShell)

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts\install_node_deps.py

copy config\models.yaml.example config\models.yaml   # then add your API keys

# Generate HTML samples (writes to runs\<timestamp>\)
python -m a11y_llm_tests.cli run --samples 1

# Evaluate the generated samples and build the HTML report
python -m a11y_llm_tests.cli evaluate runs\latest
```

After evaluation, open `runs/latest/index.html` in a browser for the full report.
Detailed per-sample results are saved to `runs/latest/results.json`.

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
