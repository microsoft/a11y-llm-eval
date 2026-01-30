import json
from pathlib import Path
import pytest

from a11y_llm_tests import node_bridge

HELPER_PATH = str((Path(__file__).resolve().parents[1] / 'node_runner' / 'helpers' / 'get-helper-text.js').resolve())

CASES = [
    (
        'aria_describedby_single',
        '<label for="i">Phone</label><input id="i" type="text" aria-describedby="desc"><span id="desc">Include area code</span>',
        {
            "combined": "include area code",
            "helpers": [
                {"text": "Include area code", "source": "ARIA_DESCRIBEDBY"},
            ],
            "accessible_description": "Include area code",
        },
    ),
    (
        'aria_describedby_multiple',
        '<label for="i">Phone</label><input id="i" type="text" aria-describedby="a b"><span id="a">Include area code</span><span id="b">No dashes</span>',
        {
            "combined": "include area code no dashes",
            "helpers": [
                {"text": "Include area code No dashes", "source": "ARIA_DESCRIBEDBY"},
            ],
            "accessible_description": "Include area code No dashes",
        },
    ),
    (
        'title_attribute',
        '<label for="i">Phone</label><input id="i" type="text" title="Must be 10 digits">',
        {
            "combined": "must be 10 digits",
            "helpers": [
                {"text": "Must be 10 digits", "source": "TITLE"},
            ],
            "accessible_description": "Must be 10 digits",
        },
    ),
    (
        'prefer_describedby_and_title',
        '<label for="i">Phone</label><input id="i" type="text" aria-describedby="desc" title="Must be 10 digits"><span id="desc">Include area code</span>',
        {
            "combined": "must be 10 digits include area code",
            "helpers": [
                {"text": "Must be 10 digits", "source": "TITLE"},
                {"text": "Include area code", "source": "ARIA_DESCRIBEDBY"},
            ],
            "accessible_description": "Include area code",
        },
    ),
    (
        'visual_helper_nearby_below',
        '<div class="form-field"><label for="i">Phone</label><input id="i" type="text"><span class="hint">Include area code</span></div>',
        {
            "combined": "include area code",
            "helpers": [
                {"text": "Include area code", "source": "HELPER_NEARBY"},
            ],
            "accessible_description": "",
        },
    ),
    (
        'visual_helper_prefer_below_over_above',
        '<div class="form-field"><span class="hint">Hint above</span><input id="i" type="text"><span class="hint">Hint below</span></div>',
        {
            "combined": "hint above hint below",
            "helpers": [
                {"text": "Hint above", "source": "HELPER_NEARBY"},
                {"text": "Hint below", "source": "HELPER_NEARBY"},
            ],
            "accessible_description": "",
        },
    ),
    (
        'exclude_label_text',
        '<span>Phone</span><input id="i" type="text">',
        {
            "combined": "",
            "helpers": [
                {"text": "", "source": "NONE"},
            ],
            "accessible_description": "",
        },
    ),
    (
        'exclude_accessible_name_text',
        '<div id="a">Phone</div><input id="i" type="text" aria-labelledby="a"><span class="hint">Include area code</span>',
        {
            "combined": "include area code",
            "helpers": [
                {"text": "Include area code", "source": "HELPER_NEARBY"},
            ],
            "accessible_description": "",
        },
    ),
    (
        'ignore_error_messages',
        '<input id="i" type="text" aria-describedby="err h"><span id="err" class="error">Invalid</span><span id="h">Include area code</span>',
        {
            "combined": "include area code",
            "helpers": [
                {"text": "Include area code", "source": "ARIA_DESCRIBEDBY"},
            ],
            "accessible_description": "Include area code",
        },
    ),
    (
        'none_found',
        '<input id="i" type="text">',
        {
            "combined": "",
            "helpers": [
                {"text": "", "source": "NONE"},
            ],
            "accessible_description": "",
        },
    ),
    (
        'include_only_single_character_visual_helper',
        '<div class="form-field"><span id="name-label" class="label-text">Full Name</span><span aria-hidden="true">*</span><input type="text" id="i" name="fullname" aria-labelledby="name-label" aria-required="true" autocomplete="name"></div>',
        {
            "combined": "*",
            "helpers": [
                {"text": "*", "source": "HELPER_NEARBY"},
            ],
            "accessible_description": "",
        },
    ),
    (
        'include_visual_help_text_combined_with_class',
        '<div class="form-field"><span id="name-label" class="label-text">Full Name</span><span aria-hidden="true">*</span><input type="text" id="i" name="fullname" aria-labelledby="name-label" aria-required="true" autocomplete="name"><span class="hint">This is hint text</span></div>',
        {
            "combined": "* this is hint text",
            "helpers": [
                {"text": "*", "source": "HELPER_NEARBY"},
                {"text": "This is hint text", "source": "HELPER_NEARBY"},
            ],
            "accessible_description": "",
        },
    ),
    (
        'non_adjacent_astrisk',
        '<div class="form-field"><span id="name-label" class="label-text">Full Name</span>*<span class="hint">This is hint text</span><input type="text" id="i" name="fullname" aria-labelledby="name-label" aria-required="true" autocomplete="name"></div>',
        {
            "combined": "* this is hint text",
            "helpers": [
                {"text": "*", "source": "HELPER_NEARBY"},
                {"text": "This is hint text", "source": "HELPER_NEARBY"},
            ],
            "accessible_description": "",
        },
    ),
    (
        'placeholder_used_as_helper',
        '<span>Phone</span><input id="i" type="text" placeholder="Enter your name">',
        {
            "combined": "enter your name",
            "helpers": [
                {"text": "Enter your name", "source": "HELPER_NEARBY"},
            ],
            "accessible_description": "",
        },
    ),
    (
        'placeholder_used_as_label_excluded',
        '<input id="i" type="text" placeholder="Enter your name">',
        {
            "combined": "",
            "helpers": [
                {"text": "", "source": "NONE"},
            ],
            "accessible_description": "",
        },
    ),
    (
        'aria_placeholder_attribute',
        '<span>Phone</span><input id="i" type="text" aria-placeholder="Enter your name">',
        {
            "combined": "enter your name",
            "helpers": [
                {"text": "Enter your name", "source": "ARIA_PLACEHOLDER"},
            ],
            "accessible_description": "",
        },
    ),
    (
        'css_pseudo_placeholder_helper',
        '<style>#i:empty::before { content: attr(data-placeholder); }</style>'
        '<input id="i" type="text" data-placeholder="Enter your name">',
        {
            "combined": "enter your name",
            "helpers": [
                {"text": "Enter your name", "source": "CSS_PLACEHOLDER"},
            ],
            "accessible_description": "",
        },
    ),
    (
        'css_pseudo_placeholder_helper_2',
        '<style>#i:empty::before { content: attr(data-placeholder); }</style>'
        '<label id="lbl">Full name</label><input id="i" aria-labelledby="lbl" type="text" data-placeholder="Enter your name">',
        {
            # CSS pseudo-element placeholder is treated as helper text
            "combined": "enter your name",
            "helpers": [
                {"text": "Enter your name", "source": "CSS_PLACEHOLDER"}
            ],
            "accessible_description": "",
        },
    ),
    (
        'complex_case_with_multiple_sources',
        '<label for="i">Name</label>*<input id="i" type="text" aria-describedby="desc" title="Your full name"><span id="desc" class="hint">Include first and last name</span><span>Use lowercase letters</span>',
        {
            "combined": "* your full name include first and last name use lowercase letters",
            "helpers": [
                {"text": "*", "source": "HELPER_NEARBY"},
                {"text": "Your full name", "source": "TITLE"},
                {"text": "include first and last name", "source": "ARIA_DESCRIBEDBY"},
                {"text": "use lowercase letters", "source": "HELPER_NEARBY"},
            ],
            "accessible_description": "include first and last name",
        },
    ),
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
    const {{getHelperText, combineHelperTexts, getAccessibleDescription}} = require({helper_path_js});
    const input = await page.$('#i');
    const helper = await getHelperText(input);
    const expected = {json.dumps(expected_js)};
    await assert('helper-text', () => {{
        const norm = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();

        const combined = combineHelperTexts(helper);
        const combinedNorm = norm(combined);
        const expectedCombinedNorm = norm(expected && expected.combined);

        const helpers = Array.isArray(helper)
            ? helper
            : (helper ? [helper] : []);

        const actualHelpers = helpers.map(h => {{
            return {{
                text: norm(h && h.text),
                source: h && h.source,
            }};
        }});

        const expectedHelpers = (expected && Array.isArray(expected.helpers))
            ? expected.helpers.map(h => {{
                return {{
                    text: norm(h && h.text),
                    source: h && h.source,
                }};
            }})
            : [];

        const accessibleDescription = getAccessibleDescription(helper);
        const accessibleDescriptionNorm = norm(accessibleDescription);
        const expectedAccessibleDescriptionNorm = norm(expected && expected.accessible_description);

        const pass = combinedNorm === expectedCombinedNorm &&
            JSON.stringify(actualHelpers) === JSON.stringify(expectedHelpers) &&
            accessibleDescriptionNorm === expectedAccessibleDescriptionNorm;

        const message = JSON.stringify({{
            combined,
            actualHelpers,
            accessibleDescription,
            expectedCombined: expected && expected.combined,
            expectedHelpers,
            expectedAccessibleDescription: expected && expected.accessible_description,
        }});
        return {{ pass, message }};
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
        pytest.fail(f"Case {name!r} helper-text assertion failed: {found.get('message')}")