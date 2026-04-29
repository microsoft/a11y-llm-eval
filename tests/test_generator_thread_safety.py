"""Tests verifying that generation functions are thread-safe when prompt
config is passed explicitly (Phase 1 fix)."""

import threading
from unittest.mock import patch, MagicMock
from a11y_llm_tests import generator


def _fake_agent_result(html="<html><body>ok</body></html>"):
    """Build a minimal AgentGenerationResult mock."""
    from a11y_llm_tests.copilot_runtime import AgentGenerationResult
    return AgentGenerationResult(
        html=html,
        transcript={"format": "copilot_agent_conversation/v1", "events": [], "output_source": "message"},
        usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        elapsed_s=0.5,
        sandbox="docker:test",
        limit_error=None,
        session_log_path=None,
    )


def test_concurrent_calls_with_different_instructions_do_not_interfere(tmp_path):
    """Two threads call generate_html_with_agent_meta with different
    output_format_instructions. Neither should see the other's config."""
    results: dict[str, str] = {}
    errors: list[str] = []

    def _gen(thread_id: str, ofi: str):
        try:
            # Use disable_cache=True and no sandbox_workdir to avoid
            # path-translation validation against the workspace root.
            html, meta, _ = generator.generate_html_with_agent_meta(
                "test-model",
                f"prompt for {thread_id}",
                0,
                disable_cache=True,
                output_format_instructions=ofi,
                custom_instructions_override=f"custom for {thread_id}",
            )
            results[thread_id] = meta.get("output_format_instructions", "")
        except Exception as exc:
            errors.append(f"{thread_id}: {exc}")

    # Apply the mock at module level so both threads see it.
    with patch.object(generator, "run_agent_generation_sync", return_value=_fake_agent_result()):
        t1 = threading.Thread(target=_gen, args=("A", "Instructions-A"))
        t2 = threading.Thread(target=_gen, args=("B", "Instructions-B"))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    assert not errors, errors
    assert results["A"] == "Instructions-A"
    assert results["B"] == "Instructions-B"


def test_compute_prompt_hash_explicit_params_independent_of_globals():
    """compute_prompt_hash with explicit params ignores module globals."""
    generator.configure_prompts("GLOBAL instructions", "GLOBAL custom")
    h_explicit = generator.compute_prompt_hash(
        "user prompt",
        output_format_instructions="EXPLICIT instructions",
        custom_instructions="EXPLICIT custom",
    )
    h_global = generator.compute_prompt_hash("user prompt")
    assert h_explicit != h_global

    # Verify explicit params are deterministic
    h_explicit2 = generator.compute_prompt_hash(
        "user prompt",
        output_format_instructions="EXPLICIT instructions",
        custom_instructions="EXPLICIT custom",
    )
    assert h_explicit == h_explicit2

    # Cleanup
    generator.configure_prompts(None, None)


def test_compute_prompt_hash_none_params_use_globals():
    """When explicit params are None, compute_prompt_hash uses module globals."""
    generator.configure_prompts("Global OFI", "Global CI")
    h1 = generator.compute_prompt_hash("prompt")
    h2 = generator.compute_prompt_hash(
        "prompt",
        output_format_instructions=None,
        custom_instructions=None,
    )
    # None means "use the global", so both should match
    assert h1 == h2

    # Cleanup
    generator.configure_prompts(None, None)
