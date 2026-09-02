# AGENTS.md

Router / table of contents for agentic tooling working in this repository.
This file intentionally stays short — see the linked documents for details.

## What this repo is

A11y LLM Evaluation Harness and Dataset: a Python + Node.js test harness
that benchmarks how well LLMs generate accessible HTML, using axe-core and
custom assertions rendered via Playwright.

## Where to look

- Agent behavior rules: [`.github/copilot-instructions.md`](.github/copilot-instructions.md)
- Backwards-compatibility contract / behavior spec: [`docs/features-and-acceptance.md`](docs/features-and-acceptance.md)
- Custom-instructions benchmark design: [`docs/custom-instructions-benchmark.md`](docs/custom-instructions-benchmark.md)
- PR / telemetry tagging rules (mandatory on every PR): [`.github/instructions/telemetry.instructions.md`](.github/instructions/telemetry.instructions.md)
- Custom agent: [`.github/agents/git-commit.agent.md`](.github/agents/git-commit.agent.md)
- Custom prompt: [`.github/prompts/review-run.prompt.md`](.github/prompts/review-run.prompt.md)

## Verification / Definition of Done

- Run the Python test suite: `python -m pytest -s` (same command CI runs in
  [`.github/workflows/build.yml`](.github/workflows/build.yml)).
- If you modify CLI, evaluation, or reporting behavior, update
  `docs/features-and-acceptance.md` in the same PR and add/extend tests
  under `tests/test_cases/` per `.github/copilot-instructions.md`.
- Node.js dependencies for the Playwright/axe-core runner are installed via
  `python scripts/install_node_deps.py` (see CI workflow for the full setup
  sequence).

## PR conventions

Every PR must follow the tagging rules in
[`.github/instructions/telemetry.instructions.md`](.github/instructions/telemetry.instructions.md).
