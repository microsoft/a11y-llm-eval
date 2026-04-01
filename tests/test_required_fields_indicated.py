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
        'pass',
    ),
    (
        'asterisk_start_pass',
        '<label for="i">* Email</label><input id="i" type="text" required>',
        'pass',
        'pass',
    ),
    (
        'help_required_phrase_pass',
        '<div class="form-field"><label for="i">Phone</label><input id="i" type="text" required><span class="hint">This field is required.</span></div>',
        'pass',
        'pass',
    ),
    (
        'content_required_ignored',
        '<div class="form-field"><label for="i">Expiration</label><input id="i" type="text"><span class="hint">Required format: MM/YYYY</span></div>',
        'na',
        'na',
    ),
    (
        'asterisk_but_no_attr_fail',
        '<label for="i">Name*</label><input id="i" type="text">',
        'pass',
        'fail',
    ),
    (
        'label_required_word_fail',
        '<label for="i">Phone (required)</label><input id="i" type="text">',
        'pass',
        'fail',
    ),
    (
        'no_visual_indicators_pass',
        '<label for="i">Full Name</label><input id="i" type="text">',
        'na',
        'na',
    ),
    (
        'programmatic_only_fail',
        '<label for="i">Full Name</label><input id="i" type="text" required>',
        'fail',
        'pass',
    ),
    (
        'placeholder_required_not_visual',
        '<input id="i" type="text" placeholder="Required" required>',
        'fail',
        'pass',
    ),
]


@pytest.mark.parametrize('name,html_snippet,expected_visual_status,expected_programmatic_status', CASES, ids=[c[0] for c in CASES])
def test_required_fields_indicated(name, html_snippet, expected_visual_status, expected_programmatic_status, tmp_path):
    # Build a minimal HTML document containing the snippet
    html = f'<!doctype html><html><head><meta charset="utf-8"></head><body>{html_snippet}</body></html>'

    helper_path_js = json.dumps(REQUIRED_HELPER_PATH)

    # JS test invokes the helper's test function and asserts the overall pass/fail
    test_js = f"""
const testFormControls = require({helper_path_js});
module.exports.run = async ({{page, assert}}) => {{
    const visualResults = await testFormControls.testRequiredFieldsIndicatedVisually(page);
    const programmaticResults = await testFormControls.testRequiredFieldsIndicatedProgrammatically(page);
    await assert('required-indicated-visually', () => {{
        const status = visualResults && typeof visualResults.status === 'function' ? visualResults.status() : (visualResults && typeof visualResults.passed === 'function' && visualResults.passed() ? 'pass' : 'fail');
        const message = visualResults && typeof visualResults.getMessage === 'function' ? visualResults.getMessage() : '';
        return {{ status, message }};
    }});
    await assert('required-indicated-programmatically', () => {{
        const status = programmaticResults && typeof programmaticResults.status === 'function' ? programmaticResults.status() : (programmaticResults && typeof programmaticResults.passed === 'function' && programmaticResults.passed() ? 'pass' : 'fail');
        const message = programmaticResults && typeof programmaticResults.getMessage === 'function' ? programmaticResults.getMessage() : '';
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

    found_visual = None
    found_programmatic = None
    for a in assertions:
        if a.get('name') == 'required-indicated-visually':
            found_visual = a
        if a.get('name') == 'required-indicated-programmatically':
            found_programmatic = a

    assert found_visual is not None, f"No 'required-indicated-visually' assertion in runner output: {result}"
    assert found_programmatic is not None, f"No 'required-indicated-programmatically' assertion in runner output: {result}"
    if found_visual.get('status') != expected_visual_status:
        actual = (found_visual.get('message') or '').strip().lower()
        pytest.fail(f"Case {name!r} expected visual status {expected_visual_status!r}, but got {found_visual.get('status')!r}. Message: '{actual}'")
    if found_programmatic.get('status') != expected_programmatic_status:
        actual = (found_programmatic.get('message') or '').strip().lower()
        pytest.fail(f"Case {name!r} expected programmatic status {expected_programmatic_status!r}, but got {found_programmatic.get('status')!r}. Message: '{actual}'")
 