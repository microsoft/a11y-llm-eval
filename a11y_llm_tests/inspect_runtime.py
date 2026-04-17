"""Inspect AI-backed generation runtime."""
from __future__ import annotations

import asyncio
import copy
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


ATTACHMENT_PROTOCOL = "attachment://"
TRUNCATED_TOOL_OUTPUT_MARKER = "The output of your call to submit was too long to be displayed."


@dataclass
class _CompatMessage:
    content: str


@dataclass
class _CompatChoice:
    message: _CompatMessage
    finish_reason: Optional[str] = None
    stop_reason: Optional[str] = None


class InspectCompletionResponse:
    """Minimal response wrapper compatible with existing generator code."""

    def __init__(self, content: str, *, usage: Optional[dict[str, Any]], stop_reason: Optional[str]):
        finish_reason = None
        if stop_reason in {"max_tokens", "model_length"}:
            finish_reason = "length"
        elif stop_reason is not None:
            finish_reason = "stop"

        self.choices = [
            _CompatChoice(
                message=_CompatMessage(content=content),
                finish_reason=finish_reason,
                stop_reason=stop_reason,
            )
        ]
        self.usage = usage or {}
        self.response_cost = (usage or {}).get("total_cost")
        self._hidden_params: dict[str, Any] = {}
        self.completion = content
        self.stop_reason = stop_reason


@dataclass
class GenerationRequest:
    model: str
    messages: Any
    seed: Optional[int] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    api_base: Optional[str] = None
    api_version: Optional[str] = None
    azure_ad_token_provider: Any = None
    max_workers: Optional[int] = None


@dataclass
class AgentGenerationResult:
    html: str
    transcript: dict[str, Any]
    usage: dict[str, Any]
    elapsed_s: float
    sandbox: Optional[str]
    limit_error: Optional[str] = None
    eval_log_path: Optional[str] = None


