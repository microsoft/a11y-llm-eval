import json
from pathlib import Path

import pytest

from a11y_llm_tests import node_bridge


HELPER_PATH = str((Path(__file__).resolve().parents[1] / 'node_runner' / 'helpers' / 'get-accessibility-tree.js').resolve())


CASES = [
    (
        'textbox_name_and_description',
        '<label for="i">Phone</label><input id="i" type="text" aria-describedby="desc"><span id="desc">Include area code</span>',
        '#i',
        {
            'name': 'phone',
            'description': 'include area code',
        },
    ),
    (
        'group_name_and_description',
        '<div id="question">Favorite fruits</div>'
        '<div id="hint">Choose all that apply.</div>'
        '<div id="group" role="group" aria-labelledby="question" aria-describedby="hint">'
        '<div><input id="apple" type="checkbox"><label for="apple">Apple</label></div>'
        '<div><input id="banana" type="checkbox"><label for="banana">Banana</label></div>'
        '</div>',
        '#group',
        {
            'name': 'favorite fruits',
            'description': 'choose all that apply.',
        },
    ),
]


@pytest.mark.parametrize('name,html_snippet,selector,expected', CASES, ids=[case[0] for case in CASES])
def test_get_accessibility_tree(name, html_snippet, selector, expected, tmp_path):
    html = f'<!doctype html><html><head><meta charset="utf-8"></head><body>{html_snippet}</body></html>'

    helper_path_js = json.dumps(HELPER_PATH)
    selector_js = json.dumps(selector)

    test_js = f"""
module.exports.run = async ({{page, assert}}) => {{
    const {{getAccessibilityNodeInfo}} = require({helper_path_js});
    const locator = page.locator({selector_js});
    const info = await getAccessibilityNodeInfo(locator);

    await assert('accessibility-tree', () => {{
        const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
        return {{
            status: norm(info && info.name) === norm({json.dumps(expected['name'])})
                && norm(info && info.description) === norm({json.dumps(expected['description'])})
                ? 'pass'
                : 'fail',
            message: JSON.stringify(info || {{}}),
        }};
    }});
}};
"""

    test_js_path = tmp_path / 'test.js'
    test_js_path.write_text(test_js, encoding='utf-8')

    screenshot_dir = Path('runs') / 'pytest_screenshots'
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_file = str(screenshot_dir / f'accessibility_tree__{name}.png')

    result = node_bridge.run(html, str(test_js_path), screenshot_file)

    assert 'testFunctionResult' in result, f"Runner failed or returned unexpected output: {result}"
    assertions = result['testFunctionResult'].get('assertions', [])
    found = next((assertion for assertion in assertions if assertion.get('name') == 'accessibility-tree'), None)

    assert found is not None, f"No 'accessibility-tree' assertion in runner output: {result}"
    assert found.get('status') == 'pass', found.get('message')