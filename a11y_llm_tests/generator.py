"""LLM HTML generation & caching layer."""
from __future__ import annotations
import hashlib, os, time, random
from pathlib import Path
from typing import Tuple, Dict, Any, Optional
import json

from .inspect_runtime import (
    AgentGenerationResult,
    GenerationRequest,
    InspectGenerationRuntime,
    extract_agent_html_from_transcript,
    normalize_agent_transcript,
    normalize_agent_limits,
    run_agent_generation,
)
from .model_config import get_model_provider
from .utils import (
    atomic_write_bytes,
    atomic_write_text,
    is_probably_complete_html,
    read_and_validate_cached_html,
    write_sha256_sidecar,
)

CACHE_DIR = Path(".cache/generations")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

generation_runtime = InspectGenerationRuntime()

# Retry policy for generation calls
RETRY_MAX_ATTEMPTS = 5
RETRY_BASE_DELAY = 1.0  # seconds
RETRY_MAX_DELAY = 60.0  # seconds

# If we detect a truncated HTML document (often from partial writes or model cutoffs),
# regenerate once before returning.
TRUNCATION_RETRY_MAX = 3

# Default output budget. Many Anthropic/Claude routes default to ~4096 if not explicitly set.
DEFAULT_MAX_TOKENS = 32768

_PROVIDER_ENV_DEBUG_VARS: dict[str, tuple[str, ...]] = {
    "azure": ("AZURE_API_BASE", "AZURE_API_KEY", "AZURE_API_VERSION"),
    "azure_ai": ("AZURE_AI_API_BASE", "AZURE_AI_API_KEY", "AZURE_AI_API_VERSION"),
    "azureai": ("AZUREAI_BASE_URL", "AZUREAI_API_KEY", "AZUREAI_AUDIENCE"),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "vertex_ai": ("VERTEXAI_PROJECT", "VERTEXAI_LOCATION", "GOOGLE_APPLICATION_CREDENTIALS"),
    "openai": ("OPENAI_API_KEY",),
}


def _load_required_env(env_name: str) -> str:
    value = os.environ.get(env_name)
    if value:
        return value
    raise RuntimeError(f"Required environment variable is not set: {env_name}")


def _load_optional_env(env_name: str) -> Optional[str]:
    value = os.environ.get(env_name)
    return value if value else None


def _is_anthropic_model(model: str) -> bool:
    """Heuristic for whether a configured model routes to Anthropic."""

    m = (model or "").strip().lower()
    return (
        m.startswith("anthropic/")
        or m.startswith("anthropic.")
        or m.startswith("anthropic:")
        or m.startswith("claude-")
        or m == "claude"
        or m.startswith("claude/")
    )


def _is_codex_model(model: str) -> bool:
    """Heuristic for whether a model is a Codex-style deployment.

    Some Codex / code-agent deployments (notably certain Azure GPT-* Codex models)
    reject sampling parameters like `temperature`. We omit those parameters to
    avoid hard failures.
    """

    m = (model or "").strip().lower()
    return "codex" in m and (m.endswith("codex") or "-codex" in m or "/codex" in m)


class OutputTokenLimitHit(RuntimeError):
    """Raised when the provider indicates output was truncated due to token limits."""

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        finish_reason: Optional[str] = None,
        stop_reason: Optional[str] = None,
        tokens_out: Optional[int] = None,
    ):
        # NOTE: exceptions must be pickleable to cross multiprocessing boundaries.
        # During unpickling, Python typically reconstructs exceptions as `cls(*args)`.
        if message is None:
            msg = (
                f"Output token limit hit for model={model} (max_tokens={max_tokens}, "
                f"finish_reason={finish_reason}, stop_reason={stop_reason}, tokens_out={tokens_out})."
            )
        else:
            msg = message
        super().__init__(msg)
        self.model = model
        self.max_tokens = max_tokens
        self.finish_reason = finish_reason
        self.stop_reason = stop_reason
        self.tokens_out = tokens_out


def _is_azure_ai_provider(provider: str) -> bool:
    return provider in {"azure_ai", "azureai"}


def _is_openai_azure_model(model: str) -> bool:
    parts = [part.strip().lower() for part in (model or "").split("/") if part.strip()]
    return len(parts) >= 2 and parts[0] == "openai" and parts[1] == "azure"


def _format_model_debug_label(model: str, model_display_name: Optional[str] = None) -> str:
    display = (model_display_name or "").strip()
    if display and display != model:
        return f"{display} [{model}]"
    return model


def _format_provider_auth_debug(model: str) -> str:
    provider = get_model_provider(model)
    env_names = _PROVIDER_ENV_DEBUG_VARS.get(provider)
    if not env_names:
        return f"provider={provider}"
    env_status = ", ".join(
        f"{name}={'set' if os.environ.get(name) else 'missing'}" for name in env_names
    )
    return f"provider={provider}; auth_env[{env_status}]"


def _build_provider_completion_kwargs(model: str, provider_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    provider = get_model_provider(model)
    config = provider_config or {}
    auth_cfg = config.get("auth") if isinstance(config, dict) else None
    if not isinstance(auth_cfg, dict):
        return {}

    mode = str(auth_cfg.get("mode") or "").strip().lower()
    if not mode or mode == "env":
        return {}

    if mode != "default_azure_credential":
        raise RuntimeError(f"Unsupported auth mode for provider '{provider}': {mode}")

    if provider != "azure" and not _is_azure_ai_provider(provider):
        raise RuntimeError(
            f"auth.mode=default_azure_credential is only supported for Azure providers, got '{provider}'"
        )

    if _is_azure_ai_provider(provider):
        try:
            import azure.identity  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Model provider is configured with auth.mode=default_azure_credential, but azure-identity is not installed"
            ) from exc

        api_base_env = str(auth_cfg.get("api_base_env") or "AZUREAI_BASE_URL")
        audience_env = str(auth_cfg.get("audience_env") or "AZUREAI_AUDIENCE")
        scope = str(auth_cfg.get("scope") or "https://cognitiveservices.azure.com/.default")
        os.environ[audience_env] = scope
        return {
            "api_base": _load_required_env(api_base_env),
        }

    if provider == "azure" and _is_openai_azure_model(model):
        try:
            import azure.identity  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Model provider is configured with auth.mode=default_azure_credential, but azure-identity is not installed"
            ) from exc

        api_base_env = str(auth_cfg.get("api_base_env") or "AZUREAI_OPENAI_BASE_URL")
        api_version_env = str(auth_cfg.get("api_version_env") or "AZUREAI_OPENAI_API_VERSION")
        audience_env = str(auth_cfg.get("audience_env") or "AZUREAI_AUDIENCE")
        scope = str(auth_cfg.get("scope") or "https://cognitiveservices.azure.com/.default")
        os.environ[audience_env] = scope

        kwargs = {
            "api_base": _load_required_env(api_base_env),
        }
        api_version = _load_optional_env(api_version_env)
        if api_version is not None:
            kwargs["api_version"] = api_version
        return kwargs

    try:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    except ImportError as exc:
        raise RuntimeError(
            "Model provider is configured with auth.mode=default_azure_credential, but azure-identity is not installed"
        ) from exc

    default_api_base_env = "AZURE_API_BASE"
    default_api_version_env = "AZURE_API_VERSION"
    api_base_env = str(auth_cfg.get("api_base_env") or default_api_base_env)
    api_version_env = str(auth_cfg.get("api_version_env") or default_api_version_env)
    scope = str(auth_cfg.get("scope") or "https://cognitiveservices.azure.com/.default")

    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(credential, scope)
    kwargs = {
        "api_base": _load_required_env(api_base_env),
        "azure_ad_token_provider": token_provider,
    }
    api_version = _load_optional_env(api_version_env)
    if api_version is not None:
        kwargs["api_version"] = api_version
    return kwargs