class InspectGenerationRuntime:
    """Provide generation helpers over Inspect AI for the harness."""

    def __init__(self) -> None:
        self.drop_params = True
        self._log_dir: Optional[Path] = None

    def supports_batch_generation(self) -> bool:
        return True

    def set_log_dir(self, log_dir: str | Path | None) -> None:
        if log_dir is None:
            self._log_dir = None
            return
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        self._log_dir = path

    def generate(self, request: GenerationRequest) -> InspectCompletionResponse:
        return self.completion(**self._request_to_kwargs(request))

    def generate_batch(self, requests: list[GenerationRequest]) -> list[InspectCompletionResponse | Exception]:
        if not requests:
            return []
        first = requests[0]
        kwargs = self._request_to_kwargs(first)
        kwargs["messages"] = [request.messages for request in requests]
        kwargs["max_workers"] = first.max_workers or len(requests)
        return self.batch_completion(**kwargs)

    def completion(self, **kwargs: Any) -> InspectCompletionResponse:
        return asyncio.run(self._acompletion(**kwargs))

    def batch_completion(self, **kwargs: Any) -> list[InspectCompletionResponse | Exception]:
        return asyncio.run(self._abatch_completion(**kwargs))

    async def _acompletion(self, **kwargs: Any) -> InspectCompletionResponse:
        started = time.time()
        log_payload = self._log_request_payload("single", kwargs)
        model_name = kwargs.pop("model")
        messages = self._normalize_messages(kwargs.pop("messages"))
        config, get_model_kwargs = self._split_model_kwargs(kwargs)

        try:
            inspect_model = self._get_model(model_name, config=config, **get_model_kwargs)
            output = await inspect_model.generate(messages, config=config, cache=False)
            response = self._wrap_output(output)
            self._write_log_event(log_payload, response=response, elapsed=time.time() - started)
            return response
        except Exception as exc:
            self._write_log_event(log_payload, error=exc, elapsed=time.time() - started)
            raise

    async def _abatch_completion(self, **kwargs: Any) -> list[InspectCompletionResponse | Exception]:
        started = time.time()
        log_payload = self._log_request_payload("batch", kwargs)
        model_name = kwargs.pop("model")
        batch_messages = [self._normalize_messages(messages) for messages in kwargs.pop("messages")]
        max_workers = int(kwargs.pop("max_workers", 0) or 0)
        config, get_model_kwargs = self._split_model_kwargs(kwargs)
        inspect_model = self._get_model(model_name, config=config, **get_model_kwargs)

        semaphore = asyncio.Semaphore(max_workers) if max_workers > 0 else None

        async def _run_one(messages: Any) -> InspectCompletionResponse | Exception:
            try:
                if semaphore is not None:
                    async with semaphore:
                        output = await inspect_model.generate(messages, config=config, cache=False)
                else:
                    output = await inspect_model.generate(messages, config=config, cache=False)
                return self._wrap_output(output)
            except Exception as exc:
                return exc

        responses = await asyncio.gather(*[_run_one(messages) for messages in batch_messages])
        self._write_log_event(log_payload, batch_responses=responses, elapsed=time.time() - started)
        return responses

    def _request_to_kwargs(self, request: GenerationRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
        }
        if request.seed is not None:
            kwargs["seed"] = request.seed
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens
        if request.api_base is not None:
            kwargs["api_base"] = request.api_base
        if request.api_version is not None:
            kwargs["api_version"] = request.api_version
        if request.azure_ad_token_provider is not None:
            kwargs["azure_ad_token_provider"] = request.azure_ad_token_provider
        if request.max_workers is not None:
            kwargs["max_workers"] = request.max_workers
        return kwargs

    def _normalize_messages(self, messages: Any) -> Any:
        if not isinstance(messages, list):
            return messages
        return [self._normalize_message(message) for message in messages]

    def _normalize_message(self, message: Any) -> Any:
        if not isinstance(message, dict):
            return message

        role = str(message.get("role") or "").strip().lower()
        content = message.get("content", "")
        metadata = message.get("metadata")

        ChatMessageSystem, ChatMessageUser, ChatMessageAssistant, ChatMessageTool = self._import_chat_message_types()

        if role == "system":
            return ChatMessageSystem(content=content, metadata=metadata)
        if role == "user":
            return ChatMessageUser(
                content=content,
                metadata=metadata,
                tool_call_id=message.get("tool_call_id"),
            )
        if role == "assistant":
            return ChatMessageAssistant(
                content=content,
                metadata=metadata,
                tool_calls=message.get("tool_calls"),
                model=message.get("model"),
            )
        if role == "tool":
            return ChatMessageTool(
                content=content,
                metadata=metadata,
                tool_call_id=message.get("tool_call_id"),
                function=message.get("function"),
                error=message.get("error"),
            )
        return message

    def _wrap_output(self, output: Any) -> InspectCompletionResponse:
        completion = getattr(output, "completion", None)
        if completion is None:
            completion = ""
        usage = self._extract_usage(output)
        stop_reason = getattr(output, "stop_reason", None)
        return InspectCompletionResponse(str(completion), usage=usage, stop_reason=stop_reason)

    def _extract_usage(self, output: Any) -> dict[str, Any]:
        usage_obj = getattr(output, "usage", None)
        if usage_obj is None:
            return {}
        if isinstance(usage_obj, dict):
            return usage_obj
        return {
            "prompt_tokens": getattr(usage_obj, "input_tokens", None),
            "completion_tokens": getattr(usage_obj, "output_tokens", None),
            "total_tokens": getattr(usage_obj, "total_tokens", None),
            "total_cost": getattr(usage_obj, "total_cost", None),
        }

    def _log_request_payload(self, event_type: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        messages = kwargs.get("messages")
        if isinstance(messages, list) and messages and isinstance(messages[0], list):
            sample_count = len(messages)
        else:
            sample_count = 1
        return {
            "event_type": event_type,
            "model": kwargs.get("model"),
            "seed": kwargs.get("seed"),
            "temperature": kwargs.get("temperature"),
            "max_tokens": kwargs.get("max_tokens"),
            "sample_count": sample_count,
        }

    def _write_log_event(
        self,
        payload: dict[str, Any],
        *,
        response: InspectCompletionResponse | None = None,
        batch_responses: list[InspectCompletionResponse | Exception] | None = None,
        error: Exception | None = None,
        elapsed: float,
    ) -> None:
        if self._log_dir is None:
            return
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pid": os.getpid(),
            "elapsed_s": elapsed,
            **payload,
        }
        if response is not None:
            record["status"] = "ok"
            record["usage"] = response.usage
            record["stop_reason"] = getattr(response.choices[0], "stop_reason", None)
        elif batch_responses is not None:
            record["status"] = "ok"
            record["batch_results"] = [
                {
                    "ok": not isinstance(item, Exception),
                    "usage": None if isinstance(item, Exception) else item.usage,
                    "error": None if not isinstance(item, Exception) else str(item),
                }
                for item in batch_responses
            ]
        elif error is not None:
            record["status"] = "error"
            record["error"] = str(error)

        try:
            path = self._log_dir / f"generation-{os.getpid()}.jsonl"
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        except Exception:
            pass

    def _split_model_kwargs(self, kwargs: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
        GenerateConfig = self._import_generate_config()

        config_kwargs = {}
        for key in (
            "max_retries",
            "timeout",
            "attempt_timeout",
            "max_connections",
            "system_message",
            "max_tokens",
            "top_p",
            "temperature",
            "stop_seqs",
            "best_of",
            "frequency_penalty",
            "presence_penalty",
            "logit_bias",
            "seed",
            "top_k",
            "num_choices",
            "logprobs",
            "top_logprobs",
            "parallel_tool_calls",
            "internal_tools",
            "max_tool_output",
            "cache_prompt",
            "verbosity",
            "effort",
            "reasoning_effort",
            "reasoning_tokens",
            "reasoning_summary",
            "reasoning_history",
            "response_schema",
            "extra_headers",
            "extra_body",
            "modalities",
            "cache",
            "batch",
        ):
            if key in kwargs and kwargs[key] is not None:
                config_kwargs[key] = kwargs.pop(key)

        config = GenerateConfig(**config_kwargs)

        get_model_kwargs: dict[str, Any] = {}
        api_base = kwargs.pop("api_base", None)
        if api_base is not None:
            get_model_kwargs["base_url"] = api_base
        api_key = kwargs.pop("api_key", None)
        if api_key is not None:
            get_model_kwargs["api_key"] = api_key
        if kwargs:
            get_model_kwargs.update(kwargs)
        return config, get_model_kwargs

    def _get_model(self, model_name: str, **kwargs: Any) -> Any:
        try:
            from inspect_ai.model import get_model
        except ImportError as exc:
            raise RuntimeError(
                "inspect-ai is required for generation. Install it with 'pip install inspect-ai'."
            ) from exc

        return get_model(model_name, **kwargs)

    def _import_generate_config(self) -> Any:
        try:
            from inspect_ai.model import GenerateConfig
        except ImportError as exc:
            raise RuntimeError(
                "inspect-ai is required for generation. Install it with 'pip install inspect-ai'."
            ) from exc

        return GenerateConfig

    def _import_chat_message_types(self) -> tuple[Any, Any, Any, Any]:
        try:
            from inspect_ai.model import (
                ChatMessageAssistant,
                ChatMessageSystem,
                ChatMessageTool,
                ChatMessageUser,
            )
        except ImportError as exc:
            raise RuntimeError(
                "inspect-ai is required for generation. Install it with 'pip install inspect-ai'."
            ) from exc

        return ChatMessageSystem, ChatMessageUser, ChatMessageAssistant, ChatMessageTool


def default_agent_limits() -> dict[str, Any]:
    return {
        "message_limit": 50,
        "token_limit": 120000,
        "time_limit": 600,
        "working_limit": 420,
        "max_output_tokens": 16000,
        "attempts": 1,
    }


def normalize_agent_limits(agent_limits: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    limits_cfg = {
        k: v
        for k, v in default_agent_limits().items()
        if k != "cost_limit" and v is not None
    }

    if agent_limits:
        provided_limits = {k: v for k, v in agent_limits.items() if v is not None}
        limits_cfg.update({k: v for k, v in provided_limits.items() if k != "cost_limit"})
        if "cost_limit" in provided_limits:
            limits_cfg["cost_limit"] = provided_limits["cost_limit"]

    return limits_cfg


def _maybe_resolve_attachment(value: Any, attachments: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith(ATTACHMENT_PROTOCOL):
        return attachments.get(value[len(ATTACHMENT_PROTOCOL) :], value)
    return value


def _resolve_attachment_refs(value: Any, attachments: dict[str, Any]) -> Any:
    value = _maybe_resolve_attachment(value, attachments)
    if isinstance(value, list):
        return [_resolve_attachment_refs(item, attachments) for item in value]
    if isinstance(value, dict):
        return {str(key): _resolve_attachment_refs(item, attachments) for key, item in value.items()}
    return value


def _message_tool_calls(message: Any) -> list[Any]:
    if isinstance(message, dict):
        return message.get("tool_calls") or []
    return getattr(message, "tool_calls", None) or []


def _tool_call_function_name(tool_call: Any) -> Optional[str]:
    if isinstance(tool_call, dict):
        return tool_call.get("function")
    return getattr(tool_call, "function", None)


def _tool_call_arguments(tool_call: Any) -> dict[str, Any]:
    if isinstance(tool_call, dict):
        arguments = tool_call.get("arguments") or {}
    else:
        arguments = getattr(tool_call, "arguments", None) or {}

    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _extract_submit_answer(messages: list[Any], attachments: dict[str, Any]) -> Optional[str]:
    for message in reversed(messages):
        for tool_call in reversed(_message_tool_calls(message)):
            if _tool_call_function_name(tool_call) != "submit":
                continue
            answer = _tool_call_arguments(tool_call).get("answer")
            answer = _maybe_resolve_attachment(answer, attachments)
            if isinstance(answer, str) and answer:
                return answer
    return None


def _event_function_name(event: Any) -> Optional[str]:
    if isinstance(event, dict):
        return event.get("function")
    return getattr(event, "function", None)


def _event_arguments(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        arguments = event.get("arguments") or {}
    else:
        arguments = getattr(event, "arguments", None) or {}

    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _extract_submit_answer_from_events(events: list[Any], attachments: dict[str, Any]) -> Optional[str]:
    for event in reversed(events):
        if _event_function_name(event) != "submit":
            continue
        answer = _event_arguments(event).get("answer")
        answer = _maybe_resolve_attachment(answer, attachments)
        if isinstance(answer, str) and answer:
            return answer
    return None


def _extract_html_document(text: Any) -> Optional[str]:
    if not isinstance(text, str):
        return None
    lower = text.lower()
    if "<html" not in lower or "</html>" not in lower:
        return None
    html_start = lower.index("<html")
    doctype_start = lower.rfind("<!doctype", 0, html_start)
    start = doctype_start if doctype_start != -1 else html_start
    end = lower.rindex("</html>") + len("</html>")
    return text[start:end].strip()


def extract_agent_html_from_transcript(transcript: dict[str, Any], fallback_html: Optional[str] = None) -> str:
    def _tool_calls_from_message(message: Any) -> list[Any]:
        if isinstance(message, dict):
            return message.get("tool_calls") or []
        return []

    def _scan_messages(messages: Any) -> Optional[str]:
        if not isinstance(messages, list):
            return None
        for message in reversed(messages):
            for tool_call in reversed(_tool_calls_from_message(message)):
                if _tool_call_function_name(tool_call) != "submit":
                    continue
                answer = _tool_call_arguments(tool_call).get("answer")
                extracted = _extract_html_document(answer)
                if extracted:
                    return extracted

            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                extracted = _extract_html_document(content)
                if extracted:
                    return extracted
            if isinstance(content, list):
                for block in reversed(content):
                    if not isinstance(block, dict):
                        continue
                    extracted = _extract_html_document(block.get("text"))
                    if extracted:
                        return extracted
        return None

    if not isinstance(transcript, dict):
        return fallback_html or ""

    output = transcript.get("output")
    if isinstance(output, dict):
        extracted = _scan_messages([
            choice.get("message")
            for choice in output.get("choices") or []
            if isinstance(choice, dict) and isinstance(choice.get("message"), dict)
        ])
        if extracted:
            return extracted

        extracted = _extract_html_document(output.get("completion"))
        if extracted and TRUNCATED_TOOL_OUTPUT_MARKER not in extracted:
            return extracted

    extracted = _scan_messages(transcript.get("messages"))
    if extracted:
        return extracted

    events = transcript.get("events")
    if isinstance(events, list):
        extracted = _extract_submit_answer_from_events(events, {})
        extracted = _extract_html_document(extracted)
        if extracted:
            return extracted

    return fallback_html or ""


def _extract_agent_html(sample: Any) -> str:
    attachments = getattr(sample, "attachments", None) or {}
    output = getattr(sample, "output", None)
    completion = _maybe_resolve_attachment(getattr(output, "completion", None) or "", attachments)

    if isinstance(completion, str) and completion and TRUNCATED_TOOL_OUTPUT_MARKER not in completion:
        return completion

    submit_answer = _extract_submit_answer(getattr(sample, "messages", None) or [], attachments)
    if submit_answer:
        return submit_answer

    submit_answer = _extract_submit_answer_from_events(getattr(sample, "events", None) or [], attachments)
    if submit_answer:
        return submit_answer

    return completion if isinstance(completion, str) else str(completion or "")


def _normalize_message_content_blocks(message: Any, html: str) -> Any:
    if not isinstance(message, dict):
        return message

    content = message.get("content")
    if isinstance(content, str):
        if TRUNCATED_TOOL_OUTPUT_MARKER in content:
            message["content"] = html
        return message

    if not isinstance(content, list):
        return message

    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if isinstance(text, str) and TRUNCATED_TOOL_OUTPUT_MARKER in text:
            block["text"] = html
    return message


def normalize_agent_transcript(transcript: dict[str, Any], html: str) -> dict[str, Any]:
    normalized = copy.deepcopy(transcript)

    messages = normalized.get("messages")
    if isinstance(messages, list):
        normalized["messages"] = [_normalize_message_content_blocks(message, html) for message in messages]

    output = normalized.get("output")
    if isinstance(output, dict):
        output["completion"] = html
        choices = output.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if isinstance(message, dict):
                    _normalize_message_content_blocks(message, html)

    return normalized


def run_agent_generation(
    *,
    model: str,
    prompt: str,
    sandbox: Any,
    system_prompt: str,
    log_dir: str | None = None,
    model_base_url: str | None = None,
    model_args: dict[str, Any] | None = None,
    agent_limits: dict[str, Any] | None = None,
    use_browser: bool = True,
    temperature: float | None = None,
    seed: int | None = None,
) -> AgentGenerationResult:
    """Run a sandboxed Inspect ReAct agent through a one-sample task.

    The agent executes inside an Inspect sample context so sandbox-backed tools,
    transcript events, and sample limits all behave as intended.
    """

    from inspect_ai import Task, eval as inspect_eval
    from inspect_ai.agent import react
    from inspect_ai.dataset import Sample
    from inspect_ai.model import GenerateConfig
    from inspect_ai.tool import bash, mcp_server_sandbox, mcp_tools, python as python_tool, text_editor

    limits_cfg = normalize_agent_limits(agent_limits)

    tool_timeout = min(int(limits_cfg.get("working_limit") or 420), 180)
    tools: list[Any] = [
        text_editor(timeout=tool_timeout),
        bash(timeout=tool_timeout),
        python_tool(timeout=tool_timeout),
    ]

    if use_browser:
        try:
            browser_server = mcp_server_sandbox(
                name="playwright",
                command="npx",
                args=[
                    "playwright",
                    "mcp",
                    "--isolated",
                    "--output-dir",
                    "/tmp/playwright-mcp",
                ],
                sandbox="default",
                timeout=120,
            )
            tools.append(mcp_tools(browser_server))
        except Exception:
            # If MCP browser setup fails at construction time, keep the agent usable
            # with editor + execution tools.
            pass

    agent_prompt = (
        f"{system_prompt}\n\n"
        "You are working inside a sandboxed coding environment to produce one standalone HTML document. "
        "Use the available tools when useful to draft, inspect, preview, and refine the page. "
        "Submit exactly one final standalone HTML document as your answer. "
        "Do not wrap the final answer in markdown fences or commentary."
    )

    agent = react(
        prompt=agent_prompt,
        tools=tools,
        attempts=int(limits_cfg.get("attempts") or 1),
        submit=True,
        truncation="auto",
    )

    generate_config_kwargs: dict[str, Any] = {}
    if temperature is not None:
        generate_config_kwargs["temperature"] = temperature
    if seed is not None:
        generate_config_kwargs["seed"] = seed
    max_output = limits_cfg.get("max_output_tokens")
    if max_output is not None:
        generate_config_kwargs["max_tokens"] = int(max_output)
    generate_config = GenerateConfig(**generate_config_kwargs) if generate_config_kwargs else None

    task_kwargs: dict[str, Any] = {
        "dataset": [Sample(input=prompt, id="agent-html", sandbox=sandbox)],
        "solver": agent,
        "model": model,
        "sandbox": sandbox,
        "message_limit": int(limits_cfg.get("message_limit") or 50),
        "token_limit": int(limits_cfg.get("token_limit") or 120000),
        "time_limit": int(limits_cfg.get("time_limit") or 600),
        "working_limit": int(limits_cfg.get("working_limit") or 420),
        "fail_on_error": True,
        "continue_on_fail": False,
        "name": "sandboxed_agent_html_generation",
    }
    if generate_config is not None:
        task_kwargs["config"] = generate_config
    if limits_cfg.get("cost_limit") is not None:
        task_kwargs["cost_limit"] = float(limits_cfg["cost_limit"])

    task = Task(**task_kwargs)

    eval_kwargs: dict[str, Any] = {
        "model": model,
        "display": "none",
        "log_level": "error",
        "log_level_transcript": "warning",
        "log_dir": log_dir,
        "log_samples": True,
        "log_realtime": False,
        "score": False,
        "max_tasks": 1,
        "max_samples": 1,
        "sandbox_cleanup": True,
    }
    if model_base_url is not None:
        eval_kwargs["model_base_url"] = model_base_url
    if model_args:
        eval_kwargs["model_args"] = model_args

    started = time.time()
    logs = inspect_eval(task, **eval_kwargs)
    elapsed_s = time.time() - started

    if not logs:
        raise RuntimeError("Inspect eval returned no logs for sandboxed agent generation")
    log = logs[0]
    samples = getattr(log, "samples", None) or []
    if not samples:
        raise RuntimeError("Inspect eval returned no samples for sandboxed agent generation")
    sample = samples[0]

    attachments = getattr(sample, "attachments", None) or {}
    completion = _extract_agent_html(sample)

    total_input_tokens = 0
    total_output_tokens = 0
    total_tokens = 0
    total_cost = 0.0
    saw_cost = False
    for usage in (getattr(sample, "model_usage", None) or {}).values():
        input_tokens = getattr(usage, "input_tokens", None) or 0
        output_tokens = getattr(usage, "output_tokens", None) or 0
        total_value = getattr(usage, "total_tokens", None)
        cost_value = getattr(usage, "total_cost", None)
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens
        total_tokens += total_value if total_value is not None else (input_tokens + output_tokens)
        if cost_value is not None:
            total_cost += float(cost_value)
            saw_cost = True

    def _jsonable(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [_jsonable(item) for item in value]
        if isinstance(value, dict):
            return {str(key): _jsonable(item) for key, item in value.items()}
        if hasattr(value, "model_dump"):
            try:
                return value.model_dump(mode="json")
            except Exception:
                pass
        if hasattr(value, "model_dump_json"):
            try:
                return json.loads(value.model_dump_json())
            except Exception:
                pass
        return str(value)

    limit_obj = getattr(sample, "limit", None)
    limit_error = None
    if limit_obj is not None:
        limit_type = getattr(limit_obj, "type", None)
        limit_value = getattr(limit_obj, "limit", None)
        limit_error = f"{limit_type}:{limit_value}"

    sample_error = getattr(sample, "error", None)
    if sample_error is not None and not limit_error:
        limit_error = getattr(sample_error, "message", None) or str(sample_error)

    transcript_messages = _resolve_attachment_refs(_jsonable(getattr(sample, "messages", None) or []), attachments)
    transcript_events = _resolve_attachment_refs(_jsonable(getattr(sample, "events", None) or []), attachments)
    transcript_output = _resolve_attachment_refs(_jsonable(getattr(sample, "output", None)), attachments)
    if isinstance(transcript_output, dict):
        transcript_output["completion"] = completion

    transcript = {
        "format": "inspect_agent_conversation/v1",
        "sandbox": sandbox,
        "messages": transcript_messages,
        "events": transcript_events,
        "output": transcript_output,
        "limit": _jsonable(limit_obj),
        "error": _jsonable(sample_error),
        "limits": _jsonable(limits_cfg),
        "usage": {
            "prompt_tokens": total_input_tokens or None,
            "completion_tokens": total_output_tokens or None,
            "total_tokens": total_tokens or None,
            "total_cost": total_cost if saw_cost else None,
        },
    }
    transcript = normalize_agent_transcript(transcript, completion)

    usage = {
        "prompt_tokens": total_input_tokens or None,
        "completion_tokens": total_output_tokens or None,
        "total_tokens": total_tokens or None,
        "total_cost": total_cost if saw_cost else None,
    }

    return AgentGenerationResult(
        html=completion,
        transcript=transcript,
        usage=usage,
        elapsed_s=elapsed_s,
        sandbox=sandbox,
        limit_error=limit_error,
        eval_log_path=getattr(log, "location", None),
    )