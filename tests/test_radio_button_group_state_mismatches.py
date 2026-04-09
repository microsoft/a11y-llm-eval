from pathlib import Path

import pytest

from a11y_llm_tests import node_bridge


RADIO_TEST_PATH = str((Path(__file__).resolve().parents[1] / 'test_cases' / 'radio-button-group' / 'test.js').resolve())


CASES = [
    (
        'checked_mismatch',
        '''<!doctype html>
<html><body>
  <form>
    <fieldset>
      <legend>Preferred Contact Method</legend>
      <div class="form-field">
        <input id="email" type="radio" name="contact-method" checked aria-checked="false">
        <label for="email">Email</label>
      </div>
      <div class="form-field">
        <input id="phone" type="radio" name="contact-method">
        <label for="phone">Phone</label>
      </div>
    </fieldset>
  </form>
</body></html>''',
        {
            'ARIA attributes match native radio attributes if used': 'fail',
            'Checked state is programmatically exposed': 'fail',
            'Required fields are indicated programmatically': 'na',
        },
    ),
    (
        'required_mismatch',
        '''<!doctype html>
<html><body>
  <form>
    <fieldset>
      <legend>Preferred Contact Method (required)</legend>
      <div class="form-field">
        <input id="email" type="radio" name="contact-method" required checked aria-required="false">
        <label for="email">Email</label>
      </div>
      <div class="form-field">
        <input id="phone" type="radio" name="contact-method">
        <label for="phone">Phone</label>
      </div>
    </fieldset>
  </form>
</body></html>''',
        {
            'ARIA attributes match native radio attributes if used': 'fail',
            'Required fields are indicated visually': 'pass',
            'Required fields are indicated programmatically': 'pass',
            'Checked state is programmatically exposed': 'pass',
        },
    ),
    (
        'disabled_mismatch',
        '''<!doctype html>
<html><body>
  <form>
    <fieldset>
      <legend>Preferred Contact Method</legend>
      <div class="form-field">
        <input id="email" type="radio" name="contact-method" checked>
        <label for="email">Email</label>
      </div>
      <div class="form-field">
        <input id="phone" type="radio" name="contact-method">
        <label for="phone">Phone</label>
      </div>
      <div class="form-field">
        <input id="text" type="radio" name="contact-method" disabled aria-disabled="false">
        <label for="text">Text Message</label>
      </div>
    </fieldset>
  </form>
</body></html>''',
        {
            'ARIA attributes match native radio attributes if used': 'fail',
            'Each radio group is keyboard reachable': 'pass',
            'Arrow keys change the selected radio within each group': 'pass',
            'Checked state is programmatically exposed': 'pass',
        },
    ),
    (
        'global_required_note',
        '''<!doctype html>
<html><body>
  <form>
    <fieldset>
      <legend>Preferred Contact Method</legend>
      <div class="form-field">
        <input id="email" type="radio" name="contact-method" required checked>
        <label for="email">Email</label>
      </div>
      <div class="form-field">
        <input id="phone" type="radio" name="contact-method">
        <label for="phone">Phone</label>
      </div>
    </fieldset>
    <p>All questions are required.</p>
  </form>
</body></html>''',
        {
            'Required fields are indicated visually': 'pass',
            'Required fields are indicated programmatically': 'pass',
            'ARIA attributes match native radio attributes if used': 'pass',
        },
    ),
]


@pytest.mark.parametrize('name,html,expected', CASES, ids=[case[0] for case in CASES])
def test_radio_button_group_native_aria_state_mismatches(name, html, expected):
    screenshot_dir = Path('runs') / 'pytest_screenshots'
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    screenshot_file = str(screenshot_dir / f'radio_state_mismatch__{name}.png')

    result = node_bridge.run(html, RADIO_TEST_PATH, screenshot_file)

    assert 'testFunctionResult' in result, f"Runner failed or returned unexpected output: {result}"
    assertions = result['testFunctionResult'].get('assertions', [])
    actual = {assertion.get('name'): assertion.get('status') for assertion in assertions if assertion.get('name')}

    mismatches = {
        assertion_name: {
            'expected': expected_status,
            'actual': actual.get(assertion_name),
        }
        for assertion_name, expected_status in expected.items()
        if actual.get(assertion_name) != expected_status
    }

    assert not mismatches, f"Unexpected assertion results for {name}: {mismatches}. Full results: {actual}"