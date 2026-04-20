from pathlib import Path

import pytest

from a11y_llm_tests.prompt_specs import load_prompt_specs


def _create_test_fixtures(tmp_path: Path):
    """Create shared test fixtures with two test cases and global dimensions."""
    test_cases_dir = tmp_path / "test_cases"

    case1 = test_cases_dir / "single-checkbox"
    case1.mkdir(parents=True)
    (case1 / "prompt.yaml").write_text(
        "name: Single Checkbox\n"
        "base_prompt: |\n"
        "  Build a consent checkbox.\n"
        "common_requirements:\n"
        '  - Wrap the checkbox in a div with class "form-field".\n'
        "dimensions:\n"
        "  requirement:\n"
        "    label: Requirement\n"
        "    values:\n"
        "      required:\n"
        "        label: Required\n"
        "        prompt_fragment: Make the checkbox required.\n"
        "      optional:\n"
        "        label: Optional\n"
        "        prompt_fragment: Make the checkbox optional.\n",
        encoding="utf-8",
    )

    case2 = test_cases_dir / "modal-dialog"
    case2.mkdir(parents=True)
    (case2 / "prompt.yaml").write_text(
        "name: Modal Dialog\n"
        "base_prompt: |\n"
        "  Build a modal dialog.\n",
        encoding="utf-8",
    )

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "prompt_dimensions.yaml").write_text(
        "dimensions:\n"
        "  framework:\n"
        "    label: Framework\n"
        "    values:\n"
        "      vanilla-js:\n"
        "        label: Vanilla JS\n"
        "        prompt_fragment: Use vanilla JavaScript.\n"
        "      react:\n"
        "        label: React\n"
        "        prompt_fragment: Structure it like a React team would.\n",
        encoding="utf-8",
    )

    return test_cases_dir, config_dir / "prompt_dimensions.yaml"


def test_load_prompt_specs_expands_global_and_local_dimensions(tmp_path: Path):
    test_cases_dir, dimensions_file = _create_test_fixtures(tmp_path)

    prompt_spec_set = load_prompt_specs(test_cases_dir, dimensions_file)

    # single-checkbox has 2 global dims x 2 local dims = 4, modal-dialog has 2 global dims = 2
    assert len(prompt_spec_set.prompt_cases) == 6
    case_names = {case.test_name for case in prompt_spec_set.prompt_cases}
    assert "Single Checkbox | Vanilla JS | Required" in case_names
    assert "Single Checkbox | React | Optional" in case_names

    first_case = prompt_spec_set.prompt_cases[0]
    assert first_case.prompt_case_id == "modal-dialog--framework-vanilla-js"
    assert first_case.test_name == "Modal Dialog | Vanilla JS"
    assert first_case.base_test_name == "modal-dialog"
    assert "Build a modal dialog." in first_case.prompt_text
    assert "Use vanilla JavaScript." in first_case.prompt_text


def test_test_case_filter_selects_single_case(tmp_path: Path):
    test_cases_dir, dimensions_file = _create_test_fixtures(tmp_path)

    result = load_prompt_specs(test_cases_dir, dimensions_file, test_case_filter=["single-checkbox"])

    assert result.base_test_names == ["single-checkbox"]
    assert all(pc.base_test_name == "single-checkbox" for pc in result.prompt_cases)
    assert len(result.prompt_cases) == 4  # 2 frameworks x 2 requirements


def test_test_case_filter_selects_multiple_cases(tmp_path: Path):
    test_cases_dir, dimensions_file = _create_test_fixtures(tmp_path)

    result = load_prompt_specs(test_cases_dir, dimensions_file, test_case_filter=["single-checkbox", "modal-dialog"])

    assert set(result.base_test_names) == {"single-checkbox", "modal-dialog"}
    assert len(result.prompt_cases) == 6  # 4 + 2


def test_test_case_filter_none_returns_all(tmp_path: Path):
    test_cases_dir, dimensions_file = _create_test_fixtures(tmp_path)

    result = load_prompt_specs(test_cases_dir, dimensions_file, test_case_filter=None)

    assert set(result.base_test_names) == {"single-checkbox", "modal-dialog"}


def test_test_case_filter_unknown_name_raises(tmp_path: Path):
    test_cases_dir, dimensions_file = _create_test_fixtures(tmp_path)

    with pytest.raises(ValueError, match="Unknown test case.*nonexistent"):
        load_prompt_specs(test_cases_dir, dimensions_file, test_case_filter=["nonexistent"])