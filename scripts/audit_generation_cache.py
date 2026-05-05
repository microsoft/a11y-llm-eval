#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple


DEFAULT_CACHE_DIR = Path(".cache/generations")

_SKILL_ID_RE = re.compile(r"_skill-([^_]+)")

STRONG_SIGNAL_RULES: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    (
        "repo-doc-read",
        re.compile(r"/workspace/docs/features-and-acceptance\.md"),
    ),
    (
        "instruction-set-config-read",
        re.compile(r"/workspace/config/default_instruction_sets\.yaml"),
    ),
    (
        "skills-config-read",
        re.compile(r"/workspace/config/default_skills\.yaml"),
    ),
    (
        "cache-read",
        re.compile(r"/workspace/\.cache/generations(?:/|\b)"),
    ),
    (
        "variant-sandbox-read",
        re.compile(r"/workspace/runs/.*/sandbox/variants/"),
    ),
    (
        "other-skill-sandbox-read",
        re.compile(r"/workspace/runs/.*/sandbox/skills/"),
    ),
    (
        "repo-custom-instructions",
        re.compile(r"You are working in the \*\*A11y LLM Evaluation Harness\*\* codebase\."),
    ),
)

WEAK_SIGNAL_RULES: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    (
        "git-status",
        re.compile(r"\bgit status\b"),
    ),
)


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _base_cache_file_from_sidecar(path: Path) -> Path:
    suffixes = [".meta.json", ".agent.json", ".session.jsonl", ".sha256"]
    text = str(path)
    for suffix in suffixes:
        if text.endswith(suffix):
            return Path(text[: -len(suffix)])
    return path


def _iter_cache_entries(cache_dir: Path) -> Iterator[Path]:
    seen = set()
    if not cache_dir.exists():
        return
    for path in sorted(cache_dir.iterdir()):
        if path.name.startswith(".") or path.is_dir():
            continue
        base = _base_cache_file_from_sidecar(path)
        if base.suffix != ".html":
            continue
        if base in seen:
            continue
        seen.add(base)
        yield base


def _variant_kind(cache_file: Path, meta: Optional[Dict[str, Any]]) -> str:
    if _extract_skill_id(cache_file):
        return "skill"
    if meta and meta.get("custom_instructions"):
        return "instruction-set"
    return "control"


def _extract_skill_id(cache_file: Path) -> Optional[str]:
    match = _SKILL_ID_RE.search(cache_file.name)
    if not match:
        return None
    return match.group(1)


def _walk_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)
        return
    if isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)


def _collect_signal_hits(texts: Iterable[str], cache_file: Path, variant_kind: str) -> List[Dict[str, str]]:
    hits: List[Dict[str, str]] = []
    skill_id = _extract_skill_id(cache_file)
    expected_instruction_path = variant_kind == "instruction-set"
    expected_variant_path = variant_kind == "instruction-set"
    expected_skill_path = variant_kind == "skill"
    for text in texts:
        for label, pattern in STRONG_SIGNAL_RULES:
            if not pattern.search(text):
                continue
            if label == "variant-sandbox-read" and expected_variant_path:
                continue
            if label == "other-skill-sandbox-read" and expected_skill_path:
                continue
            hits.append({"severity": "strong", "label": label, "excerpt": _excerpt(text, pattern)})
        for label, pattern in WEAK_SIGNAL_RULES:
            if pattern.search(text):
                hits.append({"severity": "weak", "label": label, "excerpt": _excerpt(text, pattern)})

        if ".github/copilot-instructions.md" in text and not expected_instruction_path:
            hits.append(
                {
                    "severity": "strong",
                    "label": "unexpected-copilot-instructions",
                    "excerpt": _trim_excerpt(text),
                }
            )
        if skill_id:
            if "/sandbox/skills/" in text and skill_id not in text:
                hits.append(
                    {
                        "severity": "strong",
                        "label": "different-skill-reference",
                        "excerpt": _trim_excerpt(text),
                    }
                )
        elif "skill-" in cache_file.name or variant_kind != "control":
            pass
        elif "skill-" in text or "skill-building-" in text:
            hits.append(
                {
                    "severity": "strong",
                    "label": "unexpected-skill-reference",
                    "excerpt": _trim_excerpt(text),
                }
            )
    return _dedupe_hits(hits)


