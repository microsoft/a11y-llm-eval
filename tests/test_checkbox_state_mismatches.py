from pathlib import Path

import pytest

from a11y_llm_tests import node_bridge


CHECKBOX_TEST_PATH = str((Path(__file__).resolve().parents[1] / 'test_cases' / 'single-checkbox' / 'test.js').resolve())


CASES = [
    (
        'checked_mismatch',
        '''<!doctype html>
<html><body>
  <form>
    <div class="form-field">
      <input id="consent" type="checkbox" checked aria-checked="false">
      <label for="consent">I agree to the policy</label>
    </div>
  </form>
</body></html>''',
        {
            'ARIA attributes match native checkbox attributes if used': 'fail',
            'Checked state is programmatically exposed': 'fail',
            'Required fields are indicated programmatically': 'na',
        },
        {
          'ARIA attributes match native checkbox attributes if used': ['I agree to the policy', 'checked'],
          'Checked state is programmatically exposed': ['I agree to the policy'],
        },
    ),
    (
        'required_mismatch',
        '''<!doctype html>
<html><body>
  <form>
    <div class="form-field">
      <input id="updates" type="checkbox" required checked aria-required="false">
      <label for="updates">Receive account updates (required)</label>
    </div>
  </form>
</body></html>''',
        {
            'ARIA attributes match native checkbox attributes if used': 'fail',
            'Required fields are indicated visually': 'pass',
            'Required fields are indicated programmatically': 'pass',
            'Checked state is programmatically exposed': 'pass',
        },
        {
          'ARIA attributes match native checkbox attributes if used': ['Receive account updates', 'required'],
        },
    ),
    (
        'disabled_mismatch',
        '''<!doctype html>
<html><body>
  <form>
    <div class="form-field">
      <input id="offers" type="checkbox" disabled aria-disabled="false">
      <label for="offers">Send me promotional offers</label>
    </div>
  </form>
</body></html>''',
        {
            'ARIA attributes match native checkbox attributes if used': 'fail',
            'Each checkbox is keyboard reachable': 'pass',
            'Space toggles checkbox state': 'fail',
            'Checked state is programmatically exposed': 'pass',
        },
        {
          'ARIA attributes match native checkbox attributes if used': ['Send me promotional offers', 'disabled'],
          'Space toggles checkbox state': ['Send me promotional offers'],
        },
    ),
    (
        'global_required_note',
        '''<!doctype html>
<html><body>
  <form>
    <div class="form-field">
      <input id="alerts" type="checkbox" required checked>
      <label for="alerts">Receive emergency alerts</label>
    </div>
    <p>All options are required.</p>
  </form>
</body></html>''',
        {
            'Required fields are indicated visually': 'pass',
            'Required fields are indicated programmatically': 'pass',
            'ARIA attributes match native checkbox attributes if used': 'pass',
        },
        {},
    ),
    (
        'native_indeterminate_mixed',
        '''<!doctype html>
<html><body>
  <form>
    <div class="form-field">
      <input id="select-all" type="checkbox" aria-checked="mixed">
      <label for="select-all">Select all notifications</label>
    </div>
    <script>
      document.getElementById('select-all').indeterminate = true;
    </script>
  </form>
</body></html>''',
        {
            'ARIA attributes match native checkbox attributes if used': 'pass',
            'Checked state is programmatically exposed': 'pass',
            'Space toggles checkbox state': 'pass',
        },
        {},
    ),
    (
        'aria_mixed_custom_checkbox',
        '''<!doctype html>
<html><body>
  <form>
    <div class="form-field">
      <div id="bulk" role="checkbox" aria-checked="mixed" tabindex="0" aria-label="Select all notifications"></div>
    </div>
  </form>
</body></html>''',
        {
            'ARIA attributes match native checkbox attributes if used': 'pass',
            'Checked state is programmatically exposed': 'pass',
            'Each checkbox is keyboard reachable': 'pass',
        },
        {},
    ),
]


@pytest.mark.parametrize('name,html,expected,expected_messages', CASES, ids=[case[0] for case in CASES])
def test_checkbox_native_aria_state_mismatches(name, html, expected, expected_messages):
    screenshot_dir = Path('runs') / 'pytest_screenshots'
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_file = str(screenshot_dir / f'checkbox_state_mismatch__{name}.png')

    result = node_bridge.run(html, CHECKBOX_TEST_PATH, screenshot_file)

    assert 'testFunctionResult' in result, f"Runner failed or returned unexpected output: {result}"
    assertions = result['testFunctionResult'].get('assertions', [])
    actual = {assertion.get('name'): assertion.get('status') for assertion in assertions if assertion.get('name')}
    messages = {assertion.get('name'): assertion.get('message') for assertion in assertions if assertion.get('name')}

    mismatches = {
        assertion_name: {
            'expected': expected_status,
            'actual': actual.get(assertion_name),
        }
        for assertion_name, expected_status in expected.items()
        if actual.get(assertion_name) != expected_status
    }

    assert not mismatches, f"Unexpected assertion results for {name}: {mismatches}. Full results: {actual}"

    for assertion_name, expected_fragments in expected_messages.items():
        message = messages.get(assertion_name) or ''
        for fragment in expected_fragments:
            assert fragment in message, f"Expected '{fragment}' in assertion message for {name}/{assertion_name}, got: {message}"