def supports_batch_generation() -> bool:
    return bool(getattr(generation_runtime, "supports_batch_generation", lambda: False)())


def configure_runtime(log_dir: Optional[str] = None) -> None:
    generation_runtime.set_log_dir(log_dir)

DEFAULT_SYSTEM_PROMPT = (
    "You are generating a single standalone HTML document. "
    "Do NOT wrap output in markdown fences. Include <head> and <body>. "
    "Do NOT explain the code, just output it."
)

_PROMPT_JOINER = "\n|:|\n"
_configured_system_prompt: str = DEFAULT_SYSTEM_PROMPT
_custom_instructions: Optional[str] = None


def configure_prompts(system_prompt: Optional[str] = None, custom_instructions: Optional[str] = None) -> None:
    """Configure the base system prompt and optional custom instructions."""
    global _configured_system_prompt, _custom_instructions
    base = (system_prompt or "").strip()
    _configured_system_prompt = base or DEFAULT_SYSTEM_PROMPT
    if custom_instructions is None:
        _custom_instructions = None
    else:
        text = custom_instructions.rstrip("\n")
        _custom_instructions = text if text.strip() else None


def get_base_system_prompt() -> str:
    return _configured_system_prompt


def get_custom_instructions() -> Optional[str]:
    return _custom_instructions


def get_effective_system_prompt() -> str:
    if _custom_instructions:
        return f"{_configured_system_prompt}\n\n{_custom_instructions}".strip()
    return _configured_system_prompt


def prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def compute_prompt_hash(user_prompt: str) -> str:
    combined = _PROMPT_JOINER.join([
        _configured_system_prompt,
        _custom_instructions or "",
        user_prompt,
    ])
    return prompt_hash(combined)


def clean_generation(raw: str) -> str:
    # Strip markdown fences if present
    if "```" in raw:
        parts = []
        inside = False
        for line in raw.splitlines():
            if line.strip().startswith("```"):
                inside = not inside
                continue
            if inside:
                parts.append(line)
        if parts:
            raw = "\n".join(parts)
    # Keep only first HTML document, preserving a leading doctype when present.
    lower = raw.lower()
    if "<html" in lower and "</html>" in lower:
        html_start = lower.index("<html")
        doctype_start = lower.rfind("<!doctype", 0, html_start)
        start = doctype_start if doctype_start != -1 else html_start
        end = lower.index("</html>") + len("</html>")
        raw = raw[start:end]
    return raw.strip()


def _meta_path(cache_file: Path) -> Path:
    return cache_file.with_suffix(cache_file.suffix + ".meta.json")


def _agent_transcript_cache_path(cache_file: Path) -> Path:
    return cache_file.with_suffix(cache_file.suffix + ".agent.json")


def _agent_eval_cache_path(cache_file: Path) -> Path:
    return cache_file.with_suffix(cache_file.suffix + ".eval")


def _cache_artifacts(
    model: str,
    user_prompt: str,
    iteration: int,
    seed: Optional[int],
    generation_mode: Optional[str] = None,
) -> tuple[str, Path, Path]:
    prompt_hash_value = compute_prompt_hash(user_prompt)
    seed_part = f"_s{seed}" if seed is not None else ""
    iteration_part = f"_i{iteration}"
    mode_part = "_agent" if generation_mode == "agent" else ""
    cache_file = CACHE_DIR / f"{model}_{prompt_hash_value}{seed_part}{iteration_part}{mode_part}.html"
    return prompt_hash_value, cache_file, _meta_path(cache_file)


def _build_generation_meta(
    *,
    cached: bool,
    latency_s: float,
    prompt_hash_value: str,
    model_display_name: Optional[str],
    tokens_in: Optional[int] = None,
    tokens_out: Optional[int] = None,
    total_tokens: Optional[int] = None,
    cost_usd: Optional[float] = None,
    finish_reason: Optional[str] = None,
    stop_reason: Optional[str] = None,
    max_tokens: Optional[int] = None,
    seed: Optional[int] = None,
    temperature: Optional[float] = None,
    system_prompt: Optional[str] = None,
    custom_instructions: Optional[str] = None,
    effective_system_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "cached": cached,
        "latency_s": latency_s,
        "prompt_hash": prompt_hash_value,
        "model_display_name": model_display_name,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "total_tokens": total_tokens,
        "cost_usd": cost_usd,
        "finish_reason": finish_reason,
        "stop_reason": stop_reason,
        "max_tokens": max_tokens,
        "seed": seed,
        "temperature": temperature,
        "system_prompt": system_prompt,
        "custom_instructions": custom_instructions,
        "effective_system_prompt": effective_system_prompt,
    }


def _load_cached_generation(
    *,
    cache_file: Path,
    meta_file: Path,
    prompt_hash_value: str,
    temperature: Optional[float],
    seed: Optional[int],
    model_display_name: Optional[str],
    base_system_prompt: str,
    custom_instructions: Optional[str],
    effective_system_prompt: str,
) -> tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    cached_html, reason = read_and_validate_cached_html(cache_file)
    if cached_html is None:
        return None, None, reason

    meta: Dict[str, Any] = _build_generation_meta(
        cached=True,
        latency_s=0.0,
        prompt_hash_value=prompt_hash_value,
        model_display_name=model_display_name,
        seed=seed,
        temperature=temperature,
        system_prompt=base_system_prompt,
        custom_instructions=custom_instructions,
        effective_system_prompt=effective_system_prompt,
    )
    if meta_file.exists():
        try:
            loaded = json.loads(meta_file.read_text(encoding="utf-8"))
            meta.update({
                k: loaded.get(k) for k in [
                    "tokens_in",
                    "tokens_out",
                    "total_tokens",
                    "cost_usd",
                    "system_prompt",
                    "custom_instructions",
                    "effective_system_prompt",
                    "generation_mode",
                    "agent_sandbox",
                    "agent_limit_error",
                    "agent_limits",
                ]
            })
        except Exception:
            pass
    return cached_html, meta, None


