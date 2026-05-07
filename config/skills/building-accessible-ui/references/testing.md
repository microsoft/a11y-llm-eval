# Testing

Run automated accessibility tests as part of the deliverable. Writing or configuring a test is not enough — execute it, fix every non-best-practice violation, re-run, and report the result.

## 1. Opt-out gate

Skip testing only when the project explicitly opts out via `CONTRIBUTING`, `AGENTS.md`, `README`, a skill-local instruction, or the user saying to skip. Absence of existing tests is **not** an opt-out.

## 2. Strategy — pick the first that fits

1. **Existing a11y tests** (axe, Playwright + axe, jest-axe, pa11y, Lighthouse CI, Espresso `AccessibilityChecks`, `XCUIAccessibilityAudit`, etc.): extend that suite.
2. **Existing test framework, no a11y tests**: add accessibility tests to the runner in use, matching its conventions.
3. **No framework**: run the UI in a rendered browser and call `axe.run()`. See §3.

## 3. Rendered-browser check (Strategy 3)

Load the UI in a real browser, inject axe-core, run `axe.run()`, and fail on any non-best-practice violation. Use whatever runtime is available. Probe runtimes once each in order — stop at the first that works. Don't reason about availability; run the probe.

**Assume Playwright and Node are already installed.** Probe with one short command; if it works, go straight to the script. **Do not run `pip install playwright`, `pip install axe-playwright-python`, `npm install playwright`, or `playwright install <browser>` unless the probe fails.** Those commands download hundreds of MB or emit multi-line pip warnings that will blow the context on the next turn. Don't pip-install wrapper libraries like `axe-playwright-python` — use the documented `page.add_script_tag(path="/tmp/axe.min.js")` pattern below.

| # | Runtime | Probe | Only if the probe fails |
|---|---|---|---|
| 1 | Python + Playwright | `python -c "import playwright"` | `pip install --quiet --no-input 'playwright~=1.55.0' >/dev/null 2>&1` (then re-probe; do **not** run `playwright install`) |
| 2 | Node + Playwright/Puppeteer + `axe-core` | `node -v` | `npm i --silent --no-progress -D axe-core playwright >/dev/null 2>&1` |
| 3 | Browser MCP tool (e.g. `playwright` MCP) | tool listed? | — |
| 4 | JSDOM + `axe.run(document)` | last resort; misses layout/focus/forced-colors | — |

If `import playwright` succeeds but `chromium.launch()` fails with "Executable doesn't exist", the browser binary is missing. Use `playwright install chromium >/dev/null 2>&1` — redirect the output, or the progress bar will occupy ~1–2k tokens per turn for the rest of the task.

### Python + Playwright example

Fetch axe-core to disk first (once), then have Playwright load it by path. Never read the axe source into Python or print it.

```bash
# once, silently
[ -f /tmp/axe.min.js ] || curl -sSfLo /tmp/axe.min.js https://cdn.jsdelivr.net/npm/axe-core/axe.min.js
```

```python
from playwright.sync_api import sync_playwright
import json, sys

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page()
    page.set_content(open("out.html").read(), wait_until="load")
    page.add_script_tag(path="/tmp/axe.min.js")   # path=, NOT content=
    r = page.evaluate("async () => await window.axe.run()")
    b.close()

wcag = [v for v in r["violations"] if "best-practice" not in v.get("tags", [])]
bp   = [v for v in r["violations"] if "best-practice" in v.get("tags", [])]
print(json.dumps({"wcag": [{"id": v["id"], "impact": v["impact"], "targets": [n["target"] for n in v["nodes"]]} for v in wcag],
                  "bp":   [{"id": v["id"], "targets": [n["target"] for n in v["nodes"]]} for v in bp]}))
sys.exit(1 if wcag else 0)
```

Axe source in fallback runtimes: `require("axe-core").source` (Node), a vendored/`node_modules` copy if present, or the `curl` line above.

Keep tool output minimal: `pip install --quiet`, `npm --silent`, `curl -sSfL`, pipe chatty commands through `2>&1 | tail -5`. Every line a tool prints is re-sent to the model on the next turn.

If every runtime fails, report the first command you ran, its exact stderr, and what would unblock it. "Environment seems limited" is not a report.

## 4. Fix, re-run, report

- Fix every non-best-practice violation. Re-run until clean. Best-practice items are warnings, not failures.
- **Re-run after every post-test edit.** A passing run only certifies the bytes that were tested. If you change the artifact afterwards — even "just styling" or "just a rename" — the previous result is stale. Re-run the same probe against the final artifact before submitting. The submitted artifact and the last tested artifact must be byte-identical.
- In your summary include: pass/fail, violations list (`id`, `impact`, targets), which strategy + runtime you used, and any violation intentionally not fixed (with reason — e.g. pre-existing markup per `SKILL.md` rule 5).

## Common failure modes

- Declaring the environment unusable after one `pip list | grep` or `which node` — probe by importing/invoking.
- Running `pip install playwright` or `playwright install chromium` without probing first. Probe → run script. Only install on failure, and always redirect the output.
- Passing `--quiet` to a command that doesn't support it (e.g. `playwright install --quiet` is not valid). Use `>/dev/null 2>&1` or `2>&1 | tail -5` instead.
- Writing tests but not running them. Configuring ≠ testing.
- Editing the artifact after the last passing run and submitting without re-testing. The clean result no longer applies.
- Flipping best-practice / WCAG severity.
- Letting verbose install output (pip downloads, curl progress, `playwright install` chatter) fill the context. Use quiet flags *and* redirect.
- Reading the axe source into your script (`open(axe).read()`, `urlopen(...).read()`, `require("axe-core").source` printed to stdout).
