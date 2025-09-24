"""Cache utilities for generation artifacts.

Currently minimal: provides helper to compose cache keys that account for model,
prompt hash, and optional seed, ensuring sampled generations can coexist.
"""

from pathlib import Path
from typing import Optional

CACHE_ROOT = Path('.cache')
CACHE_ROOT.mkdir(exist_ok=True)

def generation_cache_key(model: str, prompt_hash: str, seed: Optional[int] = None) -> str:
	"""Return a filename-safe cache key for a generation.

	Example: modelabc_deadbeef or modelabc_deadbeef_s42
	"""
	if seed is None:
		return f"{model}_{prompt_hash}"
	return f"{model}_{prompt_hash}_s{seed}"

__all__ = ["generation_cache_key", "CACHE_ROOT"]
