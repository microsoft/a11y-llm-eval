import json
from pathlib import Path
import pytest

from a11y_llm_tests import node_bridge

HELPER_PATH = str((Path(__file__).resolve().parents[1] / 'node_runner' / 'helpers' / 'get-helper-text.js').resolve())

CASES = [
    (
        'aria_describedby_single',
        '<label for="i">Phone</label><input id="i" type="text" aria-describedby="desc"><span id="desc">Include area code</span>',
        'include area code',
    ),
    (
        'aria_describedby_multiple',
        '<label for="i">Phone</label><input id="i" type="text" aria-describedby="a b"><span id="a">Include area code</span><span id="b">No dashes</span>',
        'include area code no dashes',
    ),
    (
        'title_attribute',
        '<label for="i">Phone</label><input id="i" type="text" title="Must be 10 digits">',
        'must be 10 digits',
    ),
    (
        'prefer_describedby_over_title',
        '<label for="i">Phone</label><input id="i" type="text" aria-describedby="desc" title="Must be 10 digits"><span id="desc">Include area code</span>',
        'include area code',
    ),
    (
        'visual_helper_nearby_below',
        '<div class="form-field"><label for="i">Phone</label><input id="i" type="text"><span class="hint">Include area code</span></div>',
        'include area code',
    ),
    (
        'visual_helper_prefer_below_over_above',
        '<div class="form-field"><span class="hint">Hint above</span><input id="i" type="text"><span class="hint">Hint below</span></div>',
        'hint above hint below',
    ),
    (
        'exclude_label_text',
        '<span>Phone</span><input id="i" type="text">',
        '',
    ),
    (
        'exclude_accessible_name_text',
        '<div id="a">Phone</div><input id="i" type="text" aria-labelledby="a"><span class="hint">Include area code</span>',
        'include area code',
    ),
    (
        'ignore_error_messages',
        '<input id="i" type="text" aria-describedby="err h"><span id="err" class="error">Invalid</span><span id="h">Include area code</span>',
        'include area code',
    ),
    (
        'none_found',
        '<input id="i" type="text">',
        '',
    ),
    (
        'ignore_only_single_character_visual_helper',
        '<div class="form-field"><span id="name-label" class="label-text">Full Name</span><span aria-hidden="true">*</span><input type="text" id="i" name="fullname" aria-labelledby="name-label" aria-required="true" autocomplete="name"></div>',
        ''
    )
    ,
    (
        'placeholder_used_as_helper',
        '<span>Phone</span><input id="i" type="text" placeholder="Enter your name">',
        'enter your name',
    )
    ,
    (
        'placeholder_used_as_label_excluded',
        '<input id="i" type="text" placeholder="Enter your name">',
        '',
    )
]


@pytest.mark.parametrize('name,html_snippet,expected', CASES, ids=[c[0] for c in CASES])
def test_get_helper_text(name, html_snippet, expected, tmp_path):
    # Build a minimal HTML document containing the snippet
    html = f'<!doctype html><html><head><meta charset="utf-8"></head><body>{html_snippet}</body></html>'

    # Create a small test.js that requires the helper via absolute path and asserts the helper text
    helper_path_js = json.dumps(HELPER_PATH)
    expected_js = expected

    test_js = f"""
module.exports.run = async ({{page, assert}}) => {{
    const {{getHelperText}} = require({helper_path_js});
    const input = await page.$('#i');
    const helper = await getHelperText(input);
    const expected = {json.dumps(expected_js)};
    await assert('helper-text', () => {{
        const helperStr = (helper.text || '').trim().toLowerCase();
        const expectedStr = (expected || '').trim().toLowerCase();
        const pass = helperStr === expectedStr;
        return {{ pass, message: helperStr || '' }};
    }});
}};
"""
    test_js_path = tmp_path / 'test.js'
    test_js_path.write_text(test_js, encoding='utf-8')

    # Run the node runner via the bridge
    screenshot_dir = Path('runs') / 'pytest_screenshots'
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_file = str(screenshot_dir / f"helper_text__{name}.png")

    result = node_bridge.run(html, str(test_js_path), screenshot_file)

    # Ensure the runner succeeded and check the assertion result
    assert 'testFunctionResult' in result, f"Runner failed or returned unexpected output: {result}"
    assertions = result['testFunctionResult'].get('assertions', [])

    found = None
    for a in assertions:
        if a.get('name') == 'helper-text':
            found = a
            break

    assert found is not None, f"No 'helper-text' assertion in runner output: {result}"
    if found.get('status') != 'pass':
        actual = (found.get('message') or '').strip().lower()
        pytest.fail(f"Case {name!r} expected helper text to be \"{expected}\", got: \"{actual}\"")