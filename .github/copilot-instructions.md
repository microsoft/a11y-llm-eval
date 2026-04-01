# Copilot instructions for this repository

You are working in the **A11y LLM Evaluation Harness** codebase.

## Non-negotiable: Backwards compatibility contract

Before making *any* change that could affect behavior, outputs, or public interfaces, read:

- `docs/features-and-acceptance.md`

Treat it as the project’s contract for:

- CLI behavior and flags
- run directory layout
- `results.json` fields and meaning
- evaluation pass/fail logic
- sampling + pass@k semantics
- prompt configuration and caching
- Node runner I/O contract

## When making changes

1. **Preserve documented behavior by default.**
   - If you find a mismatch between docs and code, assume code is the source of truth and update the doc.

2. **If you intentionally change user-visible behavior** (CLI, artifacts, schema, pass/fail, caching, report path/format):
   - Update `docs/features-and-acceptance.md` in the same PR.
   - Update or add tests in `tests/` to lock the new behavior.
   - Call out breaking changes and any migration steps.

3. **Avoid accidental format drift**
   - Do not rename fields in `results.json` without updating schema and acceptance criteria.
   - Do not change file naming conventions under `runs/<id>/raw` or `runs/<id>/screenshots` without updating docs + tests.

4. **Validation expectations**
   - Prefer running the focused tests for any area you touch.
   - If you modify CLI/evaluation/reporting, run `pytest`.

5. **Create tests for new features**
   - Add test cases under `tests/test_cases/` with clear prompts and assertions.
   - Ensure new tests cover edge cases and failure modes.

## Documentation hygiene

- Keep the acceptance criteria concrete and testable.
- Add new features to `docs/features-and-acceptance.md` when introduced.
- If a behavior is deprecated, document it explicitly with the planned removal version/date.

## Git workflow

- Do not create commits unless the user explicitly asks for a commit or asks to finalize changes in git.
- Before staging or committing, inspect `git status` and the relevant diffs.
- Stage only files directly related to the requested change.
- If unrelated local changes are present, ask before including them in a commit.
- Use non-interactive git commands only.
- Use commit subjects in conventional format: `feat: ...`, `fix: ...`, or `chore: ...`.
- Do not amend, rebase, or push unless the user explicitly asks.
