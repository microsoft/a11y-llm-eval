import json
from pathlib import Path

import pytest

from a11y_llm_tests import node_bridge

FORM_CONTROLS_HELPER_PATH = str((Path(__file__).resolve().parents[1] / 'node_runner' / 'helpers' / 'test-form-controls.js').resolve())

CASES = [
    (
        'autocomplete_no_recognizable_purpose',
        'testIdentifyInputPurposeAutocomplete',
        '<label for="i">Comments</label><input id="i" type="text">',
        'na',
    ),
    (
        'placeholder_no_placeholder_text',
        'testPlaceholderTextDefined',
        '<label for="i">Full Name</label><input id="i" type="text" autocomplete="name">',
        'na',
    ),
]


@pytest.mark.parametrize('name,helper_name,html_snippet,expected_status', CASES, ids=[c[0] for c in CASES])
def test_form_control_helpers_not_applicable(name, helper_name, html_snippet, expected_status, tmp_path):
    html = f'<!doctype html><html><head><meta charset="utf-8"></head><body>{html_snippet}</body></html>'

    helper_path_js = json.dumps(FORM_CONTROLS_HELPER_PATH)
    helper_name_js = json.dumps(helper_name)

    test_js = f"""
const testFormControls = require({helper_path_js});
module.exports.run = async ({{page, assert}}) => {{
    const results = await testFormControls[{helper_name_js}](page);
    await assert('helper-status', () => {{
        const status = results && typeof results.status === 'function' ? results.status() : (results && typeof results.passed === 'function' && results.passed() ? 'pass' : 'fail');
        const message = results && typeof results.getMessage === 'function' ? results.getMessage() : '';
        return {{ status, message }};
    }});
}};
"""
    test_js_path = tmp_path / 'test.js'
    test_js_path.write_text(test_js, encoding='utf-8')

    screenshot_dir = Path('runs') / 'pytest_screenshots'
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_file = str(screenshot_dir / f"form_controls_not_applicable__{name}.png")

    result = node_bridge.run(html, str(test_js_path), screenshot_file)

    assert 'testFunctionResult' in result, f"Runner failed or returned unexpected output: {result}"
    assertions = result['testFunctionResult'].get('assertions', [])

    found = None
    for assertion in assertions:
        if assertion.get('name') == 'helper-status':
            found = assertion
            break

    assert found is not None, f"No 'helper-status' assertion in runner output: {result}"
    assert found.get('status') == expected_status, (
        f"Case {name!r} expected status {expected_status!r}, but got {found.get('status')!r}. "
        f"Message: {(found.get('message') or '').strip()}"
    )
