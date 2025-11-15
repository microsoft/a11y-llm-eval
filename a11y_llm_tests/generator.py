"""LLM HTML generation & caching layer."""
from __future__ import annotations
import hashlib, time, random
from pathlib import Path
from typing import Tuple, Dict, Any, Optional
import json
import litellm

CACHE_DIR = Path(".cache/generations")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Retry policy for litellm calls
RETRY_MAX_ATTEMPTS = 5
RETRY_BASE_DELAY = 1.0  # seconds
RETRY_MAX_DELAY = 60.0  # seconds

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


def generate_html_with_meta(
    model: str,
    user_prompt: str,
    iteration: int,
    temperature: Optional[float] = None,
    seed: Optional[int] = None,
    disable_cache: bool = False,
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
    if not disable_cache and cache_file.exists():
        html = cache_file.read_text(encoding="utf-8")
        meta: Dict[str, Any] = {
            "cached": True,
            "latency_s": 0.0,
            "prompt_hash": h,
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
                        "tokens_in", "tokens_out", "total_tokens", "cost_usd",
                        "system_prompt", "custom_instructions", "effective_system_prompt",
                    ]
                })
            except Exception:
                pass  # ignore malformed meta
        return html, meta

    start = time.time()
    litellm.drop_params = True
    print(f"Generating HTML with model={model}, temp={temperature}, seed={seed}...")

    resp = None
    last_exc: Optional[BaseException] = None
    for attempt in range(1, RETRY_MAX_ATTEMPTS + 1):
        try:
            resp = litellm.completion(
                model=model,
                messages=[
                    {"role": "system", "content": effective_system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                seed=seed,
            )
            # Basic validation: ensure we have choices and text
            if resp and getattr(resp, "choices", None) and len(resp.choices) > 0:
                break
            # Treat missing choices as transient error
            last_exc = RuntimeError("litellm returned no choices")
        except Exception as e:
            last_exc = e

        # If we're here, we will retry unless this was the last attempt
        if attempt == RETRY_MAX_ATTEMPTS:
            break
        # Exponential backoff with jitter
        delay = min(RETRY_BASE_DELAY * (2 ** (attempt - 1)), RETRY_MAX_DELAY)
        jitter = random.uniform(0, delay * 0.1)
        sleep_for = delay + jitter
        print(f"litellm call failed (attempt {attempt}/{RETRY_MAX_ATTEMPTS}): {last_exc}; retrying in {sleep_for:.1f}s...")
        time.sleep(sleep_for)

    elapsed = time.time() - start

    if resp is None or not getattr(resp, "choices", None):
        # Raise the last exception or a generic one so callers can handle it
        if last_exc:
            raise last_exc
        raise RuntimeError("litellm.completion failed with no response")

    # Extract tokens & cost defensively
    usage = getattr(resp, "usage", None) or getattr(resp, "_hidden_params", {}).get("usage") or {}
    tokens_in = usage.get("prompt_tokens") if isinstance(usage, dict) else None
    tokens_out = usage.get("completion_tokens") if isinstance(usage, dict) else None
    total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None

    cost_usd = None
    # liteLLM often attaches response_cost either directly or hidden
    cost_usd = getattr(resp, "response_cost", None)
    if cost_usd is None:
        hidden = getattr(resp, "_hidden_params", {})
        if isinstance(hidden, dict):
            cost_usd = hidden.get("response_cost")

    raw = resp.choices[0].message.content
    html = clean_generation(raw)
    cache_file.parent.mkdir(exist_ok=True, parents=True)
    cache_file.write_text(html, encoding="utf-8")
    # Write meta file for future cache hits
    meta_payload = {
        "model": model,
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
        meta_file.write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")
    except Exception:
        pass

    meta = {
        "cached": False,
        "latency_s": elapsed,
        "prompt_hash": h,
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
    return html, meta


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
