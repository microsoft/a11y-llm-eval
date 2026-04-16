import json
import tempfile
from pathlib import Path
import pytest

from a11y_llm_tests import node_bridge

HELPER_PATH = str((Path(__file__).resolve().parents[1] / 'node_runner' / 'helpers' / 'get-visual-label.js').resolve())

CASES = [
    (
        'label_for',
        '<label for="i">Full Name</label><input id="i" type="text">',
        'full name',
    ),
    (
        'nested_label',
        '<label>Nickname<input id="i" type="text"></label>',
        'nickname',
    ),
    (
        'aria_labelledby',
        '<div id="a">Email</div><div id="b">(work)</div><input id="i" aria-labelledby="a b">',
        'email (work)',
    ),
    (
        'visual_nearby',
        '<div class="form-field"><span class="label-text">Phone</span><input id="i" type="text"></div>',
        'phone',
    ),
    (
        'multiple_nearby',
        '<div class="form-field"><span>Label One</span><span>Label Two</span><input id="i" type="text"></div>',
        'label one label two',
    ),
    (
        'multiple_programmatic_labels',
        '<label for="i">A</label><label for="i">B</label><input id="i" type="text">',
        'a b',
    ),
    (
        'placeholder_only',
        '<input id="i" type="text" placeholder="Enter your name">',
        'enter your name',
    ),
    (
        'visual_and_placeholder',
        '<span>Phone</span><input id="i" type="text" placeholder="Enter your name">',
        'phone',
    ),
    (
        'visual_hint',
        '<span>Phone</span><input id="i" type="text" placeholder="Enter your name"><span class="hint">Include area code</span>',
        'phone',
    ),
    (
        'visual_label_and_aria_describedby',
        '<span>Phone</span><input id="i" type="text" placeholder="Enter your name" aria-describedby="desc"><span id="desc">Include area code</span>',
        'phone',
    ),
    (
        'astrisk_in_label',
        '<div class="form-field"><label><span class="label-text">Full Name <span aria-hidden="true">*</span></span><input id="i" type="text" name="fullname" required autocomplete="name"></label></div>',
        'full name *',
    ),
    (
        'asterisk_css_after_in_label',
        '<style>label.required::after { content: " *"; }</style><div class="form-field"><label class="required" for="i">Full Name</label><input id="i" type="text" name="fullname" required autocomplete="name"></div>',
        'full name *',
    ),
    (
        'transparent_text_excluded',
        '<style>.visually-hidden-text { color: transparent; }</style><label for="i">Full<span class="visually-hidden-text"> Invisible</span> Name</label><input id="i" type="text">',
        'full name',
    ),
    (
        'nested_label_with_option_description',
        '<label class="option"><input id="i" type="checkbox" aria-label="Python"><span class="option-label"><span class="option-title">Python</span><span class="option-desc">A valid language or technology in this context.</span></span></label>',
        'python',
    ),
    (
        'nested_label_with_required_indicator_and_description',
        '<label class="option"><input id="i" type="checkbox" aria-label="Python"><span class="option-label"><span class="option-title">Python<span aria-hidden="true">*</span></span><span class="option-desc">A valid language or technology in this context.</span></span></label>',
        'python*',
    ),
]

@pytest.mark.parametrize('name,html_snippet,expected', CASES, ids=[c[0] for c in CASES])
def test_get_visual_label(name, html_snippet, expected, tmp_path):
        # Build a minimal HTML document containing the snippet
        html = f'<!doctype html><html><head><meta charset="utf-8"></head><body>{html_snippet}</body></html>'

        # Create a small test.js that requires the helper via absolute path and asserts the label
        helper_path_js = json.dumps(HELPER_PATH)
        expected_js = expected

        # The in-page assertion returns an object with `pass` and `message` so we can see the label
        # and allow order-insensitive matching of expected words.
        test_js = f"""
const {{getVisualLabel}} = require({helper_path_js});
module.exports.run = async ({{page, assert}}) => {{
    const input = await page.$('#i');
    const label = await getVisualLabel(input);
    const expected = {json.dumps(expected_js)};
    await assert('visual-label', () => {{
        const labelStr = (label.text || '').trim().toLowerCase();
        const expectedStr = (expected || '').trim().toLowerCase();
        const pass = labelStr === expectedStr;
        return {{ pass, message: labelStr || '' }};
    }});
}};
"""
        test_js_path = tmp_path / 'test.js'
        test_js_path.write_text(test_js, encoding='utf-8')

        # Run the node runner via the bridge
        screenshot_dir = Path('runs') / 'pytest_screenshots'
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot_file = str(screenshot_dir / f"visual_label__{name}.png")

        result = node_bridge.run(html, str(test_js_path), screenshot_file)

        # Ensure the runner succeeded and check the assertion result
        assert 'testFunctionResult' in result, f"Runner failed or returned unexpected output: {result}"
        assertions = result['testFunctionResult'].get('assertions', [])
        # Find our assertion
        found = None
        for a in assertions:
                if a.get('name') == 'visual-label':
                        found = a
                        break

        assert found is not None, f"No 'visual-label' assertion in runner output: {result}"
        if found.get('status') != 'pass':
            # allow partial match: accept if the returned message contains at least one expected part
            actual = (found.get('message') or '').strip().lower()
            pytest.fail(f"Case {name!r} expected label to be \"{expected}\", got: \"{actual}\"")
