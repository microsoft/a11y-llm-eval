"""LLM HTML generation & caching layer."""
from __future__ import annotations
import hashlib, os, time, random
from pathlib import Path
from typing import Tuple, Dict, Any, Optional
import json
import litellm

from .utils import (
    atomic_write_bytes,
    atomic_write_text,
    is_probably_complete_html,
    read_and_validate_cached_html,
    write_sha256_sidecar,
)

CACHE_DIR = Path(".cache/generations")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Retry policy for litellm calls
RETRY_MAX_ATTEMPTS = 5
RETRY_BASE_DELAY = 1.0  # seconds
RETRY_MAX_DELAY = 60.0  # seconds

# If we detect a truncated HTML document (often from partial writes or model cutoffs),
# regenerate once before returning.
TRUNCATION_RETRY_MAX = 1

# Default output budget. Many Anthropic/Claude routes default to ~4096 if not explicitly set.
DEFAULT_MAX_TOKENS = 16384

_PROVIDER_ENV_DEBUG_VARS: dict[str, tuple[str, ...]] = {
    "azure": ("AZURE_API_BASE", "AZURE_API_KEY", "AZURE_API_VERSION"),
    "azure_ai": ("AZURE_AI_API_BASE", "AZURE_AI_API_KEY", "AZURE_AI_API_VERSION"),
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
    """Heuristic for whether a LiteLLM model routes to Anthropic.

    In this repo, Anthropic models are typically configured as `claude-*` in
    config/models.yaml, but LiteLLM also supports explicit provider prefixes.
    """

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
    """Heuristic for whether a LiteLLM model is a Codex-style deployment.

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


def _get_model_provider(model: str) -> str:
    m = (model or "").strip()
    if "/" in m:
        return m.split("/", 1)[0].strip().lower() or "unknown"
    return "unknown"


def _format_model_debug_label(model: str, model_display_name: Optional[str] = None) -> str:
    display = (model_display_name or "").strip()
    if display and display != model:
        return f"{display} [{model}]"
    return model


def _format_provider_auth_debug(model: str) -> str:
    provider = _get_model_provider(model)
    env_names = _PROVIDER_ENV_DEBUG_VARS.get(provider)
    if not env_names:
        return f"provider={provider}"
    env_status = ", ".join(
        f"{name}={'set' if os.environ.get(name) else 'missing'}" for name in env_names
    )
    return f"provider={provider}; auth_env[{env_status}]"


def _build_provider_completion_kwargs(model: str, provider_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    provider = _get_model_provider(model)
    config = provider_config or {}
    auth_cfg = config.get("auth") if isinstance(config, dict) else None
    if not isinstance(auth_cfg, dict):
        return {}

    mode = str(auth_cfg.get("mode") or "").strip().lower()
    if not mode or mode == "env":
        return {}

    if mode != "default_azure_credential":
        raise RuntimeError(f"Unsupported auth mode for provider '{provider}': {mode}")

    if provider not in {"azure", "azure_ai"}:
        raise RuntimeError(
            f"auth.mode=default_azure_credential is only supported for Azure providers, got '{provider}'"
        )

    try:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    except ImportError as exc:
        raise RuntimeError(
            "Model provider is configured with auth.mode=default_azure_credential, but azure-identity is not installed"
        ) from exc

    if provider == "azure_ai":
        default_api_base_env = "AZURE_AI_API_BASE"
        default_api_version_env = "AZURE_AI_API_VERSION"
    else:
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
    # Keep only first <html>...</html>
    lower = raw.lower()
    if "<html" in lower and "</html>" in lower:
        start = lower.index("<html")
        end = lower.index("</html>") + len("</html>")
        raw = raw[start:end]
    return raw.strip()


def _meta_path(cache_file: Path) -> Path:
    return cache_file.with_suffix(cache_file.suffix + ".meta.json")


def _invalidate_cache_entry(cache_file: Path) -> None:
    """Best-effort removal of a corrupted cache entry (html + sidecars)."""
    for p in [
        cache_file,
        cache_file.with_suffix(cache_file.suffix + ".sha256"),
        _meta_path(cache_file),
    ]:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


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
    h = compute_prompt_hash(user_prompt)
    # Incorporate seed into cache identity for sampling diversity
    seed_part = f"_s{seed}" if seed is not None else ""
    iteration_part = f"_i{iteration}"
    cache_file = CACHE_DIR / f"{model}_{h}{seed_part}{iteration_part}.html"
    meta_file = _meta_path(cache_file)

    truncated_cache_files: list[str] = []
    truncated_cache_reasons: dict[str, str] = {}
    if not disable_cache and cache_file.exists():
        cached_html, reason = read_and_validate_cached_html(cache_file)
        if cached_html is not None:
            html = cached_html
            meta: Dict[str, Any] = {
                "cached": True,
                "latency_s": 0.0,
                "prompt_hash": h,
                "model_display_name": model_display_name,
                "tokens_in": None,
                "tokens_out": None,
                "total_tokens": None,
                "cost_usd": None,
                "seed": seed,
                "temperature": temperature,
                "system_prompt": base_system_prompt,
                "custom_instructions": custom_instructions,
                "effective_system_prompt": effective_system_prompt,
            }
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
                        ]
                    })
                except Exception:
                    pass  # ignore malformed meta
            return html, meta

        # Corrupted/partial cache entry; either invalidate (default) or record for debug.
        if debug_truncated_cache:
            truncated_cache_files.append(str(cache_file))
            truncated_cache_reasons[str(cache_file)] = reason or "invalid"
        else:
            _invalidate_cache_entry(cache_file)

    start = time.time()
    litellm.drop_params = True
    model_debug_label = _format_model_debug_label(model, model_display_name)
    provider_auth_debug = _format_provider_auth_debug(model)
    print(
        f"Generating HTML with model={model_debug_label}, temp={temperature}, seed={seed} "
        f"({provider_auth_debug})..."
    )

    # Only set a default output token budget for Anthropic/Claude.
    # Other providers have their own defaults/limits; passing a large max_tokens
    # everywhere can change behavior unexpectedly.
    effective_max_tokens: Optional[int] = DEFAULT_MAX_TOKENS if _is_anthropic_model(model) else None

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
        # Some providers attach stop_reason at the top level.
        if stop_reason is None:
            stop_reason = getattr(resp, "stop_reason", None) or getattr(resp, "stopReason", None)
        return finish_reason, stop_reason

    def _call_litellm_with_retries():
        resp = None
        last_exc: Optional[BaseException] = None
        for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
            try:
                kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": effective_system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "seed": seed,
                }
                if temperature is not None and not _is_codex_model(model):
                    kwargs["temperature"] = temperature
                if effective_max_tokens is not None:
                    kwargs["max_tokens"] = effective_max_tokens
                kwargs.update(_build_provider_completion_kwargs(model, provider_config))

                resp = litellm.completion(**kwargs)
                if resp and getattr(resp, "choices", None) and len(resp.choices) > 0:
                    return resp
                last_exc = RuntimeError("litellm returned no choices")
            except Exception as e:
                last_exc = e

            if attempt == RETRY_MAX_ATTEMPTS:
                break
            delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
            jitter = random.uniform(0, delay * 0.1)
            sleep_for = delay + jitter
            print(
                f"litellm call failed for model={model_debug_label} ({provider_auth_debug}) "
                f"(attempt {attempt}/{RETRY_MAX_ATTEMPTS}): {last_exc}; "
                f"retrying in {sleep_for:.1f}s..."
            )
            time.sleep(sleep_for)

        if last_exc:
            raise last_exc
        raise RuntimeError("litellm.completion failed with no response")

    resp = None
    html = None
    tokens_in = tokens_out = total_tokens = None
    cost_usd = None
    raw = None
    finish_reason = None
    stop_reason = None

    for trunc_attempt in range(TRUNCATION_RETRY_MAX + 1):
        resp = _call_litellm_with_retries()

        finish_reason, stop_reason = _extract_finish_and_stop_reason(resp)

        usage = getattr(resp, "usage", None) or getattr(resp, "_hidden_params", {}).get("usage") or {}
        tokens_in = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        tokens_out = usage.get("completion_tokens") if isinstance(usage, dict) else None
        total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None

        # Exit fast if we hit the provider output limit to avoid spending on additional generations.
        limit_hit = False
        if isinstance(finish_reason, str) and finish_reason.lower() == "length":
            limit_hit = True
        if isinstance(stop_reason, str) and stop_reason.lower() in {"max_tokens", "length", "token_limit", "tokens"}:
            limit_hit = True
        if effective_max_tokens is not None and tokens_out is not None and tokens_out >= (effective_max_tokens - 1):
            # Heuristic for providers that don't report finish_reason reliably.
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

        if is_probably_complete_html(html):
            break
        if trunc_attempt < TRUNCATION_RETRY_MAX:
            print("Detected truncated/incomplete HTML; retrying generation once...")

    elapsed = time.time() - start

    # Cache only if the output looks complete; never poison the cache with truncated HTML.
    cacheable = bool(html) and is_probably_complete_html(html)
    # In debug mode, preserve truncated cache files for inspection (don't overwrite them).
    should_write_cache = cacheable and not (debug_truncated_cache and truncated_cache_files)
    if should_write_cache:
        cache_file.parent.mkdir(exist_ok=True, parents=True)
        html_bytes = html.encode("utf-8")
        atomic_write_bytes(cache_file, html_bytes)
        write_sha256_sidecar(cache_file, html_bytes)

        meta_payload = {
            "model": model,
            "model_display_name": model_display_name,
            "prompt_hash": h,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
            "seed": seed,
            "temperature": temperature,
            "system_prompt": base_system_prompt,
            "custom_instructions": custom_instructions,
            "effective_system_prompt": effective_system_prompt,
        }
        try:
            atomic_write_text(meta_file, json.dumps(meta_payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    meta = {
        "cached": False,
        "latency_s": elapsed,
        "prompt_hash": h,
        "model_display_name": model_display_name,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "total_tokens": total_tokens,
        "cost_usd": cost_usd,
        "finish_reason": finish_reason,
        "stop_reason": stop_reason,
        "max_tokens": effective_max_tokens,
        "seed": seed,
        "temperature": temperature,
        "system_prompt": base_system_prompt,
        "custom_instructions": custom_instructions,
        "effective_system_prompt": effective_system_prompt,
    }
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
