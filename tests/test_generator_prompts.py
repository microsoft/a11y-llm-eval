import pytest

from a11y_llm_tests import generator


@pytest.fixture(autouse=True)
def reset_prompts():
    generator.configure_prompts(None, None)
    yield
    generator.configure_prompts(None, None)


def test_compute_prompt_hash_changes_with_system_prompt():
    baseline = generator.compute_prompt_hash("Prompt body")
    generator.configure_prompts("Revised system prompt", None)
    changed = generator.compute_prompt_hash("Prompt body")
    assert baseline != changed


def test_hash_changes_with_custom_instructions():
    generator.configure_prompts(None, "Alpha instructions")
    first = generator.compute_prompt_hash("Prompt body")
    generator.configure_prompts(None, "Beta instructions")
    second = generator.compute_prompt_hash("Prompt body")
    assert first != second


def test_effective_system_prompt_includes_custom_instructions():
    generator.configure_prompts("Base prompt", "### Custom\n- Item")
    effective = generator.get_effective_system_prompt()
    assert "Base prompt" in effective
    assert "### Custom" in effective
