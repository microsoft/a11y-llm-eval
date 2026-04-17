from pathlib import Path
from types import SimpleNamespace

from a11y_llm_tests.inspect_runtime import (
    GenerationRequest,
    InspectGenerationRuntime,
    _extract_agent_html,
    _resolve_attachment_refs,
    extract_agent_html_from_transcript,
    normalize_agent_transcript,
)


class _FakeUsage:
    input_tokens = 1
    output_tokens = 2
    total_tokens = 3
    total_cost = 0.01


class _FakeOutput:
    completion = "<html><body>ok</body></html>"
    usage = _FakeUsage()
    stop_reason = "stop"


def test_runtime_generate_shapes_request(monkeypatch):
    runtime = InspectGenerationRuntime()
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        from a11y_llm_tests.inspect_runtime import InspectCompletionResponse

        return InspectCompletionResponse("<html><body>ok</body></html>", usage={"prompt_tokens": 1}, stop_reason="stop")

    monkeypatch.setattr(runtime, "completion", fake_completion)

    runtime.generate(
        GenerationRequest(
            model="openai/test-model",
            messages=[{"role": "user", "content": "Prompt"}],
            seed=123,
            temperature=0.2,
            max_tokens=456,
            api_base="https://example.test",
            api_version="2024-10-21",
        )
    )

    assert captured["model"] == "openai/test-model"
    assert captured["seed"] == 123
    assert captured["temperature"] == 0.2
    assert captured["max_tokens"] == 456
    assert captured["api_base"] == "https://example.test"
    assert captured["api_version"] == "2024-10-21"


def test_runtime_generate_omits_none_seed(monkeypatch):
    runtime = InspectGenerationRuntime()
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        from a11y_llm_tests.inspect_runtime import InspectCompletionResponse

        return InspectCompletionResponse("<html><body>ok</body></html>", usage={"prompt_tokens": 1}, stop_reason="stop")

    monkeypatch.setattr(runtime, "completion", fake_completion)

    runtime.generate(
        GenerationRequest(
            model="openai/azure/gpt-5.4-mini",
            messages=[{"role": "user", "content": "Prompt"}],
            seed=None,
        )
    )

    assert "seed" not in captured


def test_runtime_converts_dict_messages_to_inspect_chat_messages(monkeypatch):
    runtime = InspectGenerationRuntime()

    class _FakeGenerateConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _FakeChatMessageSystem:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _FakeChatMessageUser:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _FakeChatMessageAssistant:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _FakeChatMessageTool:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    captured = {}

    class _FakeModel:
        async def generate(self, messages, config=None, cache=False):
            captured["messages"] = messages
            return _FakeOutput()

    monkeypatch.setattr(runtime, "_import_generate_config", lambda: _FakeGenerateConfig)
    monkeypatch.setattr(
        runtime,
        "_import_chat_message_types",
        lambda: (
            _FakeChatMessageSystem,
            _FakeChatMessageUser,
            _FakeChatMessageAssistant,
            _FakeChatMessageTool,
        ),
    )
    monkeypatch.setattr(runtime, "_get_model", lambda model_name, **kwargs: _FakeModel())

    response = runtime.completion(
        model="azureai/test-model",
        messages=[
            {"role": "system", "content": "System"},
            {"role": "user", "content": "Prompt"},
        ],
    )

    assert response.usage["total_tokens"] == 3
    assert len(captured["messages"]) == 2
    assert isinstance(captured["messages"][0], _FakeChatMessageSystem)
    assert isinstance(captured["messages"][1], _FakeChatMessageUser)
    assert captured["messages"][0].content == "System"
    assert captured["messages"][1].content == "Prompt"


def test_runtime_writes_jsonl_logs(monkeypatch, tmp_path):
    runtime = InspectGenerationRuntime()
    runtime.set_log_dir(tmp_path)

    class _FakeGenerateConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _FakeModel:
        async def generate(self, messages, config=None, cache=False):
            return _FakeOutput()

    monkeypatch.setattr(runtime, "_import_generate_config", lambda: _FakeGenerateConfig)
    monkeypatch.setattr(runtime, "_get_model", lambda model_name, **kwargs: _FakeModel())

    response = runtime.completion(model="openai/test-model", messages=[{"role": "user", "content": "Prompt"}])
    assert response.usage["total_tokens"] == 3

    logs = list(Path(tmp_path).glob("generation-*.jsonl"))
    assert logs


