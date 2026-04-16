from pathlib import Path

from a11y_llm_tests.inspect_runtime import GenerationRequest, InspectGenerationRuntime


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