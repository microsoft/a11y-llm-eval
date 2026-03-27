import json
from pathlib import Path
import pytest

from a11y_llm_tests import node_bridge

REQUIRED_HELPER_PATH = str((Path(__file__).resolve().parents[1] / 'node_runner' / 'helpers' / 'test-form-controls.js').resolve())

CASES = [
    (
        'asterisk_end_pass',
        '<label for="i">Name*</label><input id="i" type="text" aria-required="true">',
        'pass',
    ),
    (
        'asterisk_start_pass',
        '<label for="i">* Email</label><input id="i" type="text" required>',
        'pass',
    ),
    (
        'help_required_phrase_pass',
        '<div class="form-field"><label for="i">Phone</label><input id="i" type="text" required><span class="hint">This field is required.</span></div>',
        'pass',
    ),
    (
        'content_required_ignored',
        '<div class="form-field"><label for="i">Expiration</label><input id="i" type="text"><span class="hint">Required format: MM/YYYY</span></div>',
        'na',
    ),
    (
        'asterisk_but_no_attr_fail',
        '<label for="i">Name*</label><input id="i" type="text">',
        'fail',
    ),
    (
        'label_required_word_fail',
        '<label for="i">Phone (required)</label><input id="i" type="text">',
        'fail',
    ),
    (
        'no_visual_indicators_pass',
        '<label for="i">Full Name</label><input id="i" type="text">',
        'na',
    ),
    (
        'in_placeholder_fail',
        '<label for="i">Full Name</label><input id="i" type="text" placeholder="Required">',
        'fail',
    ),
]


@pytest.mark.parametrize('name,html_snippet,expected_status', CASES, ids=[c[0] for c in CASES])
def test_required_fields_indicated(name, html_snippet, expected_status, tmp_path):
    # Build a minimal HTML document containing the snippet
    html = f'<!doctype html><html><head><meta charset="utf-8"></head><body>{html_snippet}</body></html>'

    helper_path_js = json.dumps(REQUIRED_HELPER_PATH)

    # JS test invokes the helper's test function and asserts the overall pass/fail
    test_js = f"""
const testFormControls = require({helper_path_js});
module.exports.run = async ({{page, assert}}) => {{
    const results = await testFormControls.testRequiredFieldsIndicated(page);
    await assert('required-indicated', () => {{
        const status = results && typeof results.status === 'function' ? results.status() : (results && typeof results.passed === 'function' && results.passed() ? 'pass' : 'fail');
        const message = results && typeof results.getMessage === 'function' ? results.getMessage() : '';
        return {{ status, message }};
    }});
}};
"""
    test_js_path = tmp_path / 'test.js'
    test_js_path.write_text(test_js, encoding='utf-8')

    # Run the node runner via the bridge
    screenshot_dir = Path('runs') / 'pytest_screenshots'
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_file = str(screenshot_dir / f"required_fields__{name}.png")

    result = node_bridge.run(html, str(test_js_path), screenshot_file)

    # Ensure the runner succeeded and check the assertion result
    assert 'testFunctionResult' in result, f"Runner failed or returned unexpected output: {result}"
    assertions = result['testFunctionResult'].get('assertions', [])

    found = None
    for a in assertions:
        if a.get('name') == 'required-indicated':
            found = a
            break

    assert found is not None, f"No 'required-indicated' assertion in runner output: {result}"
    if found.get('status') != expected_status:
        actual = (found.get('message') or '').strip().lower()
        pytest.fail(f"Case {name!r} expected status {expected_status!r}, but got {found.get('status')!r}. Message: '{actual}'")
 