def _load_cached_agent_generation(
    *,
    cache_file: Path,
    meta_file: Path,
    prompt_hash_value: str,
    temperature: Optional[float],
    seed: Optional[int],
    model_display_name: Optional[str],
    base_system_prompt: str,
    custom_instructions: Optional[str],
    effective_system_prompt: str,
    runtime_log_dir: Optional[str] = None,
) -> tuple[Optional[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
    cached_html, meta, reason = _load_cached_generation(
        cache_file=cache_file,
        meta_file=meta_file,
        prompt_hash_value=prompt_hash_value,
        temperature=temperature,
        seed=seed,
        model_display_name=model_display_name,
        base_system_prompt=base_system_prompt,
        custom_instructions=custom_instructions,
        effective_system_prompt=effective_system_prompt,
    )
    if cached_html is None or meta is None:
        return None, None, None, reason

    if meta.get("agent_limit_error"):
        return None, None, None, "agent_limit_error_in_cache"

    transcript_file = _agent_transcript_cache_path(cache_file)
    try:
        transcript = json.loads(transcript_file.read_text(encoding="utf-8"))
    except Exception:
        return None, None, None, "missing_or_invalid_agent_transcript"

    if not isinstance(transcript, dict):
        return None, None, None, "missing_or_invalid_agent_transcript"

    repaired_html = clean_generation(extract_agent_html_from_transcript(transcript, fallback_html=cached_html))
    if is_probably_complete_html(repaired_html):
        cached_html = repaired_html
        try:
            html_bytes = cached_html.encode("utf-8")
            atomic_write_bytes(cache_file, html_bytes)
            write_sha256_sidecar(cache_file, html_bytes)
        except Exception:
            pass

    transcript = normalize_agent_transcript(transcript, cached_html)

    meta["generation_mode"] = meta.get("generation_mode") or "inspect_react_agent"

    # Restore the cached .eval log into this run's inspect_logs/ directory
    # so the report can link to it.
    eval_cache = _agent_eval_cache_path(cache_file)
    restored_eval_path = None
    if eval_cache.exists() and runtime_log_dir:
        try:
            import shutil
            dest_dir = Path(runtime_log_dir)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / eval_cache.name
            shutil.copy2(str(eval_cache), str(dest))
            restored_eval_path = str(dest)
        except Exception:
            pass
    meta["agent_eval_path"] = restored_eval_path
    return cached_html, meta, transcript, None


def _effective_max_tokens_for_model(model: str) -> Optional[int]:
    return DEFAULT_MAX_TOKENS if _is_anthropic_model(model) else None


def _build_generation_request(
    *,
    model: str,
    messages: Any,
    temperature: Optional[float],
    seed: Optional[int],
    effective_max_tokens: Optional[int],
    provider_config: Optional[Dict[str, Any]],
    max_workers: Optional[int] = None,
) -> GenerationRequest:
    provider_kwargs = _build_provider_completion_kwargs(model, provider_config)
    return GenerationRequest(
        model=model,
        messages=messages,
        seed=seed,
        temperature=(None if temperature is None or _is_codex_model(model) else temperature),
        max_tokens=effective_max_tokens,
        api_base=provider_kwargs.get("api_base"),
        api_version=provider_kwargs.get("api_version"),
        azure_ad_token_provider=provider_kwargs.get("azure_ad_token_provider"),
        max_workers=max_workers,
        cache_prompt=True if _is_anthropic_model(model) else None,
    )


def _extract_finish_and_stop_reason(resp) -> tuple[Optional[str], Optional[str]]:
    """Best-effort extraction of finish/stop reasons across providers."""
    finish_reason = None
    stop_reason = None
    try:
        choice0 = resp.choices[0] if getattr(resp, "choices", None) else None
        if isinstance(choice0, dict):
            finish_reason = choice0.get("finish_reason")
            stop_reason = choice0.get("stop_reason") or choice0.get("stopReason")
        else:
            finish_reason = getattr(choice0, "finish_reason", None)
            stop_reason = getattr(choice0, "stop_reason", None) or getattr(choice0, "stopReason", None)
    except Exception:
        pass
    if stop_reason is None:
        stop_reason = getattr(resp, "stop_reason", None) or getattr(resp, "stopReason", None)
    return finish_reason, stop_reason


def _response_to_generation_result(
    *,
    resp,
    model: str,
    elapsed: float,
    prompt_hash_value: str,
    temperature: Optional[float],
    seed: Optional[int],
    model_display_name: Optional[str],
    base_system_prompt: str,
    custom_instructions: Optional[str],
    effective_system_prompt: str,
    effective_max_tokens: Optional[int],
) -> tuple[str, Dict[str, Any]]:
    finish_reason, stop_reason = _extract_finish_and_stop_reason(resp)

    usage = getattr(resp, "usage", None) or getattr(resp, "_hidden_params", {}).get("usage") or {}
    tokens_in = usage.get("prompt_tokens") if isinstance(usage, dict) else None
    tokens_out = usage.get("completion_tokens") if isinstance(usage, dict) else None
    total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None

    limit_hit = False
    if isinstance(finish_reason, str) and finish_reason.lower() == "length":
        limit_hit = True
    if isinstance(stop_reason, str) and stop_reason.lower() in {"max_tokens", "length", "token_limit", "tokens"}:
        limit_hit = True
    if effective_max_tokens is not None and tokens_out is not None and tokens_out >= (effective_max_tokens - 1):
        limit_hit = True
    if limit_hit:
        raise OutputTokenLimitHit(
            model=model,
            max_tokens=effective_max_tokens,
            finish_reason=finish_reason,
            stop_reason=stop_reason,
            tokens_out=tokens_out,
        )

    cost_usd = getattr(resp, "response_cost", None)
    if cost_usd is None:
        hidden = getattr(resp, "_hidden_params", {})
        if isinstance(hidden, dict):
            cost_usd = hidden.get("response_cost")

    raw = resp.choices[0].message.content
    html = clean_generation(raw)
    meta = _build_generation_meta(
        cached=False,
        latency_s=elapsed,
        prompt_hash_value=prompt_hash_value,
        model_display_name=model_display_name,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        finish_reason=finish_reason,
        stop_reason=stop_reason,
        max_tokens=effective_max_tokens,
        seed=seed,
        temperature=temperature,
        system_prompt=base_system_prompt,
        custom_instructions=custom_instructions,
        effective_system_prompt=effective_system_prompt,
    )
    return html, meta


def _write_generation_cache(
    *,
    cache_file: Path,
    meta_file: Path,
    html: str,
    model: str,
    model_display_name: Optional[str],
    prompt_hash_value: str,
    meta: Dict[str, Any],
) -> None:
    cache_file.parent.mkdir(exist_ok=True, parents=True)
    html_bytes = html.encode("utf-8")
    atomic_write_bytes(cache_file, html_bytes)
    write_sha256_sidecar(cache_file, html_bytes)

    meta_payload = {
        "model": model,
        "model_display_name": model_display_name,
        "prompt_hash": prompt_hash_value,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tokens_in": meta.get("tokens_in"),
        "tokens_out": meta.get("tokens_out"),
        "total_tokens": meta.get("total_tokens"),
        "cost_usd": meta.get("cost_usd"),
        "seed": meta.get("seed"),
        "temperature": meta.get("temperature"),
        "system_prompt": meta.get("system_prompt"),
        "custom_instructions": meta.get("custom_instructions"),
        "effective_system_prompt": meta.get("effective_system_prompt"),
        "generation_mode": meta.get("generation_mode"),
        "agent_sandbox": meta.get("agent_sandbox"),
        "agent_limit_error": meta.get("agent_limit_error"),
        "agent_limits": meta.get("agent_limits"),
    }
    try:
        atomic_write_text(meta_file, json.dumps(meta_payload, indent=2), encoding="utf-8")
    except Exception:
        pass


def _write_agent_generation_cache(
    *,
    cache_file: Path,
    meta_file: Path,
    html: str,
    model: str,
    model_display_name: Optional[str],
    prompt_hash_value: str,
    meta: Dict[str, Any],
    transcript: Dict[str, Any],
    eval_log_path: Optional[str] = None,
) -> None:
    _write_generation_cache(
        cache_file=cache_file,
        meta_file=meta_file,
        html=html,
        model=model,
        model_display_name=model_display_name,
        prompt_hash_value=prompt_hash_value,
        meta=meta,
    )
    try:
        atomic_write_text(
            _agent_transcript_cache_path(cache_file),
            json.dumps(transcript, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass
    # Cache the Inspect AI .eval log alongside other sidecars so it can be
    # restored on future cache hits.
    if eval_log_path:
        src = Path(eval_log_path)
        if src.exists():
            try:
                import shutil
                shutil.copy2(str(src), str(_agent_eval_cache_path(cache_file)))
            except Exception:
                pass


def _invalidate_cache_entry(cache_file: Path) -> None:
    """Best-effort removal of a corrupted cache entry (html + sidecars)."""
    for p in [
        cache_file,
        cache_file.with_suffix(cache_file.suffix + ".sha256"),
        _meta_path(cache_file),
        _agent_transcript_cache_path(cache_file),
        _agent_eval_cache_path(cache_file),
    ]:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


def generate_html_batch_with_meta(
    model: str,
    requests: list[Dict[str, Any]],
    temperature: Optional[float] = None,
    seed: Optional[int] = None,
    disable_cache: bool = False,
    debug_truncated_cache: bool = False,
    model_display_name: Optional[str] = None,
    provider_config: Optional[Dict[str, Any]] = None,
    runtime_log_dir: Optional[str] = None,
) -> list[Dict[str, Any]]:
    """Generate multiple prompts for the same model using the Inspect runtime batch path.

    Each request must include `user_prompt` and `iteration`. Cache hits are returned
    immediately and only cache misses are submitted through grouped batch generation.
    Individual item failures fall back to `generate_html_with_meta`.
    """
    if not requests:
        return []

    base_system_prompt = get_base_system_prompt()
    custom_instructions = get_custom_instructions()
    effective_system_prompt = get_effective_system_prompt()
    configure_runtime(runtime_log_dir)
    effective_max_tokens = _effective_max_tokens_for_model(model)
    generation_runtime.drop_params = True
    model_debug_label = _format_model_debug_label(model, model_display_name)
    provider_auth_debug = _format_provider_auth_debug(model)

    results: list[Optional[Dict[str, Any]]] = [None] * len(requests)
    misses: list[Dict[str, Any]] = []

    for index, request in enumerate(requests):
        user_prompt = request["user_prompt"]
        iteration = int(request["iteration"])
        request_seed = request.get("seed", seed)
        request_temperature = request.get("temperature", temperature)
        request_disable_cache = bool(request.get("disable_cache", disable_cache))
        request_debug_truncated_cache = bool(request.get("debug_truncated_cache", debug_truncated_cache))
        prompt_hash_value, cache_file, meta_file = _cache_artifacts(model, user_prompt, iteration, request_seed)

        truncated_cache_files: list[str] = []
        truncated_cache_reasons: dict[str, str] = {}
        if not request_disable_cache and cache_file.exists():
            cached_html, cached_meta, reason = _load_cached_generation(
                cache_file=cache_file,
                meta_file=meta_file,
                prompt_hash_value=prompt_hash_value,
                temperature=request_temperature,
                seed=request_seed,
                model_display_name=model_display_name,
                base_system_prompt=base_system_prompt,
                custom_instructions=custom_instructions,
                effective_system_prompt=effective_system_prompt,
            )
            if cached_html is not None and cached_meta is not None:
                results[index] = {"html": cached_html, "meta": cached_meta}
                continue
            if request_debug_truncated_cache:
                truncated_cache_files.append(str(cache_file))
                truncated_cache_reasons[str(cache_file)] = reason or "invalid"
            else:
                _invalidate_cache_entry(cache_file)

        misses.append({
            "index": index,
            "user_prompt": user_prompt,
            "iteration": iteration,
            "seed": request_seed,
            "temperature": request_temperature,
            "disable_cache": request_disable_cache,
            "debug_truncated_cache": request_debug_truncated_cache,
            "prompt_hash": prompt_hash_value,
            "cache_file": cache_file,
            "meta_file": meta_file,
            "truncated_cache_files": truncated_cache_files,
            "truncated_cache_reasons": truncated_cache_reasons,
        })

    if not misses:
        return [result for result in results if result is not None]

    def _fallback_single(item: Dict[str, Any]) -> Dict[str, Any]:
        html, meta = generate_html_with_meta(
            model=model,
            user_prompt=item["user_prompt"],
            iteration=item["iteration"],
            temperature=item["temperature"],
            seed=item["seed"],
            disable_cache=item["disable_cache"],
            debug_truncated_cache=item["debug_truncated_cache"],
            model_display_name=model_display_name,
            provider_config=provider_config,
            runtime_log_dir=runtime_log_dir,
        )
        return {"html": html, "meta": meta}

    print(
        f"Generating HTML batch with model={model_debug_label}, temp={temperature}, seed={seed} "
        f"({provider_auth_debug})..."
    )

    batch_messages = [
        [
            {"role": "system", "content": effective_system_prompt},
            {"role": "user", "content": item["user_prompt"]},
        ]
        for item in misses
    ]
    batch_request = _build_generation_request(
        model=model,
        messages=batch_messages,
        temperature=temperature,
        seed=seed,
        effective_max_tokens=effective_max_tokens,
        provider_config=provider_config,
        max_workers=min(100, len(misses)),
    )

    batch_start = time.time()
    try:
        batch_responses = generation_runtime.generate_batch([
            GenerationRequest(
                model=batch_request.model,
                messages=messages,
                seed=batch_request.seed,
                temperature=batch_request.temperature,
                max_tokens=batch_request.max_tokens,
                api_base=batch_request.api_base,
                api_version=batch_request.api_version,
                azure_ad_token_provider=batch_request.azure_ad_token_provider,
                max_workers=batch_request.max_workers,
                cache_prompt=batch_request.cache_prompt,
            )
            for messages in batch_messages
        ])
    except Exception:
        batch_responses = None
    batch_elapsed = time.time() - batch_start

    if not isinstance(batch_responses, list) or len(batch_responses) != len(misses):
        for item in misses:
            results[item["index"]] = _fallback_single(item)
        return [result for result in results if result is not None]

    for item, resp in zip(misses, batch_responses):
        if isinstance(resp, Exception):
            results[item["index"]] = _fallback_single(item)
            continue

        try:
            html, meta = _response_to_generation_result(
                resp=resp,
                model=model,
                elapsed=batch_elapsed,
                prompt_hash_value=item["prompt_hash"],
                temperature=item["temperature"],
                seed=item["seed"],
                model_display_name=model_display_name,
                base_system_prompt=base_system_prompt,
                custom_instructions=custom_instructions,
                effective_system_prompt=effective_system_prompt,
                effective_max_tokens=effective_max_tokens,
            )
        except OutputTokenLimitHit:
            raise
        except Exception:
            results[item["index"]] = _fallback_single(item)
            continue

        if not is_probably_complete_html(html):
            results[item["index"]] = _fallback_single(item)
            continue

        cacheable = bool(html) and is_probably_complete_html(html)
        should_write_cache = cacheable and not (
            item["debug_truncated_cache"] and item["truncated_cache_files"]
        )
        if should_write_cache:
            _write_generation_cache(
                cache_file=item["cache_file"],
                meta_file=item["meta_file"],
                html=html,
                model=model,
                model_display_name=model_display_name,
                prompt_hash_value=item["prompt_hash"],
                meta=meta,
            )
        if item["truncated_cache_files"]:
            meta["truncated_cache_files"] = item["truncated_cache_files"]
            meta["truncated_cache_reasons"] = item["truncated_cache_reasons"]
        results[item["index"]] = {"html": html, "meta": meta}

    return [result for result in results if result is not None]


def generate_html_with_meta(
    model: str,
    user_prompt: str,
    iteration: int,
    temperature: Optional[float] = None,
    seed: Optional[int] = None,
    disable_cache: bool = False,
    debug_truncated_cache: bool = False,
    model_display_name: Optional[str] = None,
    provider_config: Optional[Dict[str, Any]] = None,
    runtime_log_dir: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Generate (or load cached) HTML plus metadata including token usage & cost.

    Returns:
        html (str): The generated HTML document.
        meta (dict): {
            'cached': bool,
            'latency_s': float,
            'prompt_hash': str,
            'tokens_in': int|None,
            'tokens_out': int|None,
            'total_tokens': int|None,
            'cost_usd': float|None,
        }
    """
    base_system_prompt = get_base_system_prompt()
    custom_instructions = get_custom_instructions()
    effective_system_prompt = get_effective_system_prompt()
    configure_runtime(runtime_log_dir)
    h, cache_file, meta_file = _cache_artifacts(model, user_prompt, iteration, seed)

    truncated_cache_files: list[str] = []
    truncated_cache_reasons: dict[str, str] = {}
    if not disable_cache and cache_file.exists():
        cached_html, cached_meta, reason = _load_cached_generation(
            cache_file=cache_file,
            meta_file=meta_file,
            prompt_hash_value=h,
            temperature=temperature,
            seed=seed,
            model_display_name=model_display_name,
            base_system_prompt=base_system_prompt,
            custom_instructions=custom_instructions,
            effective_system_prompt=effective_system_prompt,
        )
        if cached_html is not None and cached_meta is not None:
            return cached_html, cached_meta

        # Corrupted/partial cache entry; either invalidate (default) or record for debug.
        if debug_truncated_cache:
            truncated_cache_files.append(str(cache_file))
            truncated_cache_reasons[str(cache_file)] = reason or "invalid"
        else:
            _invalidate_cache_entry(cache_file)

    start = time.time()
    generation_runtime.drop_params = True
    model_debug_label = _format_model_debug_label(model, model_display_name)
    provider_auth_debug = _format_provider_auth_debug(model)
    print(
        f"Generating HTML with model={model_debug_label}, temp={temperature}, seed={seed} "
        f"({provider_auth_debug})..."
    )

    effective_max_tokens = _effective_max_tokens_for_model(model)

    def _call_generation_runtime_with_retries():
        resp = None
        last_exc: Optional[BaseException] = None
        for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
            try:
                request = _build_generation_request(
                    model=model,
                    messages=[
                        {"role": "system", "content": effective_system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    seed=seed,
                    effective_max_tokens=effective_max_tokens,
                    provider_config=provider_config,
                )

                resp = generation_runtime.generate(request)
                if resp and getattr(resp, "choices", None) and len(resp.choices) > 0:
                    return resp
                last_exc = RuntimeError("generation runtime returned no choices")
            except Exception as e:
                last_exc = e

            if attempt == RETRY_MAX_ATTEMPTS:
                break
            delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
            jitter = random.uniform(0, delay * 0.1)
            sleep_for = delay + jitter
            print(
                f"generation call failed for model={model_debug_label} ({provider_auth_debug}) "
                f"(attempt {attempt}/{RETRY_MAX_ATTEMPTS}): {last_exc}; "
                f"retrying in {sleep_for:.1f}s..."
            )
            time.sleep(sleep_for)

        if last_exc:
            raise last_exc
        raise RuntimeError("generation failed with no response")

    resp = None
    html = None
    meta: Dict[str, Any] = _build_generation_meta(
        cached=False,
        latency_s=0.0,
        prompt_hash_value=h,
        model_display_name=model_display_name,
        seed=seed,
        temperature=temperature,
        system_prompt=base_system_prompt,
        custom_instructions=custom_instructions,
        effective_system_prompt=effective_system_prompt,
    )

    for trunc_attempt in range(TRUNCATION_RETRY_MAX + 1):
        resp = _call_generation_runtime_with_retries()
        html, meta = _response_to_generation_result(
            resp=resp,
            model=model,
            elapsed=0.0,
            prompt_hash_value=h,
            temperature=temperature,
            seed=seed,
            model_display_name=model_display_name,
            base_system_prompt=base_system_prompt,
            custom_instructions=custom_instructions,
            effective_system_prompt=effective_system_prompt,
            effective_max_tokens=effective_max_tokens,
        )

        if is_probably_complete_html(html):
            break
        if trunc_attempt < TRUNCATION_RETRY_MAX:
            print("Detected truncated/incomplete HTML; retrying generation once...")

    elapsed = time.time() - start

    # Cache only if the output looks complete; never poison the cache with truncated HTML.
    cacheable = bool(html) and is_probably_complete_html(html)
    # In debug mode, preserve truncated cache files for inspection (don't overwrite them).
    should_write_cache = cacheable and not (debug_truncated_cache and truncated_cache_files)
    meta["latency_s"] = elapsed
    if should_write_cache:
        _write_generation_cache(
            cache_file=cache_file,
            meta_file=meta_file,
            html=html,
            model=model,
            model_display_name=model_display_name,
            prompt_hash_value=h,
            meta=meta,
        )

    if truncated_cache_files:
        meta["truncated_cache_files"] = truncated_cache_files
        meta["truncated_cache_reasons"] = truncated_cache_reasons
    return html or "", meta


def generate_html(model: str, user_prompt: str, temperature: float = None, seed: Optional[int] = None, disable_cache: bool = False) -> Tuple[str, bool, float]:
    """Backward-compatible shim. Prefer generate_html_with_meta.

    Returns legacy tuple (html, cached, latency_s)."""
    html, meta = generate_html_with_meta(
        model,
        user_prompt,
        iteration=0,
        temperature=temperature,
        seed=seed,
        disable_cache=disable_cache,
    )
    return html, meta["cached"], meta["latency_s"]


def _normalize_agent_sandbox_spec(value: Any) -> Any:
    if isinstance(value, tuple) and len(value) == 2:
        return (str(value[0]), str(value[1]))
    if isinstance(value, list) and len(value) == 2:
        return (str(value[0]), str(value[1]))
    return value


def format_agent_sandbox(value: Any) -> Optional[str]:
    normalized = _normalize_agent_sandbox_spec(value)
    if normalized is None:
        return None
    if isinstance(normalized, tuple) and len(normalized) == 2:
        return f"{normalized[0]}:{normalized[1]}"
    return str(normalized)


def default_agent_sandbox() -> tuple[str, str]:
    return (
        "docker",
        (Path(__file__).resolve().parent.parent / "config" / "inspect_agent_sandbox" / "compose.yaml").as_posix(),
    )


def generate_html_with_agent_meta(
    model: str,
    user_prompt: str,
    iteration: int,
    temperature: Optional[float] = None,
    seed: Optional[int] = None,
    disable_cache: bool = False,
    model_display_name: Optional[str] = None,
    provider_config: Optional[Dict[str, Any]] = None,
    runtime_log_dir: Optional[str] = None,
    agent_config: Optional[Dict[str, Any]] = None,
) -> tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Generate HTML through a sandboxed Inspect ReAct agent.

    Agent generations use the same cross-run cache identity as direct generation
    and additionally cache a transcript sidecar so agent-mode artifacts can be
    reconstructed without re-running the sandbox.
    """
    base_system_prompt = get_base_system_prompt()
    custom_instructions = get_custom_instructions()
    effective_system_prompt = get_effective_system_prompt()
    prompt_hash_value, cache_file, meta_file = _cache_artifacts(model, user_prompt, iteration, seed, generation_mode="agent")

    if not disable_cache and cache_file.exists():
        cached_html, cached_meta, cached_transcript, reason = _load_cached_agent_generation(
            cache_file=cache_file,
            meta_file=meta_file,
            prompt_hash_value=prompt_hash_value,
            temperature=temperature,
            seed=seed,
            model_display_name=model_display_name,
            base_system_prompt=base_system_prompt,
            custom_instructions=custom_instructions,
            effective_system_prompt=effective_system_prompt,
            runtime_log_dir=runtime_log_dir,
        )
        if cached_html is not None and cached_meta is not None and cached_transcript is not None:
            return cached_html, cached_meta, cached_transcript
        if reason is not None:
            _invalidate_cache_entry(cache_file)

    config = agent_config or {}
    user_limits = config.get("limits")
    limits_cfg = normalize_agent_limits(user_limits if isinstance(user_limits, dict) else None)

    sandbox_spec = _normalize_agent_sandbox_spec(config.get("sandbox") or default_agent_sandbox())
    use_browser = bool(config.get("use_browser", True))

    provider_kwargs = _build_provider_completion_kwargs(model, provider_config)
    model_args = {
        k: v
        for k, v in provider_kwargs.items()
        if k not in {"api_base"} and v is not None
    }

    result: AgentGenerationResult | None = None
    html = ""
    transcript: Dict[str, Any] = {}
    for trunc_attempt in range(TRUNCATION_RETRY_MAX + 1):
        result = run_agent_generation(
            model=model,
            prompt=user_prompt,
            sandbox=sandbox_spec,
            system_prompt=effective_system_prompt,
            log_dir=runtime_log_dir,
            model_base_url=provider_kwargs.get("api_base"),
            model_args=model_args,
            agent_limits=limits_cfg,
            use_browser=use_browser,
            temperature=temperature,
            seed=seed,
        )
        html = clean_generation(
            extract_agent_html_from_transcript(result.transcript, fallback_html=result.html)
        )
        transcript = normalize_agent_transcript(result.transcript, html)
        if is_probably_complete_html(html):
            break
        # Don't retry when a sample-level limit (working/time/token/cost/message)
        # already tripped — the next attempt would hit the same wall and double
        # the spend with no expected improvement.
        if result.limit_error:
            print(
                f"Agent hit limit ({result.limit_error}); skipping truncation retry "
                "to avoid duplicate cost."
            )
            break
        if trunc_attempt < TRUNCATION_RETRY_MAX:
            print("Detected truncated/incomplete agent HTML; retrying generation once...")

    assert result is not None
    meta = _build_generation_meta(
        cached=False,
        latency_s=result.elapsed_s,
        prompt_hash_value=prompt_hash_value,
        model_display_name=model_display_name,
        tokens_in=result.usage.get("prompt_tokens"),
        tokens_out=result.usage.get("completion_tokens"),
        total_tokens=result.usage.get("total_tokens"),
        cost_usd=result.usage.get("total_cost"),
        seed=seed,
        temperature=temperature,
        system_prompt=base_system_prompt,
        custom_instructions=custom_instructions,
        effective_system_prompt=effective_system_prompt,
    )
    meta["generation_mode"] = "inspect_react_agent"
    meta["agent_sandbox"] = format_agent_sandbox(result.sandbox)
    meta["agent_limit_error"] = result.limit_error
    meta["agent_limits"] = limits_cfg
    meta["agent_eval_path"] = result.eval_log_path
    meta["iteration"] = iteration

    if html and is_probably_complete_html(html) and not result.limit_error:
        _write_agent_generation_cache(
            cache_file=cache_file,
            meta_file=meta_file,
            html=html,
            model=model,
            model_display_name=model_display_name,
            prompt_hash_value=prompt_hash_value,
            meta=meta,
            transcript=transcript,
            eval_log_path=result.eval_log_path,
        )

    return html, meta, transcript


SKILL_TOKEN_TEST_CASE_PROMPT = "{{test_case_prompt}}"
SKILL_TOKEN_SKILL_ID = "{{skill_id}}"
SKILL_TOKEN_SKILL_PATH = "{{skill_path}}"
SKILL_TOKEN_PREVIOUS_SUBMISSION = "{{previous_submission}}"


def render_skill_turn_prompt(
    template: str,
    *,
    test_case_prompt: str,
    skill_id: str,
    skill_path: str,
    previous_submission: Optional[str],
) -> str:
    """Substitute supported skill-turn tokens."""
    out = template
    out = out.replace(SKILL_TOKEN_TEST_CASE_PROMPT, test_case_prompt)
    out = out.replace(SKILL_TOKEN_SKILL_ID, skill_id)
    out = out.replace(SKILL_TOKEN_SKILL_PATH, skill_path)
    out = out.replace(SKILL_TOKEN_PREVIOUS_SUBMISSION, previous_submission or "")
    return out


def _skill_turn_cache_file(
    model: str,
    prompt_hash_value: str,
    iteration: int,
    seed: Optional[int],
    skill_id: str,
    skill_files_hash: str,
    turn_index: int,
    cumulative_turn_hash: str,
) -> tuple[Path, Path]:
    seed_part = f"_s{seed}" if seed is not None else ""
    cache_file = CACHE_DIR / (
        f"{model}_{prompt_hash_value}{seed_part}_i{iteration}_agent_skill-{skill_id}"
        f"_sh{skill_files_hash}_t{turn_index}_{cumulative_turn_hash}.html"
    )
    return cache_file, _meta_path(cache_file)


def generate_html_with_skill_multi_turn(
    model: str,
    test_case_prompt: str,
    iteration: int,
    *,
    temperature: Optional[float] = None,
    seed: Optional[int] = None,
    disable_cache: bool = False,
    model_display_name: Optional[str] = None,
    provider_config: Optional[Dict[str, Any]] = None,
    runtime_log_dir: Optional[str] = None,
    agent_config: Optional[Dict[str, Any]] = None,
    skill_config: Dict[str, Any],
) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
    """Run a skill's multi-turn agent conversation.

    ``skill_config`` is a dict with keys:
      - id (str), host_dir (str), sandbox_mount_path (str),
        system_prompt_preamble (str), skill_files_hash (str),
        turns (list of {id, name, prompt}).

    Returns a tuple ``(turn_records, aggregate_conversation_payload)`` where
    ``turn_records`` is a list ordered by ``turn_index`` with entries::

        {
            "turn_id": str,
            "turn_index": int,
            "turn_name": str,
            "html": str,
            "meta": dict,             # generation meta for this turn
            "conversation": dict,     # transcript fragment for this turn
            "error": Optional[str],   # if the turn errored / was skipped
        }

    ``aggregate_conversation_payload`` stitches every turn's transcript into a
    single JSON document suitable for the run directory's ``.agent.json`` sidecar.
    """
    base_system_prompt = get_base_system_prompt()
    custom_instructions = get_custom_instructions()
    effective_system_prompt = get_effective_system_prompt()

    skill_id = skill_config["id"]
    host_dir = skill_config["host_dir"]
    sandbox_path = skill_config["sandbox_mount_path"]
    skill_files_hash = skill_config.get("skill_files_hash") or ""
    turns = list(skill_config.get("turns") or [])
    if not turns:
        raise ValueError(f"Skill '{skill_id}' has no turns configured")

    config = agent_config or {}
    user_limits = config.get("limits")
    limits_cfg = normalize_agent_limits(user_limits if isinstance(user_limits, dict) else None)
    sandbox_spec = _normalize_agent_sandbox_spec(config.get("sandbox") or default_agent_sandbox())
    use_browser = bool(config.get("use_browser", True))
    skill_mount = {"host_dir": host_dir, "sandbox_path": sandbox_path}

    provider_kwargs = _build_provider_completion_kwargs(model, provider_config)
    model_args = {
        k: v for k, v in provider_kwargs.items()
        if k not in {"api_base"} and v is not None
    }

    # We base the per-turn cache identity on the compute_prompt_hash of the
    # underlying test case prompt (which already incorporates system prompt +
    # skill preamble because they are set via configure_prompts) plus the
    # cumulative hash of rendered turn prompts up to and including this turn.
    base_prompt_hash_value = compute_prompt_hash(test_case_prompt)

    turn_records: list[Dict[str, Any]] = []
    rendered_prompts: list[str] = []
    seed_messages: list[Dict[str, str]] = []
    previous_submission: Optional[str] = None
    aborted_reason: Optional[str] = None

    for turn_index, turn in enumerate(turns):
        tid = turn["id"]
        tname = turn.get("name") or tid
        rendered = render_skill_turn_prompt(
            turn["prompt"],
            test_case_prompt=test_case_prompt,
            skill_id=skill_id,
            skill_path=sandbox_path,
            previous_submission=previous_submission,
        )
        rendered_prompts.append(rendered)
        cumulative_turn_hash = prompt_hash(_PROMPT_JOINER.join(rendered_prompts))

        if aborted_reason is not None:
            turn_records.append({
                "turn_id": tid,
                "turn_index": turn_index,
                "turn_name": tname,
                "html": "",
                "meta": _build_generation_meta(
                    cached=False,
                    latency_s=0.0,
                    prompt_hash_value=base_prompt_hash_value,
                    model_display_name=model_display_name,
                    seed=seed,
                    temperature=temperature,
                    system_prompt=base_system_prompt,
                    custom_instructions=custom_instructions,
                    effective_system_prompt=effective_system_prompt,
                ) | {
                    "generation_mode": "inspect_react_agent",
                    "agent_sandbox": format_agent_sandbox(sandbox_spec),
                    "agent_limit_error": aborted_reason,
                    "agent_limits": limits_cfg,
                    "iteration": iteration,
                },
                "conversation": {
                    "format": "inspect_agent_conversation/v1",
                    "turn_index": turn_index,
                    "turn_id": tid,
                    "skipped": True,
                    "skip_reason": aborted_reason,
                },
                "error": aborted_reason,
            })
            continue

        cache_file, meta_file = _skill_turn_cache_file(
            model,
            base_prompt_hash_value,
            iteration,
            seed,
            skill_id,
            skill_files_hash,
            turn_index,
            cumulative_turn_hash,
        )

        used_cache = False
        turn_html = ""
        turn_meta: Dict[str, Any] = {}
        turn_transcript: Dict[str, Any] = {}

        if not disable_cache and cache_file.exists():
            cached_html, cached_meta, cached_transcript, reason = _load_cached_agent_generation(
                cache_file=cache_file,
                meta_file=meta_file,
                prompt_hash_value=base_prompt_hash_value,
                temperature=temperature,
                seed=seed,
                model_display_name=model_display_name,
                base_system_prompt=base_system_prompt,
                custom_instructions=custom_instructions,
                effective_system_prompt=effective_system_prompt,
                runtime_log_dir=runtime_log_dir,
            )
            if cached_html is not None and cached_meta is not None and cached_transcript is not None:
                turn_html = cached_html
                turn_meta = cached_meta
                turn_transcript = cached_transcript
                used_cache = True
            elif reason is not None:
                _invalidate_cache_entry(cache_file)

        if not used_cache:
            try:
                result: AgentGenerationResult = run_agent_generation(
                    model=model,
                    prompt=rendered,
                    sandbox=sandbox_spec,
                    system_prompt=effective_system_prompt,
                    log_dir=runtime_log_dir,
                    model_base_url=provider_kwargs.get("api_base"),
                    model_args=model_args,
                    agent_limits=limits_cfg,
                    use_browser=use_browser,
                    temperature=temperature,
                    seed=seed,
                    skill_mount=skill_mount,
                    seed_messages=seed_messages if seed_messages else None,
                )
            except Exception as exc:  # hard failure during this turn
                aborted_reason = f"turn-{turn_index}-error:{exc}"
                turn_records.append({
                    "turn_id": tid,
                    "turn_index": turn_index,
                    "turn_name": tname,
                    "html": "",
                    "meta": _build_generation_meta(
                        cached=False,
                        latency_s=0.0,
                        prompt_hash_value=base_prompt_hash_value,
                        model_display_name=model_display_name,
                        seed=seed,
                        temperature=temperature,
                        system_prompt=base_system_prompt,
                        custom_instructions=custom_instructions,
                        effective_system_prompt=effective_system_prompt,
                    ) | {
                        "generation_mode": "inspect_react_agent",
                        "agent_sandbox": format_agent_sandbox(sandbox_spec),
                        "agent_limit_error": aborted_reason,
                        "agent_limits": limits_cfg,
                        "iteration": iteration,
                    },
                    "conversation": {
                        "format": "inspect_agent_conversation/v1",
                        "turn_index": turn_index,
                        "turn_id": tid,
                        "error": aborted_reason,
                    },
                    "error": aborted_reason,
                })
                continue

            turn_html = clean_generation(
                extract_agent_html_from_transcript(result.transcript, fallback_html=result.html)
            )
            turn_transcript = normalize_agent_transcript(result.transcript, turn_html)
            turn_meta = _build_generation_meta(
                cached=False,
                latency_s=result.elapsed_s,
                prompt_hash_value=base_prompt_hash_value,
                model_display_name=model_display_name,
                tokens_in=result.usage.get("prompt_tokens"),
                tokens_out=result.usage.get("completion_tokens"),
                total_tokens=result.usage.get("total_tokens"),
                cost_usd=result.usage.get("total_cost"),
                seed=seed,
                temperature=temperature,
                system_prompt=base_system_prompt,
                custom_instructions=custom_instructions,
                effective_system_prompt=effective_system_prompt,
            )
            turn_meta["generation_mode"] = "inspect_react_agent"
            turn_meta["agent_sandbox"] = format_agent_sandbox(result.sandbox)
            turn_meta["agent_limit_error"] = result.limit_error
            turn_meta["agent_limits"] = limits_cfg
            turn_meta["agent_eval_path"] = result.eval_log_path
            turn_meta["iteration"] = iteration

            if turn_html and is_probably_complete_html(turn_html) and not result.limit_error:
                _write_agent_generation_cache(
                    cache_file=cache_file,
                    meta_file=meta_file,
                    html=turn_html,
                    model=model,
                    model_display_name=model_display_name,
                    prompt_hash_value=base_prompt_hash_value,
                    meta=turn_meta,
                    transcript=turn_transcript,
                    eval_log_path=result.eval_log_path,
                )

            if result.limit_error:
                aborted_reason = result.limit_error

        turn_records.append({
            "turn_id": tid,
            "turn_index": turn_index,
            "turn_name": tname,
            "html": turn_html,
            "meta": turn_meta,
            "conversation": turn_transcript,
            "error": None,
        })

        # Extend the conversation history seed for the next turn: the latest user
        # prompt that was sent, plus the assistant's submitted HTML.
        seed_messages.append({"role": "user", "content": rendered})
        if turn_html:
            seed_messages.append({"role": "assistant", "content": turn_html})
        previous_submission = turn_html

    aggregate_conversation = {
        "format": "inspect_agent_conversation/v1+skill-multi-turn",
        "skill_id": skill_id,
        "sandbox": sandbox_spec if isinstance(sandbox_spec, tuple) else [str(sandbox_spec)],
        "sandbox_mount_path": sandbox_path,
        "turns": [
            {
                "turn_id": tr["turn_id"],
                "turn_index": tr["turn_index"],
                "turn_name": tr["turn_name"],
                "rendered_prompt": rendered_prompts[tr["turn_index"]] if tr["turn_index"] < len(rendered_prompts) else None,
                "conversation": tr["conversation"],
                "error": tr.get("error"),
            }
            for tr in turn_records
        ],
    }

    return turn_records, aggregate_conversation
