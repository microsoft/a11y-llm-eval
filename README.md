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
- Python orchestrator (generation, execution, reporting)
- Node.js Playwright + axe-core evaluation
- Per-test prompts & injected JS assertions
- HTML report summarizing performance
- Token + cost tracking (tokens in/out/total, per-generation cost, aggregated per model)
- Multi-sample generation with pass@k metrics (probability at least one passing generation in k draws)

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
```

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
- Variant screenshots: `runs/<ts>/screenshots_variants/<variant_id>/<test>__<model>__s<idx>.png`

Report:

- The main tables reflect the **control** results.
- If variants are present, the report includes an **“Instruction Benchmarks (vs Control)”** section with side-by-side metrics and deltas.


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
