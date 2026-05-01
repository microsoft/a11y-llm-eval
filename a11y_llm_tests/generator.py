"""HTML generation + caching layer.

All generations route through the GitHub Copilot SDK as agent sessions.
There is no direct (non-agent) generation path; the previous LiteLLM/Inspect
direct path was removed when we migrated to the Copilot SDK.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .copilot_runtime import (
    AgentGenerationResult,
    run_agent_generation_sync,
    run_skill_multi_turn_sync,
)
from .utils import (
    atomic_write_bytes,
    atomic_write_text,
    is_probably_complete_html,
    read_and_validate_cached_html,
    write_sha256_sidecar,
)

CACHE_DIR = Path(".cache/generations")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Default output-format instructions appended to each user prompt. Renamed
# from ``DEFAULT_SYSTEM_PROMPT`` once the harness stopped sending its own
# system_message and started suffixing the user prompt instead.
DEFAULT_OUTPUT_FORMAT_INSTRUCTIONS = (
    "Save your answer to `index.html`. Feel free to use separate CSS and JS "
    "files in the same directory."
)

# Truncation retry policy for agent generations whose final HTML reads as
# incomplete (e.g. missing </html>).
TRUNCATION_RETRY_MAX = 1

_PROMPT_JOINER = "\n|:|\n"
_configured_output_format_instructions: str = DEFAULT_OUTPUT_FORMAT_INSTRUCTIONS
_custom_instructions: Optional[str] = None
_runtime_log_dir: Optional[str] = None


# ---- prompt configuration ------------------------------------------------


def configure_prompts(
    output_format_instructions: Optional[str] = None,
    custom_instructions: Optional[str] = None,
) -> None:
    """Configure the base output-format instructions plus optional custom
    instructions text.

    Output-format instructions ("save your answer as index.html") are
    appended to each user prompt at generation time; they're a per-task
    instruction, not a persona/style customization.

    Custom instructions are delivered the way real Copilot users supply
    them: written to ``.github/copilot-instructions.md`` inside the
    agent's working directory so the SDK auto-discovers them. They are
    NOT appended to the user prompt. The text is still mixed into the
    cache key so changes invalidate cached generations correctly.

    Neither stream is sent as an SDK ``system_message``; the SDK's
    default agent system prompt is left intact.
    """
    global _configured_output_format_instructions, _custom_instructions
    base = (output_format_instructions or "").strip()
    _configured_output_format_instructions = base or DEFAULT_OUTPUT_FORMAT_INSTRUCTIONS
    if custom_instructions is None:
        _custom_instructions = None
    else:
        text = custom_instructions.rstrip("\n")
        _custom_instructions = text if text.strip() else None


def get_base_output_format_instructions() -> str:
    return _configured_output_format_instructions


def get_custom_instructions() -> Optional[str]:
    return _custom_instructions


def get_effective_output_format_instructions() -> str:
    """Combined view of base output-format + custom instructions.

    Retained for provenance in ``results.json`` so existing reports keep
    rendering both streams together. Generation-time prompt assembly no
    longer concatenates these (custom instructions are delivered as a
    file via :func:`materialize_custom_instructions_file`).
    """
    if _custom_instructions:
        return f"{_configured_output_format_instructions}\n\n{_custom_instructions}".strip()
    return _configured_output_format_instructions


COPILOT_INSTRUCTIONS_REL_PATH = Path(".github") / "copilot-instructions.md"


def materialize_custom_instructions_file(
    workdir: Optional[str],
    custom_instructions: Optional[str],
) -> Optional[str]:
    """Write custom instructions to ``<workdir>/.github/copilot-instructions.md``.

    The Copilot SDK auto-discovers this file from the session's
    ``working_directory`` (mirroring how a real user configures Copilot
    custom instructions for a repo). Returns the absolute path to the
    written file, or ``None`` if there's nothing to write.

    Stale files from a prior variant in the same workdir are removed so
    a control task following an instruction-set task doesn't inherit
    the previous variant's instructions.
    """
    if not workdir:
        return None
    target = Path(workdir) / COPILOT_INSTRUCTIONS_REL_PATH
    text = (custom_instructions or "").strip()
    if not text:
        try:
            if target.exists():
                target.unlink()
        except Exception:
            pass
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, text + "\n", encoding="utf-8")
    return str(target)


def configure_runtime(log_dir: Optional[str] = None) -> None:
    """Set the directory where Copilot session logs should be written."""
    global _runtime_log_dir
    _runtime_log_dir = log_dir


def prompt_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def compute_prompt_hash(
    user_prompt: str,
    *,
    output_format_instructions: Optional[str] = None,
    custom_instructions: Optional[str] = None,
) -> str:
    """Hash that identifies a unique generation request.

    When explicit ``output_format_instructions`` / ``custom_instructions``
    are provided they are used directly (thread-safe path). When omitted
    the module-level configured values are used (legacy / test compat).
    """
    ofi = output_format_instructions if output_format_instructions is not None else _configured_output_format_instructions
    ci = custom_instructions if custom_instructions is not None else (_custom_instructions or "")
    combined = _PROMPT_JOINER.join([ofi, ci, user_prompt])
    return prompt_hash(combined)


# ---- HTML cleanup --------------------------------------------------------


def clean_generation(raw: str) -> str:
    if "```" in raw:
        parts: List[str] = []
        inside = False
        for line in raw.splitlines():
            if line.strip().startswith("```"):
                inside = not inside
                continue
            if inside:
                parts.append(line)
        if parts:
            raw = "\n".join(parts)
    lower = raw.lower()
    if "<html" in lower and "</html>" in lower:
        html_start = lower.index("<html")
        doctype_start = lower.rfind("<!doctype", 0, html_start)
        start = doctype_start if doctype_start != -1 else html_start
        end = lower.index("</html>") + len("</html>")
        raw = raw[start:end]
    return raw.strip()


def extract_html_from_transcript(transcript: Dict[str, Any], fallback_html: str) -> str:
    """Walk a Copilot transcript and return the last assistant content that looks
    like an HTML document. Falls back to ``fallback_html`` when nothing matches.
    """
    if isinstance(transcript, dict):
        events = transcript.get("events")
        if isinstance(events, list):
            best = ""
            for ev in events:
                if not isinstance(ev, dict) or ev.get("type") != "assistant.message":
                    continue
                data = ev.get("data") or {}
                if isinstance(data, dict):
                    content = data.get("content") or ""
                    if isinstance(content, str) and "<html" in content.lower():
                        best = content
            if best:
                return best
        turns = transcript.get("turns")
        if isinstance(turns, list):
            for turn in reversed(turns):
                inner_events = (turn or {}).get("events") if isinstance(turn, dict) else None
                if not isinstance(inner_events, list):
                    continue
                for ev in reversed(inner_events):
                    if isinstance(ev, dict) and ev.get("type") == "assistant.message":
                        data = ev.get("data") or {}
                        if isinstance(data, dict):
                            content = data.get("content") or ""
                            if isinstance(content, str) and content.strip():
                                return content
    return fallback_html


# ---- cache helpers -------------------------------------------------------


def _meta_path(cache_file: Path) -> Path:
    return cache_file.with_suffix(cache_file.suffix + ".meta.json")


def _agent_transcript_cache_path(cache_file: Path) -> Path:
    return cache_file.with_suffix(cache_file.suffix + ".agent.json")


def _agent_session_cache_path(cache_file: Path) -> Path:
    return cache_file.with_suffix(cache_file.suffix + ".session.jsonl")


def _cache_artifacts(
    model: str,
    user_prompt: str,
    iteration: int,
    seed: Optional[int],
    *,
    output_format_instructions: Optional[str] = None,
    custom_instructions: Optional[str] = None,
) -> tuple[str, Path, Path]:
    h = compute_prompt_hash(
        user_prompt,
        output_format_instructions=output_format_instructions,
        custom_instructions=custom_instructions,
    )
    seed_part = f"_s{seed}" if seed is not None else ""
    iteration_part = f"_i{iteration}"
    cache_file = CACHE_DIR / f"{model}_{h}{seed_part}{iteration_part}_copilot_agent.html"
    return h, cache_file, _meta_path(cache_file)


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
    seed: Optional[int] = None,
    temperature: Optional[float] = None,
    output_format_instructions: Optional[str] = None,
    custom_instructions: Optional[str] = None,
    effective_output_format_instructions: Optional[str] = None,
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
        "seed": seed,
        "temperature": temperature,
        "output_format_instructions": output_format_instructions,
        "custom_instructions": custom_instructions,
        "effective_output_format_instructions": effective_output_format_instructions,
    }


def _load_cached_agent_generation(
    *,
    cache_file: Path,
    meta_file: Path,
    prompt_hash_value: str,
    temperature: Optional[float],
    seed: Optional[int],
    model_display_name: Optional[str],
    base_output_format_instructions: str,
    custom_instructions: Optional[str],
    effective_output_format_instructions: str,
    runtime_log_dir: Optional[str] = None,
    sandbox_workdir: Optional[str] = None,
) -> tuple[Optional[str], Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
    cached_html, reason = read_and_validate_cached_html(cache_file)
    if cached_html is None:
        return None, None, None, reason

    meta: Dict[str, Any] = _build_generation_meta(
        cached=True,
        latency_s=0.0,
        prompt_hash_value=prompt_hash_value,
        model_display_name=model_display_name,
        seed=seed,
        temperature=temperature,
        output_format_instructions=base_output_format_instructions,
        custom_instructions=custom_instructions,
        effective_output_format_instructions=effective_output_format_instructions,
    )
    if meta_file.exists():
        try:
            loaded = json.loads(meta_file.read_text(encoding="utf-8"))
            # Back-compat: older meta files used system_prompt /
            # effective_system_prompt before the rename. Read either name
            # but normalise to the new keys.
            _PROMPT_KEY_ALIASES = {
                "system_prompt": "output_format_instructions",
                "effective_system_prompt": "effective_output_format_instructions",
            }
            for k in [
                "tokens_in",
                "tokens_out",
                "total_tokens",
                "cost_usd",
                "output_format_instructions",
                "custom_instructions",
                "effective_output_format_instructions",
                "generation_mode",
                "agent_sandbox",
                "agent_limit_error",
                "agent_limits",
                "custom_instructions_delivery",
                "custom_instructions_path",
            ]:
                if k in loaded:
                    meta[k] = loaded.get(k)
            for legacy_key, new_key in _PROMPT_KEY_ALIASES.items():
                if legacy_key in loaded and meta.get(new_key) is None:
                    meta[new_key] = loaded.get(legacy_key)
        except Exception:
            pass

    if meta.get("agent_limit_error"):
        return None, None, None, "agent_limit_error_in_cache"

    transcript_file = _agent_transcript_cache_path(cache_file)
    try:
        transcript = json.loads(transcript_file.read_text(encoding="utf-8"))
    except Exception:
        return None, None, None, "missing_or_invalid_agent_transcript"

    if not isinstance(transcript, dict):
        return None, None, None, "missing_or_invalid_agent_transcript"

    repaired = clean_generation(extract_html_from_transcript(transcript, fallback_html=cached_html))
    if is_probably_complete_html(repaired):
        cached_html = repaired
        try:
            html_bytes = cached_html.encode("utf-8")
            atomic_write_bytes(cache_file, html_bytes)
            write_sha256_sidecar(cache_file, html_bytes)
        except Exception:
            pass

    meta["generation_mode"] = meta.get("generation_mode") or "copilot_agent"

    session_cache = _agent_session_cache_path(cache_file)
    restored_log_path = None
    if session_cache.exists() and runtime_log_dir:
        try:
            dest_dir = Path(runtime_log_dir)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / session_cache.name
            shutil.copy2(str(session_cache), str(dest))
            restored_log_path = str(dest)
        except Exception:
            pass
    meta["agent_session_log_path"] = restored_log_path
    _restore_sandbox_files_from_cache(cache_file, sandbox_workdir)
    return cached_html, meta, transcript, None


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
    session_log_path: Optional[str] = None,
    sandbox_workdir: Optional[str] = None,
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
        "output_format_instructions": meta.get("output_format_instructions"),
        "custom_instructions": meta.get("custom_instructions"),
        "effective_output_format_instructions": meta.get("effective_output_format_instructions"),
        "generation_mode": meta.get("generation_mode"),
        "agent_sandbox": meta.get("agent_sandbox"),
        "agent_limit_error": meta.get("agent_limit_error"),
        "agent_limits": meta.get("agent_limits"),
        "custom_instructions_delivery": meta.get("custom_instructions_delivery"),
        "custom_instructions_path": meta.get("custom_instructions_path"),
    }
    try:
        atomic_write_text(meta_file, json.dumps(meta_payload, indent=2), encoding="utf-8")
    except Exception:
        pass

    try:
        atomic_write_text(
            _agent_transcript_cache_path(cache_file),
            json.dumps(transcript, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass

    if session_log_path:
        src = Path(session_log_path)
        if src.exists():
            try:
                shutil.copy2(str(src), str(_agent_session_cache_path(cache_file)))
            except Exception:
                pass

    _cache_sandbox_files(cache_file, sandbox_workdir)


def _invalidate_cache_entry(cache_file: Path) -> None:
    for p in [
        cache_file,
        cache_file.with_suffix(cache_file.suffix + ".sha256"),
        _meta_path(cache_file),
        _agent_transcript_cache_path(cache_file),
        _agent_session_cache_path(cache_file),
    ]:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass
    files_dir = _sandbox_files_cache_dir(cache_file)
    if files_dir.is_dir():
        try:
            shutil.rmtree(files_dir)
        except Exception:
            pass


def _sandbox_files_cache_dir(cache_file: Path) -> Path:
    """Return the directory used to cache sandbox sibling files for *cache_file*."""
    return cache_file.with_suffix(cache_file.suffix + ".files")


def _cache_sandbox_files(cache_file: Path, sandbox_workdir: Optional[str]) -> None:
    """Snapshot non-hidden sibling files from the agent sandbox into the cache."""
    if not sandbox_workdir:
        return
    src = Path(sandbox_workdir)
    if not src.is_dir():
        return
    dest = _sandbox_files_cache_dir(cache_file)
    has_siblings = False
    for item in src.iterdir():
        if item.name == "index.html" or item.name.startswith("."):
            continue
        has_siblings = True
        break
    if not has_siblings:
        return
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name == "index.html" or item.name.startswith("."):
            continue
        try:
            target = dest / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
        except OSError:
            pass


def _restore_sandbox_files_from_cache(cache_file: Path, sandbox_workdir: Optional[str]) -> None:
    """Restore cached sibling files into the agent sandbox directory."""
    if not sandbox_workdir:
        return
    cached_dir = _sandbox_files_cache_dir(cache_file)
    if not cached_dir.is_dir():
        return
    dest = Path(sandbox_workdir)
    dest.mkdir(parents=True, exist_ok=True)
    for item in cached_dir.iterdir():
        try:
            target = dest / item.name
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True)
            else:
                shutil.copy2(item, target)
        except OSError:
            pass


# ---- sandbox label ------------------------------------------------------


def format_agent_sandbox(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, tuple) and len(value) == 2:
        return f"{value[0]}:{value[1]}"
    if isinstance(value, list) and len(value) == 2:
        return f"{value[0]}:{value[1]}"
    return str(value)


# ---- agent generation ---------------------------------------------------


def generate_html_with_agent_meta(
    model: str,
    user_prompt: str,
    iteration: int,
    *,
    temperature: Optional[float] = None,
    seed: Optional[int] = None,
    disable_cache: bool = False,
    model_display_name: Optional[str] = None,
    provider_config: Optional[Dict[str, Any]] = None,
    runtime_log_dir: Optional[str] = None,
    agent_config: Optional[Dict[str, Any]] = None,
    sandbox_workdir: Optional[str] = None,
    output_format_instructions: Optional[str] = None,
    custom_instructions_override: Optional[str] = None,
) -> tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Run a single-turn Copilot agent generation.

    When ``output_format_instructions`` and ``custom_instructions_override``
    are provided they are used directly (thread-safe). When omitted the
    module-global values set via :func:`configure_prompts` are used.
    """
    base_output_format_instructions = (
        output_format_instructions
        if output_format_instructions is not None
        else get_base_output_format_instructions()
    )
    custom_instructions = (
        custom_instructions_override
        if custom_instructions_override is not None
        else get_custom_instructions()
    )
    effective_output_format_instructions = (
        f"{base_output_format_instructions}\n\n{custom_instructions}".strip()
        if custom_instructions
        else base_output_format_instructions
    )
    log_dir = runtime_log_dir or _runtime_log_dir
    prompt_hash_value, cache_file, meta_file = _cache_artifacts(
        model, user_prompt, iteration, seed,
        output_format_instructions=base_output_format_instructions,
        custom_instructions=custom_instructions,
    )

    if not disable_cache and cache_file.exists():
        cached_html, cached_meta, cached_transcript, reason = _load_cached_agent_generation(
            cache_file=cache_file,
            meta_file=meta_file,
            prompt_hash_value=prompt_hash_value,
            temperature=temperature,
            seed=seed,
            model_display_name=model_display_name,
            base_output_format_instructions=base_output_format_instructions,
            custom_instructions=custom_instructions,
            effective_output_format_instructions=effective_output_format_instructions,
            runtime_log_dir=log_dir,
            sandbox_workdir=sandbox_workdir,
        )
        if cached_html is not None and cached_meta is not None and cached_transcript is not None:
            return cached_html, cached_meta, cached_transcript
        if reason is not None:
            _invalidate_cache_entry(cache_file)

    config = agent_config or {}
    limits = config.get("limits") or {}
    timeout_s = float(limits.get("timeout_s") or config.get("timeout_s") or 600.0)
    max_output_tokens = int(limits.get("max_output_tokens") or 64000)
    excluded_tools = config.get("excluded_tools") if isinstance(config.get("excluded_tools"), list) else None

    print(f"Generating HTML with model={model_display_name or model} (copilot_agent)...")

    result: AgentGenerationResult | None = None
    html = ""
    transcript: Dict[str, Any] = {}
    # Output-format / disk-write instructions are appended to the user
    # prompt (they are per-task instructions, not a persona). Custom
    # instructions are delivered separately as
    # ``<sandbox_workdir>/.github/copilot-instructions.md`` so the SDK
    # auto-discovers them the way a real Copilot user would configure
    # them for a repo. The SDK's default agent system message is left
    # intact in both cases.
    custom_instructions_path = materialize_custom_instructions_file(
        sandbox_workdir, custom_instructions
    )
    final_user_prompt = (
        f"{user_prompt}\n\n{base_output_format_instructions}".strip()
        if base_output_format_instructions
        else user_prompt
    )
    for trunc_attempt in range(TRUNCATION_RETRY_MAX + 1):
        result = run_agent_generation_sync(
            model=model,
            user_prompt=final_user_prompt,
            provider_config=provider_config,
            excluded_tools=excluded_tools,
            timeout_s=timeout_s,
            max_output_tokens=max_output_tokens,
            log_dir=log_dir,
            working_directory=sandbox_workdir,
        )
        html = clean_generation(extract_html_from_transcript(result.transcript, fallback_html=result.html))
        transcript = result.transcript
        if is_probably_complete_html(html):
            break
        if result.limit_error:
            print(f"Agent hit limit ({result.limit_error}); skipping truncation retry.")
            break
        if trunc_attempt < TRUNCATION_RETRY_MAX:
            print("Detected truncated agent HTML; retrying once...")

    assert result is not None

    # Determine how the HTML was sourced for provenance tracking.
    output_source = (result.transcript or {}).get("output_source") or "message"

    # Warn loudly when the agent failed to produce usable HTML so the user
    # understands *why* a test will fail rather than seeing a silent FAIL.
    if not html or not is_probably_complete_html(html):
        print(
            f"Warning: agent did not produce valid HTML "
            f"(model={model_display_name or model}, output_source={output_source}"
            f"{', limit_error=' + result.limit_error if result.limit_error else ''})"
        )

    meta = _build_generation_meta(
        cached=False,
        latency_s=result.elapsed_s,
        prompt_hash_value=prompt_hash_value,
        model_display_name=model_display_name,
        tokens_in=result.usage.get("prompt_tokens"),
        tokens_out=result.usage.get("completion_tokens"),
        total_tokens=result.usage.get("total_tokens"),
        seed=seed,
        temperature=temperature,
        output_format_instructions=base_output_format_instructions,
        custom_instructions=custom_instructions,
        effective_output_format_instructions=effective_output_format_instructions,
    )
    meta["generation_mode"] = "copilot_agent"
    meta["agent_sandbox"] = format_agent_sandbox(result.sandbox)
    meta["agent_limit_error"] = result.limit_error
    meta["agent_limits"] = {"timeout_s": timeout_s, "max_output_tokens": max_output_tokens}
    meta["agent_session_log_path"] = result.session_log_path
    meta["iteration"] = iteration
    meta["output_source"] = output_source
    meta["custom_instructions_delivery"] = (
        "copilot-instructions-file" if custom_instructions_path else "none"
    )
    meta["custom_instructions_path"] = custom_instructions_path

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
            session_log_path=result.session_log_path,
            sandbox_workdir=sandbox_workdir,
        )
    return html, meta, transcript


