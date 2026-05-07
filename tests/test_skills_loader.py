"""Unit tests for skill loading and per-turn cache identity.

These tests avoid running the full CLI/generator and focus on the
validation surface of ``_load_skills`` plus the helpers in
``a11y_llm_tests.generator`` that the skill code path relies on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from a11y_llm_tests import cli as cli_module
from a11y_llm_tests import generator as gen_module


def _write_skill_dir(root: Path, sid: str = "demo", with_skill_md: bool = True) -> Path:
    sdir = root / "skills" / sid
    sdir.mkdir(parents=True, exist_ok=True)
    if with_skill_md:
        (sdir / "SKILL.md").write_text("# demo skill\n", encoding="utf-8")
    return sdir


def _write_skills_yaml(root: Path, payload: dict) -> Path:
    f = root / "skills.yaml"
    f.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return f


def test_load_skills_success(tmp_path: Path):
    _write_skill_dir(tmp_path, "demo")
    f = _write_skills_yaml(tmp_path, {
        "skills": [{
            "id": "demo",
            "name": "Demo",
            "skill_dir": "skills/demo",
            "turns": [
                {"id": "generate", "prompt": "{{test_case_prompt}}"},
                {"id": "review", "prompt": "review using {{skill_path}}"},
            ],
        }]
    })
    skills = cli_module._load_skills(str(f), tmp_path)
    assert len(skills) == 1
    s = skills[0]
    assert s["id"] == "demo"
    assert Path(s["skill_dir_abs_path"]) == tmp_path / "skills" / "demo"
    assert len(s["turns"]) == 2
    assert s["turns"][0]["id"] == "generate"
    assert s["generation_mode"] == "copilot_agent"
    assert s["skill_files_hash"]  # non-empty


def test_load_skills_requires_turns(tmp_path: Path):
    _write_skill_dir(tmp_path)
    f = _write_skills_yaml(tmp_path, {
        "skills": [{"id": "demo", "skill_dir": "skills/demo", "turns": []}]
    })
    with pytest.raises(ValueError, match="non-empty 'turns'"):
        cli_module._load_skills(str(f), tmp_path)


def test_load_skills_requires_exactly_one_test_case_prompt_token(tmp_path: Path):
    _write_skill_dir(tmp_path)
    # Zero occurrences -> error.
    f = _write_skills_yaml(tmp_path, {
        "skills": [{
            "id": "demo",
            "skill_dir": "skills/demo",
            "turns": [{"id": "t1", "prompt": "no token here"}],
        }]
    })
    with pytest.raises(ValueError, match="test_case_prompt"):
        cli_module._load_skills(str(f), tmp_path)

    # Two occurrences -> error.
    f = _write_skills_yaml(tmp_path, {
        "skills": [{
            "id": "demo",
            "skill_dir": "skills/demo",
            "turns": [
                {"id": "t1", "prompt": "{{test_case_prompt}}"},
                {"id": "t2", "prompt": "{{test_case_prompt}} again"},
            ],
        }]
    })
    with pytest.raises(ValueError, match="test_case_prompt"):
        cli_module._load_skills(str(f), tmp_path)


def test_load_skills_rejects_reserved_and_duplicate_ids(tmp_path: Path):
    _write_skill_dir(tmp_path)
    f = _write_skills_yaml(tmp_path, {
        "skills": [{
            "id": "control",
            "skill_dir": "skills/demo",
            "turns": [{"id": "t1", "prompt": "{{test_case_prompt}}"}],
        }]
    })
    with pytest.raises(ValueError, match="reserved"):
        cli_module._load_skills(str(f), tmp_path)

    f = _write_skills_yaml(tmp_path, {
        "skills": [{
            "id": "demo",
            "skill_dir": "skills/demo",
            "turns": [{"id": "t1", "prompt": "{{test_case_prompt}}"}],
        }]
    })
    with pytest.raises(ValueError, match="Duplicate variant id"):
        cli_module._load_skills(str(f), tmp_path, existing_ids={"demo"})


def test_load_skills_rejects_generation_mode(tmp_path: Path):
    _write_skill_dir(tmp_path)
    f = _write_skills_yaml(tmp_path, {
        "skills": [{
            "id": "demo",
            "skill_dir": "skills/demo",
            "generation_mode": "direct",
            "turns": [{"id": "t1", "prompt": "{{test_case_prompt}}"}],
        }]
    })
    with pytest.raises(ValueError, match="generation_mode"):
        cli_module._load_skills(str(f), tmp_path)


def test_load_skills_requires_skill_md(tmp_path: Path):
    _write_skill_dir(tmp_path, with_skill_md=False)
    f = _write_skills_yaml(tmp_path, {
        "skills": [{
            "id": "demo",
            "skill_dir": "skills/demo",
            "turns": [{"id": "t1", "prompt": "{{test_case_prompt}}"}],
        }]
    })
    with pytest.raises(FileNotFoundError, match="SKILL.md"):
        cli_module._load_skills(str(f), tmp_path)


def test_hash_skill_files_changes_when_content_changes(tmp_path: Path):
    sdir = _write_skill_dir(tmp_path)
    h1 = cli_module._hash_skill_files(sdir)
    (sdir / "SKILL.md").write_text("# updated\n", encoding="utf-8")
    h2 = cli_module._hash_skill_files(sdir)
    assert h1 != h2


def test_render_skill_turn_prompt_substitutes_tokens():
    rendered = gen_module.render_skill_turn_prompt(
        "Use {{skill_id}} at {{skill_path}} on {{test_case_prompt}} prev={{previous_submission}}",
        test_case_prompt="PROMPT",
        skill_id="demo",
        skill_path="/workspace/.skills/demo",
        previous_submission="<html/>",
    )
    assert "demo" in rendered
    assert "/workspace/.skills/demo" in rendered
    assert "PROMPT" in rendered
    assert "<html/>" in rendered
    assert "{{" not in rendered


def test_skill_turn_cache_file_identity_distinguishes_turns(tmp_path: Path, monkeypatch):
    # Each turn must get its own cache path, and changing a later turn's prompt
    # must not disturb an earlier turn's cache key.
    monkeypatch.setattr(gen_module, "CACHE_DIR", tmp_path)

    path_t0_a, _ = gen_module._skill_turn_cache_file(
        model="m", prompt_hash_value="ph", iteration=0, seed=0,
        skill_id="demo", skill_files_hash="sh", turn_index=0,
        cumulative_turn_hash="hash_t0",
    )
    path_t1_a, _ = gen_module._skill_turn_cache_file(
        model="m", prompt_hash_value="ph", iteration=0, seed=0,
        skill_id="demo", skill_files_hash="sh", turn_index=1,
        cumulative_turn_hash="hash_t0_plus_t1_a",
    )
    path_t1_b, _ = gen_module._skill_turn_cache_file(
        model="m", prompt_hash_value="ph", iteration=0, seed=0,
        skill_id="demo", skill_files_hash="sh", turn_index=1,
        cumulative_turn_hash="hash_t0_plus_t1_b",
    )
    # turn 0 and turn 1 differ.
    assert path_t0_a != path_t1_a
    # changing turn 1's cumulative hash changes turn 1's path but not turn 0's.
    assert path_t1_a != path_t1_b
