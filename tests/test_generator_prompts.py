import pytest

from a11y_llm_tests import generator


@pytest.fixture(autouse=True)
def reset_prompts():
    generator.configure_prompts(None, None)
    yield
    generator.configure_prompts(None, None)


def test_compute_prompt_hash_changes_with_output_format_instructions():
    baseline = generator.compute_prompt_hash("Prompt body")
    generator.configure_prompts("Revised output-format instructions", None)
    changed = generator.compute_prompt_hash("Prompt body")
    assert baseline != changed


def test_hash_changes_with_custom_instructions():
    generator.configure_prompts(None, "Alpha instructions")
    first = generator.compute_prompt_hash("Prompt body")
    generator.configure_prompts(None, "Beta instructions")
    second = generator.compute_prompt_hash("Prompt body")
    assert first != second


def test_effective_output_format_instructions_includes_custom_instructions():
    # Retained for results.json provenance even though the runtime no
    # longer concatenates these into the user prompt.
    generator.configure_prompts("Base instructions", "### Custom\n- Item")
    effective = generator.get_effective_output_format_instructions()
    assert "Base instructions" in effective
    assert "### Custom" in effective


def test_materialize_custom_instructions_writes_copilot_instructions_file(tmp_path):
    workdir = tmp_path / "sandbox"
    workdir.mkdir()
    text = "### Custom\n- Always use semantic HTML"
    written = generator.materialize_custom_instructions_file(str(workdir), text)

    target = workdir / ".github" / "copilot-instructions.md"
    assert written == str(target)
    assert target.is_file()
    assert "Always use semantic HTML" in target.read_text(encoding="utf-8")


def test_materialize_custom_instructions_removes_stale_file(tmp_path):
    workdir = tmp_path / "sandbox"
    workdir.mkdir()
    target = workdir / ".github" / "copilot-instructions.md"
    target.parent.mkdir(parents=True)
    target.write_text("stale content", encoding="utf-8")

    written = generator.materialize_custom_instructions_file(str(workdir), None)
    assert written is None
    assert not target.exists()


def test_materialize_custom_instructions_noop_without_workdir():
    assert generator.materialize_custom_instructions_file(None, "anything") is None
    assert generator.materialize_custom_instructions_file("", "anything") is None
