from pathlib import Path

from a11y_llm_tests.prompt_specs import load_prompt_specs


def test_load_prompt_specs_expands_global_and_local_dimensions(tmp_path: Path):
    test_cases_dir = tmp_path / "test_cases"
    case_dir = test_cases_dir / "single-checkbox"
    case_dir.mkdir(parents=True)
    (case_dir / "prompt.yaml").write_text(
        """
name: Single Checkbox
base_prompt: |
  Build a consent checkbox.
common_requirements:
  - Wrap the checkbox in a div with class \"form-field\".
dimensions:
  requirement:
    label: Requirement
    values:
      required:
        label: Required
        prompt_fragment: Make the checkbox required.
      optional:
        label: Optional
        prompt_fragment: Make the checkbox optional.
""".strip() + "\n",
        encoding="utf-8",
    )

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "prompt_dimensions.yaml").write_text(
        """
dimensions:
  framework:
    label: Framework
    values:
      vanilla-js:
        label: Vanilla JS
        prompt_fragment: Use vanilla JavaScript.
      react:
        label: React
        prompt_fragment: Structure it like a React team would.
""".strip() + "\n",
        encoding="utf-8",
    )

    prompt_spec_set = load_prompt_specs(test_cases_dir, config_dir / "prompt_dimensions.yaml")

    assert len(prompt_spec_set.prompt_cases) == 4
    case_names = {case.test_name for case in prompt_spec_set.prompt_cases}
    assert "Single Checkbox | Vanilla JS | Required" in case_names
    assert "Single Checkbox | React | Optional" in case_names

    first_case = prompt_spec_set.prompt_cases[0]
    assert first_case.prompt_case_id.startswith("single-checkbox--")
    assert "Requirements:" in first_case.prompt_text
    assert 'div with class "form-field"' in first_case.prompt_text