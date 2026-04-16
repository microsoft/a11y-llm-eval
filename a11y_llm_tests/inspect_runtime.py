"""Inspect AI-backed generation runtime."""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


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

    def _wrap_output(self, output: Any) -> InspectCompletionResponse:
        usage_obj = getattr(output, "usage", None)
        usage = None
        if usage_obj is not None:
            usage = {
                "prompt_tokens": getattr(usage_obj, "input_tokens", None),
                "completion_tokens": getattr(usage_obj, "output_tokens", None),
                "total_tokens": getattr(usage_obj, "total_tokens", None),
                "total_cost": getattr(usage_obj, "total_cost", None),
            }

        content = getattr(output, "completion", None)
        if content is None:
            message = getattr(output, "message", None)
            content = getattr(message, "text", None)
        if content is None:
            content = ""

        return InspectCompletionResponse(
            str(content),
            usage=usage,
            stop_reason=getattr(output, "stop_reason", None),
        )