# ---- skill multi-turn ---------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONTAINER_WORKSPACE = "/workspace"

SKILL_TOKEN_TEST_CASE_PROMPT = "{{test_case_prompt}}"
SKILL_TOKEN_SKILL_ID = "{{skill_id}}"
SKILL_TOKEN_SKILL_PATH = "{{skill_path}}"
SKILL_TOKEN_PREVIOUS_SUBMISSION = "{{previous_submission}}"


def _host_skill_path_to_container(host_path: str) -> str:
    """Map a host-side skill directory to its container-side equivalent.

    The container mounts the repo at /workspace, so the container path is
    /workspace/<relative-to-repo-root>.
    """
    rel = Path(host_path).resolve().relative_to(_REPO_ROOT)
    return f"{_CONTAINER_WORKSPACE}/{rel.as_posix()}"


def render_skill_turn_prompt(
    template: str,
    *,
    test_case_prompt: str,
    skill_id: str,
    skill_path: str,
    previous_submission: Optional[str],
) -> str:
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
        f"{model}_{prompt_hash_value}{seed_part}_i{iteration}_copilot_agent_skill-{skill_id}"
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
    sandbox_workdir: Optional[str] = None,
    output_format_instructions: Optional[str] = None,
    custom_instructions_override: Optional[str] = None,
) -> tuple[list[Dict[str, Any]], Dict[str, Any]]:
    """Run a skill's multi-turn Copilot agent conversation.

    When ``output_format_instructions`` / ``custom_instructions_override``
    are provided they are used directly (thread-safe). Otherwise the module
    globals set via :func:`configure_prompts` are used.
    """
    base_output_format_instructions = (
        output_format_instructions
        if output_format_instructions is not None
        else get_base_output_format_instructions()
    )
    custom_instructions = (
        custom_instructions_override
        if custom_instructions_override is not None
        else get_custom_instructions()
    )
    effective_output_format_instructions = (
        f"{base_output_format_instructions}\n\n{custom_instructions}".strip()
        if custom_instructions
        else base_output_format_instructions
    )
    log_dir = runtime_log_dir or _runtime_log_dir

    skill_id = skill_config["id"]
    skill_dir_abs = skill_config["skill_dir_abs_path"]
    skill_files_hash = skill_config.get("skill_files_hash") or ""
    turns = list(skill_config.get("turns") or [])
    if not turns:
        raise ValueError(f"Skill '{skill_id}' has no turns configured")

    config = agent_config or {}
    limits = config.get("limits") or {}
    timeout_s = float(limits.get("timeout_s") or config.get("timeout_s") or 1200.0)
    max_output_tokens = int(limits.get("max_output_tokens") or 64000)
    excluded_tools = config.get("excluded_tools") if isinstance(config.get("excluded_tools"), list) else None

    base_prompt_hash_value = compute_prompt_hash(
        test_case_prompt,
        output_format_instructions=base_output_format_instructions,
        custom_instructions=custom_instructions,
    )

    rendered_prompts: list[str] = []
    cumulative_hashes: list[str] = []
    cache_hit_html: list[Optional[str]] = []
    cache_hit_transcripts: list[Optional[Dict[str, Any]]] = []
    cache_hit_meta: list[Optional[Dict[str, Any]]] = []
    all_cached = True
    previous_submission: Optional[str] = None
    for turn_index, turn in enumerate(turns):
        rendered = render_skill_turn_prompt(
            turn["prompt"],
            test_case_prompt=test_case_prompt,
            skill_id=skill_id,
            skill_path=_host_skill_path_to_container(skill_dir_abs),
            previous_submission=previous_submission,
        )
        rendered_prompts.append(rendered)
        cumulative_hashes.append(prompt_hash(_PROMPT_JOINER.join(rendered_prompts)))

        if disable_cache:
            cache_hit_html.append(None)
            cache_hit_transcripts.append(None)
            cache_hit_meta.append(None)
            all_cached = False
            previous_submission = None
            continue

        cache_file, meta_file = _skill_turn_cache_file(
            model,
            base_prompt_hash_value,
            iteration,
            seed,
            skill_id,
            skill_files_hash,
            turn_index,
            cumulative_hashes[turn_index],
        )
        if cache_file.exists():
            cached_html, cached_meta, cached_transcript, reason = _load_cached_agent_generation(
                cache_file=cache_file,
                meta_file=meta_file,
                prompt_hash_value=base_prompt_hash_value,
                temperature=temperature,
                seed=seed,
                model_display_name=model_display_name,
                base_output_format_instructions=base_output_format_instructions,
                custom_instructions=custom_instructions,
                effective_output_format_instructions=effective_output_format_instructions,
                runtime_log_dir=log_dir,
                sandbox_workdir=sandbox_workdir,
            )
            if cached_html is not None and cached_meta is not None and cached_transcript is not None:
                cache_hit_html.append(cached_html)
                cache_hit_meta.append(cached_meta)
                cache_hit_transcripts.append(cached_transcript)
                previous_submission = cached_html
                continue
            if reason is not None:
                _invalidate_cache_entry(cache_file)

        cache_hit_html.append(None)
        cache_hit_transcripts.append(None)
        cache_hit_meta.append(None)
        all_cached = False
        previous_submission = None

    if all_cached and cache_hit_html and all(h is not None for h in cache_hit_html):
        turn_records: list[Dict[str, Any]] = []
        for turn_index, turn in enumerate(turns):
            turn_records.append({
                "turn_id": turn["id"],
                "turn_index": turn_index,
                "turn_name": turn.get("name") or turn["id"],
                "html": cache_hit_html[turn_index] or "",
                "meta": cache_hit_meta[turn_index] or {},
                "conversation": cache_hit_transcripts[turn_index] or {},
                "error": None,
            })
        aggregate_conversation = _build_skill_conversation_payload(
            skill_id=skill_id,
            sandbox_label="copilot_sdk:subprocess",
            skill_dir_abs=skill_dir_abs,
            turns=turn_records,
            rendered_prompts=rendered_prompts,
        )
        return turn_records, aggregate_conversation

    print(f"Generating skill multi-turn HTML model={model_display_name or model} skill={skill_id}...")
    # Output-format / disk-write instructions are appended onto each
    # turn's user prompt (every turn may ask the agent to update the
    # on-disk artifact). Custom instructions are delivered as
    # ``<sandbox_workdir>/.github/copilot-instructions.md`` so the SDK
    # auto-discovers them on the very first turn and they remain in
    # effect for the whole session. The SDK's default system message
    # stays intact.
    custom_instructions_path = materialize_custom_instructions_file(
        sandbox_workdir, custom_instructions
    )
    runtime_turn_prompts = (
        [f"{p}\n\n{base_output_format_instructions}".strip() for p in rendered_prompts]
        if base_output_format_instructions
        else list(rendered_prompts)
    )
    result = run_skill_multi_turn_sync(
        model=model,
        rendered_turn_prompts=runtime_turn_prompts,
        skill_dir_abs_path=skill_dir_abs,
        skill_id=skill_id,
        provider_config=provider_config,
        excluded_tools=excluded_tools,
        timeout_s=timeout_s,
        max_output_tokens=max_output_tokens,
        log_dir=log_dir,
        working_directory=sandbox_workdir,
    )

    turn_records: list[Dict[str, Any]] = []
    for turn_index, turn in enumerate(turns):
        per_turn = result.turns[turn_index] if turn_index < len(result.turns) else {}
        raw_html = per_turn.get("html") or ""
        turn_html = clean_generation(extract_html_from_transcript(per_turn.get("transcript") or {}, fallback_html=raw_html))
        turn_meta = _build_generation_meta(
            cached=False,
            latency_s=float(per_turn.get("elapsed_s") or 0.0),
            prompt_hash_value=base_prompt_hash_value,
            model_display_name=model_display_name,
            tokens_in=(per_turn.get("usage") or {}).get("prompt_tokens"),
            tokens_out=(per_turn.get("usage") or {}).get("completion_tokens"),
            total_tokens=(per_turn.get("usage") or {}).get("total_tokens"),
            seed=seed,
            temperature=temperature,
            output_format_instructions=base_output_format_instructions,
            custom_instructions=custom_instructions,
            effective_output_format_instructions=effective_output_format_instructions,
        )
        turn_meta.update({
            "generation_mode": "copilot_agent",
            "agent_sandbox": format_agent_sandbox(result.sandbox),
            "agent_limit_error": per_turn.get("limit_error"),
            "agent_limits": {"timeout_s": timeout_s},
            "agent_session_log_path": result.session_log_path,
            "iteration": iteration,
            "custom_instructions_delivery": (
                "copilot-instructions-file" if custom_instructions_path else "none"
            ),
            "custom_instructions_path": custom_instructions_path,
        })
        turn_records.append({
            "turn_id": turn["id"],
            "turn_index": turn_index,
            "turn_name": turn.get("name") or turn["id"],
            "html": turn_html,
            "meta": turn_meta,
            "conversation": per_turn.get("transcript") or {},
            "error": per_turn.get("limit_error"),
        })

        if turn_html and is_probably_complete_html(turn_html) and not per_turn.get("limit_error"):
            cache_file, meta_file = _skill_turn_cache_file(
                model,
                base_prompt_hash_value,
                iteration,
                seed,
                skill_id,
                skill_files_hash,
                turn_index,
                cumulative_hashes[turn_index],
            )
            _write_agent_generation_cache(
                cache_file=cache_file,
                meta_file=meta_file,
                html=turn_html,
                model=model,
                model_display_name=model_display_name,
                prompt_hash_value=base_prompt_hash_value,
                meta=turn_meta,
                transcript=per_turn.get("transcript") or {},
                session_log_path=result.session_log_path,
                sandbox_workdir=sandbox_workdir,
            )

    aggregate_conversation = _build_skill_conversation_payload(
        skill_id=skill_id,
        sandbox_label=result.sandbox or "copilot_sdk:subprocess",
        skill_dir_abs=skill_dir_abs,
        turns=turn_records,
        rendered_prompts=rendered_prompts,
    )
    return turn_records, aggregate_conversation


def _build_skill_conversation_payload(
    *,
    skill_id: str,
    sandbox_label: str,
    skill_dir_abs: str,
    turns: List[Dict[str, Any]],
    rendered_prompts: List[str],
) -> Dict[str, Any]:
    return {
        "format": "copilot_agent_conversation/v1+skill-multi-turn",
        "skill_id": skill_id,
        "sandbox": sandbox_label,
        "skill_dir": skill_dir_abs,
        "turns": [
            {
                "turn_id": tr["turn_id"],
                "turn_index": tr["turn_index"],
                "turn_name": tr["turn_name"],
                "rendered_prompt": rendered_prompts[tr["turn_index"]] if tr["turn_index"] < len(rendered_prompts) else None,
                "conversation": tr["conversation"],
                "error": tr.get("error"),
            }
            for tr in turns
        ],
    }