def _excerpt(text: str, pattern: re.Pattern[str], radius: int = 90) -> str:
    match = pattern.search(text)
    if not match:
        return _trim_excerpt(text, radius=radius)
    start = max(match.start() - radius, 0)
    end = min(match.end() + radius, len(text))
    return text[start:end].replace("\n", "\\n")


def _trim_excerpt(text: str, radius: int = 180) -> str:
    compact = text.replace("\n", "\\n")
    if len(compact) <= radius:
        return compact
    return compact[: radius - 3] + "..."


def _dedupe_hits(hits: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    deduped = []
    for hit in hits:
        key = (hit["severity"], hit["label"], hit["excerpt"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
    return deduped


def audit_cache_entry(cache_file: Path) -> Dict[str, Any]:
    meta_path = cache_file.with_suffix(cache_file.suffix + ".meta.json")
    transcript_path = cache_file.with_suffix(cache_file.suffix + ".agent.json")
    meta = _load_json(meta_path)
    variant_kind = _variant_kind(cache_file, meta)
    result: Dict[str, Any] = {
        "cache_file": str(cache_file),
        "meta_file": str(meta_path),
        "transcript_file": str(transcript_path),
        "variant_kind": variant_kind,
        "status": "no_evidence",
        "signals": [],
    }

    if not transcript_path.exists():
        result["status"] = "error"
        result["error"] = "missing_transcript"
        return result

    transcript = _load_json(transcript_path)
    if transcript is None:
        result["status"] = "error"
        result["error"] = "invalid_transcript"
        return result

    texts = list(_walk_strings(transcript))
    if meta is not None:
        texts.extend(_walk_strings(meta))
    signals = _collect_signal_hits(texts, cache_file, variant_kind)
    result["signals"] = signals

    if any(hit["severity"] == "strong" for hit in signals):
        result["status"] = "contaminated"
    elif signals:
        result["status"] = "suspicious"

    return result


def audit_cache_dir(cache_dir: Path) -> Dict[str, Any]:
    entries = [audit_cache_entry(cache_file) for cache_file in _iter_cache_entries(cache_dir)]
    summary = {
        "cache_dir": str(cache_dir),
        "total_entries": len(entries),
        "status_counts": dict(Counter(entry["status"] for entry in entries)),
        "variant_counts": dict(Counter(entry["variant_kind"] for entry in entries)),
    }
    return {"summary": summary, "entries": entries}


def _format_text_report(report: Dict[str, Any], only_flagged: bool) -> str:
    lines = []
    summary = report["summary"]
    lines.append(f"Cache dir: {summary['cache_dir']}")
    lines.append(f"Entries: {summary['total_entries']}")
    lines.append("Status counts: " + _format_counter(summary["status_counts"]))
    lines.append("Variant counts: " + _format_counter(summary["variant_counts"]))
    lines.append("")
    for entry in report["entries"]:
        if only_flagged and entry["status"] == "no_evidence":
            continue
        lines.append(f"[{entry['status']}] {entry['variant_kind']} {entry['cache_file']}")
        if entry.get("error"):
            lines.append(f"  error: {entry['error']}")
            continue
        for hit in entry["signals"]:
            lines.append(f"  - {hit['severity']} {hit['label']}: {hit['excerpt']}")
    return "\n".join(lines).rstrip() + "\n"


def _format_counter(counter: Dict[str, int]) -> str:
    if not counter:
        return "none"
    return ", ".join(f"{key}={counter[key]}" for key in sorted(counter))


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit generation cache entries for contamination signals.")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output", type=Path, help="Write the report to a file instead of stdout.")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include no-evidence entries in text output. JSON output always includes all entries.",
    )
    args = parser.parse_args()

    report = audit_cache_dir(args.cache_dir)
    if args.format == "json":
        rendered = json.dumps(report, indent=2) + "\n"
    else:
        rendered = _format_text_report(report, only_flagged=not args.all)

    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

    status_counts = report["summary"]["status_counts"]
    return 1 if status_counts.get("contaminated") else 0


if __name__ == "__main__":
    raise SystemExit(main())