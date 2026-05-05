from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_generation_cache.py"


def _write_entry(
    cache_dir: Path,
    name: str,
    *,
    meta: dict | None = None,
    transcript: dict | None = None,
) -> Path:
    cache_file = cache_dir / f"{name}.html"
    cache_file.write_text("<html></html>", encoding="utf-8")
    if meta is not None:
        cache_file.with_suffix(cache_file.suffix + ".meta.json").write_text(
            json.dumps(meta),
            encoding="utf-8",
        )
    if transcript is not None:
        cache_file.with_suffix(cache_file.suffix + ".agent.json").write_text(
            json.dumps(transcript),
            encoding="utf-8",
        )
    return cache_file


def _run_script(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--cache-dir", str(tmp_path), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def test_control_entry_with_repo_doc_read_is_contaminated(tmp_path: Path):
    _write_entry(
        tmp_path,
        "gpt-5.5_hash_i0_copilot_agent",
        meta={"generation_mode": "copilot_agent"},
        transcript={
            "events": [
                {
                    "type": "assistant.message",
                    "data": {
                        "content": "Read file: /workspace/docs/features-and-acceptance.md"
                    },
                }
            ]
        },
    )

    result = _run_script(tmp_path, "--format", "json")

    assert result.returncode == 1
    report = json.loads(result.stdout)
    assert report["summary"]["status_counts"] == {"contaminated": 1}
    assert report["entries"][0]["variant_kind"] == "control"
    assert report["entries"][0]["signals"][0]["label"] == "repo-doc-read"


def test_instruction_entry_can_reference_copilot_instructions_without_flag(tmp_path: Path):
    _write_entry(
        tmp_path,
        "gpt-5.5_hash_i0_copilot_agent",
        meta={"custom_instructions": "All output MUST be accessible."},
        transcript={
            "events": [
                {
                    "type": "assistant.message",
                    "data": {
                        "content": "Read file: /workspace/runs/2026-05-05/sandbox/variants/a11y/index/.github/copilot-instructions.md"
                    },
                }
            ]
        },
    )

    result = _run_script(tmp_path, "--format", "json")

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["entries"][0]["status"] == "no_evidence"
    assert report["entries"][0]["variant_kind"] == "instruction-set"


def test_missing_transcript_is_reported_as_error(tmp_path: Path):
    _write_entry(
        tmp_path,
        "gpt-5.5_hash_i0_copilot_agent",
        meta={"generation_mode": "copilot_agent"},
        transcript=None,
    )

    result = _run_script(tmp_path, "--format", "json")

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert report["entries"][0]["status"] == "error"
    assert report["entries"][0]["error"] == "missing_transcript"