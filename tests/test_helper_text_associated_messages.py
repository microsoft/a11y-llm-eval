import json
from pathlib import Path

from a11y_llm_tests import node_bridge


FORM_CONTROLS_HELPER_PATH = str((Path(__file__).resolve().parents[1] / 'node_runner' / 'helpers' / 'test-form-controls.js').resolve())


def test_helper_text_associated_message_lists_failing_controls_for_repeated_group_helper(tmp_path):
    html = '''<!doctype html>
<html><body>
  <form>
    <div class="form-field">
      <legend>Which planets in our solar system are considered gas giants?</legend>
      <p class="helper-text">Select all planets primarily composed of hydrogen and helium.</p>
      <div class="checkbox-group">
        <div class="checkbox-option"><input type="checkbox" id="q2-a" name="q2" value="Mercury"><label for="q2-a">Mercury</label></div>
        <div class="checkbox-option"><input type="checkbox" id="q2-b" name="q2" value="Jupiter"><label for="q2-b">Jupiter</label></div>
        <div class="checkbox-option"><input type="checkbox" id="q2-c" name="q2" value="Venus"><label for="q2-c">Venus</label></div>
        <div class="checkbox-option"><input type="checkbox" id="q2-d" name="q2" value="Saturn"><label for="q2-d">Saturn</label></div>
        <div class="checkbox-option"><input type="checkbox" id="q2-e" name="q2" value="Neptune"><label for="q2-e">Neptune</label></div>
      </div>
    </div>
  </form>
</body></html>'''

    helper_path_js = json.dumps(FORM_CONTROLS_HELPER_PATH)

    test_js = f'''
const testFormControls = require({helper_path_js});
module.exports.run = async ({{page, assert}}) => {{
    const discovery = await testFormControls.discoverCheckboxes(page);
    const results = await testFormControls.testHelperTextAssociated(page, discovery);
    await assert('helper-text-associated', () => {{
        const status = results && typeof results.status === 'function' ? results.status() : 'fail';
        const message = results && typeof results.getMessage === 'function' ? results.getMessage() : '';
        return {{ status, message }};
    }});
}};
'''
    test_js_path = tmp_path / 'test.js'
    test_js_path.write_text(test_js, encoding='utf-8')

    screenshot_dir = Path('runs') / 'pytest_screenshots'
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_file = str(screenshot_dir / 'helper_text_associated_message_dedup.png')

    result = node_bridge.run(html, str(test_js_path), screenshot_file)

    assert 'testFunctionResult' in result, f"Runner failed or returned unexpected output: {result}"
    assertions = result['testFunctionResult'].get('assertions', [])
    found = next((assertion for assertion in assertions if assertion.get('name') == 'helper-text-associated'), None)

    assert found is not None, f"No 'helper-text-associated' assertion in runner output: {result}"
    assert found.get('status') == 'fail'

    message = found.get('message') or ''
    assert 'text input "Mercury" has helper text "Select all planets primarily composed of hydrogen and helium."' in message
    assert 'text input "Neptune" has helper text "Select all planets primarily composed of hydrogen and helium."' in message


def test_helper_text_associated_group_requires_real_programmatic_description(tmp_path):
    html = '''<!doctype html>
<html><body>
  <form>
    <div class="form-field">
      <div role="group" aria-labelledby="fruit-question" aria-describedby="missing-desc">
        <div id="fruit-question">Which fruits do you like?</div>
        <p class="helper-text">Choose all fruits you like.</p>
        <div><input type="checkbox" id="fruit-a"><label for="fruit-a">Apple</label></div>
        <div><input type="checkbox" id="fruit-b"><label for="fruit-b">Banana</label></div>
      </div>
    </div>
  </form>
</body></html>'''

    helper_path_js = json.dumps(FORM_CONTROLS_HELPER_PATH)

    test_js = f'''
const testFormControls = require({helper_path_js});
module.exports.run = async ({{page, assert}}) => {{
    const discovery = await testFormControls.discoverCheckboxes(page);
    const results = await testFormControls.testHelperTextAssociated(page, discovery);
    await assert('helper-text-associated', () => {{
        const status = results && typeof results.status === 'function' ? results.status() : 'fail';
        const message = results && typeof results.getMessage === 'function' ? results.getMessage() : '';
        return {{ status, message }};
    }});
}};
'''
    test_js_path = tmp_path / 'test.js'
    test_js_path.write_text(test_js, encoding='utf-8')

    screenshot_dir = Path('runs') / 'pytest_screenshots'
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_file = str(screenshot_dir / 'helper_text_associated_group_missing_desc.png')

    result = node_bridge.run(html, str(test_js_path), screenshot_file)

    assert 'testFunctionResult' in result, f"Runner failed or returned unexpected output: {result}"
    assertions = result['testFunctionResult'].get('assertions', [])
    found = next((assertion for assertion in assertions if assertion.get('name') == 'helper-text-associated'), None)

    assert found is not None, f"No 'helper-text-associated' assertion in runner output: {result}"
    assert found.get('status') == 'fail'

    message = found.get('message') or ''
    assert 'checkbox group "Which fruits do you like?" has helper text "Choose all fruits you like." that is not programmatically associated' in message
