"""Smoke tests for the Copilot SDK runtime adapter.

These tests do not exercise the live Copilot CLI. They verify the
serialization helpers and the public ``CopilotRuntime`` surface, which is
sufficient to catch regressions in the adapter without requiring network or
the bundled CLI binary.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from a11y_llm_tests import copilot_runtime as cr


def test_serialize_session_event_dict():
    event = SimpleNamespace(type="assistant.message", data={"content": "<html></html>"})
    payload = cr._serialize_session_event(event)
    assert payload == {"type": "assistant.message", "data": {"content": "<html></html>"}}


def test_aggregate_usage_sums_prompt_and_completion_tokens():
    events = [
        {"type": "assistant.usage", "data": {"prompt_tokens": 10, "completion_tokens": 5}},
        {"type": "assistant.usage", "data": {"prompt_tokens": 7, "completion_tokens": 11, "total_tokens": 18}},
    ]
    usage = cr._aggregate_usage(events)
    assert usage["prompt_tokens"] == 17
    assert usage["completion_tokens"] == 16
    assert usage["total_tokens"] == 18


def test_aggregate_usage_returns_empty_when_no_usage_events():
    events = [{"type": "assistant.message", "data": {"content": "<html>"}}]
    assert cr._aggregate_usage(events) == {}


def test_last_assistant_message_picks_final_content():
    events = [
        {"type": "assistant.message", "data": {"content": "<p>first</p>"}},
        {"type": "assistant.message", "data": {"content": "<html>final</html>"}},
        {"type": "assistant.usage", "data": {}},
    ]
    assert cr._last_assistant_message(events) == "<html>final</html>"


def test_build_provider_payload_passthrough():
    cfg = {
        "type": "anthropic",
        "base_url": "https://api.example.com",
        "api_key": "sk-test",
    }
    payload = cr.CopilotRuntime._build_provider_payload(cfg)
    assert payload == {
        "type": "anthropic",
        "base_url": "https://api.example.com",
        "api_key": "sk-test",
    }


def test_build_provider_payload_returns_none_without_byok_signal():
    assert cr.CopilotRuntime._build_provider_payload({}) is None
    assert cr.CopilotRuntime._build_provider_payload({"batch": {"enabled": True}}) is None


def test_build_provider_payload_resolves_api_key_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY_TEST", "from-env")
    payload = cr.CopilotRuntime._build_provider_payload({
        "type": "anthropic",
        "api_key_env": "ANTHROPIC_API_KEY_TEST",
    })
    assert payload == {"type": "anthropic", "api_key": "from-env"}


def test_sandbox_label_is_docker():
    rt = cr.CopilotRuntime(workspace_dir="/tmp")
    assert rt.sandbox_label.startswith("docker:")
    assert rt.sandbox_label.endswith("compose.yaml")


def test_compose_up_uses_workspace_scoped_project_name(monkeypatch, tmp_path):
    rt = cr.CopilotRuntime(workspace_dir=str(tmp_path), container_identity_dir=str(tmp_path / "view-a"))

    calls = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[:3] == ["docker", "image", "inspect"]:
            return Result(returncode=0)
        if cmd[:3] == ["docker", "inspect", "-f"]:
            return Result(returncode=1)
        if cmd[:3] == ["docker", "rm", "-f"]:
            return Result(returncode=0)
        if cmd[:2] == ["docker", "compose"]:
            return Result(returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(cr.subprocess, "run", fake_run)
    monkeypatch.setattr(rt, "_compute_build_hash", lambda: "hash123")
    monkeypatch.setattr(rt, "_read_cached_hash", lambda: "hash123")
    monkeypatch.setattr(rt, "_write_cached_hash", lambda value: None)

    rt._compose_up()

    compose_calls = [cmd for cmd, _ in calls if cmd[:2] == ["docker", "compose"]]
    assert len(compose_calls) == 1
    assert compose_calls[0][2] == "-p"
    assert compose_calls[0][3] == rt._compose_project_name
    assert compose_calls[0][3] == rt._container_name


def test_compose_down_uses_workspace_scoped_project_name(monkeypatch, tmp_path):
    rt = cr.CopilotRuntime(workspace_dir=str(tmp_path), container_identity_dir=str(tmp_path / "view-a"))

    calls = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[:2] == ["docker", "compose"]:
            return Result(returncode=0)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(cr.subprocess, "run", fake_run)

    rt._compose_down()

    assert len(calls) == 1
    cmd = calls[0][0]
    assert cmd[:2] == ["docker", "compose"]
    assert cmd[2] == "-p"
    assert cmd[3] == rt._compose_project_name
    assert cmd[-2:] == ["down", "--remove-orphans"]


def test_host_path_to_container_translates_workspace_paths(tmp_path):
    rt = cr.CopilotRuntime(workspace_dir=str(tmp_path))
    skill = tmp_path / "config" / "skills" / "building-accessible-ui"
    skill.mkdir(parents=True)
    assert rt.host_path_to_container(str(skill)) == "/workspace/config/skills/building-accessible-ui"


def test_host_path_to_container_rejects_paths_outside_workspace(tmp_path):
    rt = cr.CopilotRuntime(workspace_dir=str(tmp_path))
    with pytest.raises(RuntimeError, match="outside the workspace"):
        rt.host_path_to_container("/etc/passwd")


def test_generate_skill_multi_turn_passes_skill_directories(tmp_path):
    class FakeSession:
        def __init__(self, on_event):
            self.session_id = "session-1"
            self._on_event = on_event
            self.sent_prompts = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, prompt):
            self.sent_prompts.append(prompt)
            self._on_event(SimpleNamespace(type="assistant.message", data={"content": "<html></html>"}))
            self._on_event(SimpleNamespace(type="session.idle", data={}))

    class FakeClient:
        def __init__(self):
            self.kwargs = None
            self.session = None

        async def create_session(self, **kwargs):
            self.kwargs = kwargs
            self.session = FakeSession(kwargs["on_event"])
            return self.session

    rt = cr.CopilotRuntime(workspace_dir=str(tmp_path))
    rt._client = FakeClient()

    skill_dir = tmp_path / "config" / "skills" / "building-accessible-ui"
    skill_dir.mkdir(parents=True)

    result = asyncio.run(rt.generate_skill_multi_turn(
        model="gpt-5-mini",
        rendered_turn_prompts=["build accessible UI"],
        skill_dir_abs_path=str(skill_dir),
        skill_id="building-accessible-ui",
        timeout_s=1.0,
    ))

    assert result.html == "<html></html>"
    assert rt._client.session.sent_prompts == ["build accessible UI"]
    assert rt._client.kwargs["skill_directories"] == ["/workspace/config/skills"]
    # Skills are injected via skill_directories; the SDK discovers SKILL.md
    # files in immediate subdirectories. No agent/custom_agents kwargs are set.
    assert "agent" not in rt._client.kwargs
    assert "custom_agents" not in rt._client.kwargs


def test_generate_skill_multi_turn_stops_at_max_turns(tmp_path):
    class FakeSession:
        def __init__(self, on_event):
            self.session_id = "session-guard-max-turns"
            self._on_event = on_event
            self.sent_prompts = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, prompt):
            self.sent_prompts.append(prompt)
            self._on_event(SimpleNamespace(type="assistant.message", data={"content": f"<html>{prompt}</html>"}))
            self._on_event(SimpleNamespace(type="assistant.usage", data={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}))
            self._on_event(SimpleNamespace(type="session.idle", data={}))

    class FakeClient:
        def __init__(self):
            self.session = None

        async def create_session(self, **kwargs):
            self.session = FakeSession(kwargs["on_event"])
            return self.session

    rt = cr.CopilotRuntime(workspace_dir=str(tmp_path))
    rt._client = FakeClient()

    skill_dir = tmp_path / "config" / "skills" / "building-accessible-ui"
    skill_dir.mkdir(parents=True)

    result = asyncio.run(rt.generate_skill_multi_turn(
        model="gpt-5-mini",
        rendered_turn_prompts=["turn-0", "turn-1"],
        skill_dir_abs_path=str(skill_dir),
        skill_id="building-accessible-ui",
        timeout_s=1.0,
        max_turns=1,
    ))

    assert rt._client.session.sent_prompts == ["turn-0"]
    assert result.limit_error == "max_turns_exceeded on turn 1 (session=session-guard-max-turns)"
    assert result.turns[1]["limit_error"] == result.limit_error
    assert result.turns[1]["transcript"]["skipped"] is True


def test_generate_skill_multi_turn_stops_when_token_budget_already_exceeded(tmp_path):
    class FakeSession:
        def __init__(self, on_event):
            self.session_id = "session-guard-token-budget"
            self._on_event = on_event
            self.sent_prompts = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, prompt):
            self.sent_prompts.append(prompt)
            self._on_event(SimpleNamespace(type="assistant.message", data={"content": f"<html>{prompt}</html>"}))
            self._on_event(SimpleNamespace(type="assistant.usage", data={"input_tokens": 9, "output_tokens": 3, "total_tokens": 12}))
            self._on_event(SimpleNamespace(type="session.idle", data={}))

    class FakeClient:
        def __init__(self):
            self.session = None

        async def create_session(self, **kwargs):
            self.session = FakeSession(kwargs["on_event"])
            return self.session

    rt = cr.CopilotRuntime(workspace_dir=str(tmp_path))
    rt._client = FakeClient()

    skill_dir = tmp_path / "config" / "skills" / "building-accessible-ui"
    skill_dir.mkdir(parents=True)

    result = asyncio.run(rt.generate_skill_multi_turn(
        model="gpt-5-mini",
        rendered_turn_prompts=["turn-0", "turn-1"],
        skill_dir_abs_path=str(skill_dir),
        skill_id="building-accessible-ui",
        timeout_s=1.0,
        max_cumulative_total_tokens=12,
    ))

    assert rt._client.session.sent_prompts == ["turn-0"]
    assert result.limit_error == "token_budget_exceeded on turn 1 (session=session-guard-token-budget)"
    assert result.turns[1]["limit_error"] == result.limit_error
    assert result.turns[1]["transcript"]["skipped"] is True


def test_generate_skill_multi_turn_detects_no_progress_from_unchanged_artifact(tmp_path):
    class FakeSession:
        def __init__(self, on_event):
            self.session_id = "session-guard-no-progress"
            self._on_event = on_event
            self.sent_prompts = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, prompt):
            self.sent_prompts.append(prompt)
            self._on_event(SimpleNamespace(type="assistant.message", data={"content": "<html>same</html>"}))
            self._on_event(SimpleNamespace(type="assistant.usage", data={"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}))
            self._on_event(SimpleNamespace(type="session.idle", data={}))

    class FakeClient:
        def __init__(self):
            self.session = None

        async def create_session(self, **kwargs):
            self.session = FakeSession(kwargs["on_event"])
            return self.session

    rt = cr.CopilotRuntime(workspace_dir=str(tmp_path))
    rt._client = FakeClient()

    skill_dir = tmp_path / "config" / "skills" / "building-accessible-ui"
    skill_dir.mkdir(parents=True)

    result = asyncio.run(rt.generate_skill_multi_turn(
        model="gpt-5-mini",
        rendered_turn_prompts=["turn-0", "turn-1"],
        skill_dir_abs_path=str(skill_dir),
        skill_id="building-accessible-ui",
        timeout_s=1.0,
        max_consecutive_no_progress_turns=1,
    ))

    assert rt._client.session.sent_prompts == ["turn-0", "turn-1"]
    assert result.limit_error == "no_progress on turn 1 (session=session-guard-no-progress)"
    assert result.turns[1]["limit_error"] == result.limit_error


def test_generate_skill_multi_turn_stops_for_intra_turn_no_progress(tmp_path):
    class FakeSession:
        def __init__(self, on_event):
            self.session_id = "session-intra-turn-no-progress"
            self._on_event = on_event
            self.sent_prompts = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, prompt):
            self.sent_prompts.append(prompt)
            for _ in range(3):
                self._on_event(SimpleNamespace(type="assistant.message", data={"content": ""}))
                self._on_event(SimpleNamespace(type="assistant.turn.end", data={"turn_id": "0"}))

    class FakeClient:
        def __init__(self):
            self.session = None

        async def create_session(self, **kwargs):
            self.session = FakeSession(kwargs["on_event"])
            return self.session

    rt = cr.CopilotRuntime(workspace_dir=str(tmp_path))
    rt._client = FakeClient()

    skill_dir = tmp_path / "config" / "skills" / "building-accessible-ui"
    skill_dir.mkdir(parents=True)
    workdir = tmp_path / "sandbox"
    workdir.mkdir()
    (workdir / "index.html").write_text("<html>same</html>", encoding="utf-8")

    result = asyncio.run(rt.generate_skill_multi_turn(
        model="gpt-5-mini",
        rendered_turn_prompts=["turn-0"],
        skill_dir_abs_path=str(skill_dir),
        skill_id="building-accessible-ui",
        timeout_s=1.0,
        max_intra_turn_no_progress_assistant_turns=3,
        working_directory=str(workdir),
    ))

    assert rt._client.session.sent_prompts == ["turn-0"]
    assert result.limit_error == (
        "intra_turn_no_progress on turn 0 "
        "(session=session-intra-turn-no-progress)"
    )
    assert result.turns[0]["limit_error"] == result.limit_error


def test_generate_skill_multi_turn_allows_intra_turn_progress_from_nonempty_messages(tmp_path):
    class FakeSession:
        def __init__(self, on_event):
            self.session_id = "session-intra-turn-progress"
            self._on_event = on_event
            self.sent_prompts = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, prompt):
            self.sent_prompts.append(prompt)
            for content in ["", "", "<html>progress</html>", "", ""]:
                self._on_event(SimpleNamespace(type="assistant.message", data={"content": content}))
                self._on_event(SimpleNamespace(type="assistant.turn.end", data={"turn_id": "0"}))
            self._on_event(SimpleNamespace(type="session.idle", data={}))

    class FakeClient:
        def __init__(self):
            self.session = None

        async def create_session(self, **kwargs):
            self.session = FakeSession(kwargs["on_event"])
            return self.session

    rt = cr.CopilotRuntime(workspace_dir=str(tmp_path))
    rt._client = FakeClient()

    skill_dir = tmp_path / "config" / "skills" / "building-accessible-ui"
    skill_dir.mkdir(parents=True)
    workdir = tmp_path / "sandbox"
    workdir.mkdir()

    result = asyncio.run(rt.generate_skill_multi_turn(
        model="gpt-5-mini",
        rendered_turn_prompts=["turn-0"],
        skill_dir_abs_path=str(skill_dir),
        skill_id="building-accessible-ui",
        timeout_s=1.0,
        max_intra_turn_no_progress_assistant_turns=3,
        working_directory=str(workdir),
    ))

    assert rt._client.session.sent_prompts == ["turn-0"]
    assert result.limit_error is None


def test_generate_skill_multi_turn_allows_intra_turn_progress_from_sibling_artifact_changes(tmp_path):
    class FakeSession:
        def __init__(self, on_event, workdir):
            self.session_id = "session-intra-turn-sibling-progress"
            self._on_event = on_event
            self._workdir = workdir
            self.sent_prompts = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, prompt):
            self.sent_prompts.append(prompt)
            for index in range(5):
                (self._workdir / "styles.css").write_text(f"body {{ color: #{index}{index}{index}; }}", encoding="utf-8")
                self._on_event(SimpleNamespace(type="assistant.message", data={"content": ""}))
                self._on_event(SimpleNamespace(type="assistant.turn.end", data={"turn_id": str(index)}))
            self._on_event(SimpleNamespace(type="session.idle", data={}))

    class FakeClient:
        def __init__(self, workdir):
            self.session = None
            self._workdir = workdir

        async def create_session(self, **kwargs):
            self.session = FakeSession(kwargs["on_event"], self._workdir)
            return self.session

    workdir = tmp_path / "sandbox"
    workdir.mkdir()
    (workdir / "index.html").write_text("<html>same</html>", encoding="utf-8")

    rt = cr.CopilotRuntime(workspace_dir=str(tmp_path))
    rt._client = FakeClient(workdir)

    skill_dir = tmp_path / "config" / "skills" / "building-accessible-ui"
    skill_dir.mkdir(parents=True)

    result = asyncio.run(rt.generate_skill_multi_turn(
        model="gpt-5-mini",
        rendered_turn_prompts=["turn-0"],
        skill_dir_abs_path=str(skill_dir),
        skill_id="building-accessible-ui",
        timeout_s=1.0,
        max_intra_turn_no_progress_assistant_turns=3,
        working_directory=str(workdir),
    ))

    assert rt._client.session.sent_prompts == ["turn-0"]
    assert result.limit_error is None


def test_generate_skill_multi_turn_ignores_transient_files_for_intra_turn_progress(tmp_path):
    class FakeSession:
        def __init__(self, on_event, workdir):
            self.session_id = "session-intra-turn-transient-files"
            self._on_event = on_event
            self._workdir = workdir
            self.sent_prompts = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def send(self, prompt):
            self.sent_prompts.append(prompt)
            for index in range(3):
                (self._workdir / "out.json").write_text(f'{{"run": {index}}}', encoding="utf-8")
                self._on_event(SimpleNamespace(type="assistant.message", data={"content": ""}))
                self._on_event(SimpleNamespace(type="assistant.turn.end", data={"turn_id": str(index)}))

    class FakeClient:
        def __init__(self, workdir):
            self.session = None
            self._workdir = workdir

        async def create_session(self, **kwargs):
            self.session = FakeSession(kwargs["on_event"], self._workdir)
            return self.session

    workdir = tmp_path / "sandbox"
    workdir.mkdir()
    (workdir / "index.html").write_text("<html>same</html>", encoding="utf-8")

    rt = cr.CopilotRuntime(workspace_dir=str(tmp_path))
    rt._client = FakeClient(workdir)

    skill_dir = tmp_path / "config" / "skills" / "building-accessible-ui"
    skill_dir.mkdir(parents=True)

    result = asyncio.run(rt.generate_skill_multi_turn(
        model="gpt-5-mini",
        rendered_turn_prompts=["turn-0"],
        skill_dir_abs_path=str(skill_dir),
        skill_id="building-accessible-ui",
        timeout_s=1.0,
        max_intra_turn_no_progress_assistant_turns=3,
        working_directory=str(workdir),
    ))

    assert rt._client.session.sent_prompts == ["turn-0"]
    assert result.limit_error == (
        "intra_turn_no_progress on turn 0 "
        "(session=session-intra-turn-transient-files)"
    )