def test_extract_agent_html_uses_submit_attachment_when_completion_is_truncated():
    html = "<html><body><h1>resolved</h1></body></html>"
    truncated = (
        "The output of your call to submit was too long to be displayed.\n"
        "Here is a truncated version:\n<START_TOOL_OUTPUT>"
    )

    class _FakeOutput:
        def __init__(self):
            self.completion = "attachment://preview"
            self.model = "gpt-5.4-mini"
            self.choices = [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": "submit",
                                "arguments": {"answer": "attachment://final-html"},
                            }
                        ]
                    },
                    "stop_reason": "tool_calls",
                }
            ]

        def model_dump(self, mode="json"):
            return {
                "completion": "attachment://preview",
                "model": self.model,
                "choices": self.choices,
            }

    sample = SimpleNamespace(
        output=_FakeOutput(),
        attachments={
            "preview": truncated,
            "final-html": html,
            "final-answer": html,
        },
        messages=[
            {
                "role": "assistant",
                "content": [
                    {
                        "internal": {"message_phase": "final_answer"},
                        "type": "text",
                        "text": "attachment://final-answer",
                    }
                ],
                "tool_calls": [
                    {
                        "function": "submit",
                        "arguments": {"answer": "attachment://final-html"},
                    }
                ],
            }
        ],
        events=[],
        model_usage={"default": _FakeUsage()},
        limit=None,
        error=None,
    )
    assert _extract_agent_html(sample) == html


def test_extract_agent_html_uses_submit_attachment_from_events_when_messages_do_not_include_submit():
    html = "<html><body><h1>resolved</h1></body></html>"
    truncated = (
        "The output of your call to submit was too long to be displayed.\n"
        "Here is a truncated version:\n<START_TOOL_OUTPUT>"
    )

    sample = SimpleNamespace(
        output=SimpleNamespace(completion=truncated),
        attachments={"final-html": html},
        messages=[
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "commentary only"}],
                "tool_calls": [],
            }
        ],
        events=[
            {
                "event": "tool",
                "function": "submit",
                "arguments": {"answer": "attachment://final-html"},
            }
        ],
    )

    assert _extract_agent_html(sample) == html


def test_resolve_attachment_refs_replaces_attachment_strings_recursively():
    html = "<html><body><h1>resolved</h1></body></html>"
    value = {
        "output": {"completion": "attachment://final-html"},
        "messages": [
            {
                "content": [
                    {"type": "text", "text": "attachment://final-html"},
                ]
            }
        ],
    }

    resolved = _resolve_attachment_refs(value, {"final-html": html})

    assert resolved["output"]["completion"] == html
    assert resolved["messages"][0]["content"][0]["text"] == html


def test_normalize_agent_transcript_replaces_truncated_preview_in_messages_and_output():
    html = "<html><body><h1>resolved</h1></body></html>"
    truncated = (
        "The output of your call to submit was too long to be displayed.\n"
        "Here is a truncated version:\n<START_TOOL_OUTPUT>"
    )
    transcript = {
        "messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "draft commentary"},
                    {"type": "text", "text": truncated},
                ],
            }
        ],
        "output": {
            "completion": truncated,
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": truncated},
                        ]
                    }
                }
            ],
        },
    }

    normalized = normalize_agent_transcript(transcript, html)

    assert normalized["messages"][0]["content"][1]["text"] == html
    assert normalized["output"]["completion"] == html
    assert normalized["output"]["choices"][0]["message"]["content"][0]["text"] == html


def test_extract_agent_html_from_transcript_prefers_submit_answer():
    html = "<html><body><h1>resolved</h1></body></html>"
    transcript = {
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "function": "submit",
                        "arguments": {"answer": html},
                    }
                ],
                "content": [
                    {"type": "text", "text": "commentary"},
                    {
                        "type": "text",
                        "text": "The output of your call to submit was too long to be displayed.\nHere is a truncated version:\n<START_TOOL_OUTPUT>",
                    },
                ],
            }
        ],
        "output": {"completion": "broken preview"},
    }

    assert extract_agent_html_from_transcript(transcript) == html


def test_extract_agent_html_from_transcript_uses_submit_event_when_present():
    html = "<html><body><h1>resolved</h1></body></html>"
    transcript = {
        "messages": [{"role": "assistant", "content": [{"type": "text", "text": "commentary"}]}],
        "events": [
            {
                "event": "tool",
                "function": "submit",
                "arguments": {"answer": html},
            }
        ],
        "output": {
            "completion": "The output of your call to submit was too long to be displayed.",
        },
    }

    assert extract_agent_html_from_transcript(transcript) == html


def test_extract_agent_html_from_transcript_preserves_doctype():
    html = "<!DOCTYPE html>\n<html><body><h1>resolved</h1></body></html>"
    transcript = {
        "events": [
            {
                "event": "tool",
                "function": "submit",
                "arguments": {"answer": html},
            }
        ],
        "output": {
            "completion": "The output of your call to submit was too long to be displayed.",
        },
    }

    assert extract_agent_html_from_transcript(transcript) == html