"""Filesystem helpers used by report rendering."""

from __future__ import annotations

from pathlib import Path


def _read_text_if_available(path_str: str | None, run_dir: Path) -> str | None:
  if not path_str:
    return None
  raw_path = Path(path_str)
  candidates = []
  if raw_path.is_absolute():
    candidates.append(raw_path)
  else:
    candidates.append(run_dir / raw_path)
    candidates.append(Path.cwd() / raw_path)
    repo_root = run_dir.parent.parent
    candidates.append(repo_root / raw_path)

  for candidate in candidates:
    try:
      if candidate.exists() and candidate.is_file():
        return candidate.read_text(encoding="utf-8")
    except Exception:
      continue
  return None