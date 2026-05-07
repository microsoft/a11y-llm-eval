---
description: Review the latest evaluation run for false positives, false negatives, errors, and missed issues.
---

# Review latest evaluation run

Review the most recent evaluation run for accuracy issues.

## Steps

1. **Identify the latest run** — check `runs/latest` symlink.

2. **Re-evaluate with current test code** — run `python -m a11y_llm_tests.cli evaluate <run_dir>` to get fresh results against the current assertions.

3. **Summarize results** — parse `results.json` and report:
   - Total pass / fail / error counts
   - Top failing assertions ranked by frequency
   - Any `error` status samples (test infrastructure failures)

4. **Check for false positives** — for each failing assertion type:
   - Pick 2–3 diverse samples (different models, prompt variants)
   - Run the sample through the runner: `node node_runner/runner.js <html> <test.js> <out.json> <screenshot.png>`
   - View the screenshot to see what the page actually looks like
   - Read the HTML source to check if the failure is legitimate
   - A false positive = the page is correct but the test says it fails

5. **Check for false negatives** — spot-check 3–5 passing samples:
   - View screenshots for obvious accessibility issues the tests should have caught
   - Look for missing labels, broken focus management, inaccessible patterns that passed

6. **Check for missed detections** — look at error/edge cases:
   - Empty HTML files (generation failures) — should these be `error` not `fail`?
   - Samples where all assertions pass but the screenshot shows problems
   - Assertions that return `na` — are they correctly not-applicable?

7. **Report findings** organized as:
   - **True failures** (legitimate, no action needed) — list with counts
   - **False positives** (test bug) — describe the issue and which file to fix
   - **False negatives** (missed issue) — describe what was missed
   - **Edge cases** — note any handling improvements needed
   - **Errors** — infrastructure issues to investigate

## Reporting note

When reporting false positives/negatives, include:

- The specific assertion name(s) involved
- The sample HTML file path (relative to the `runs` directory)
- A brief description of the issue (e.g. "The test failed because it looked for a `role="button"` but the element was a `<div>` with a click handler, which is a common pattern that should be supported.")
- A brief root cause analysis (e.g. "The test only checks for ARIA roles and misses interactive elements that don't use ARIA but are still accessible.")
- A brief suggestion for how to fix the test (e.g. "Update the test to also recognize elements with click handlers as buttons, not just those with `role="button"`.")

## Key files

- `runs/<run_id>/results.json` — evaluation results
- `runs/<run_id>/raw/<test>/<model>/index.html` — generated HTML
- `test_cases/<test>/test.js` — test assertions
- `node_runner/helpers/test-form-controls.js` — form control test logic
- `node_runner/helpers/get-visual-label.js` — visual label detection
- `node_runner/helpers/get-accessibility-tree.js` — AT visibility checks

## Useful commands

```bash
# Re-evaluate a run
python -m a11y_llm_tests.cli evaluate runs/<run_id>

# Run a single sample through the test runner
node node_runner/runner.js <html_path> <test.js_path> /tmp/out.json /tmp/screenshot.png

# Parse results summary
python3 -c "
import json
from collections import Counter
r = json.load(open('runs/<run_id>/results.json'))
results = r['results']
statuses = Counter(s.get('test_function',{}).get('status','unknown') for s in results)
print(dict(statuses))
assertion_fails = Counter()
for s in results:
    for a in s.get('test_function',{}).get('assertions',[]):
        if a.get('status') == 'fail':
            assertion_fails[a['name']] += 1
for name, count in assertion_fails.most_common(20):
    print(f'{count:3d}x  {name}')
"
```
