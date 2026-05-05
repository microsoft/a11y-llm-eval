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
