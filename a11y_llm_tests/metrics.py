"""Metrics utilities for evaluating multiple sampled generations (pass@k)."""
from __future__ import annotations
from math import comb
from typing import Iterable, Dict, List


def compute_pass_at_k(c: int, n: int, ks: Iterable[int]) -> Dict[int, float]:
    """Compute pass@k for given counts.

    pass@k = 1 - ((n-c choose k) / (n choose k)) for 0 < c < n and k <= n.
    Handles edge cases:
      - If c == 0 -> 0.0
      - If c == n -> 1.0
      - If k > n -> treat k as n (probability reduces to c>0 ? 1 : 0)
      - If k <= 0 -> 0.0
    Parameters:
      c: number of passing samples
      n: total number of samples
      ks: iterable of k values
    Returns:
      Dict mapping each k to probability (float)
    Raises:
      ValueError if counts invalid.
    """
    if n < 0 or c < 0 or c > n:
        raise ValueError("Require 0 <= c <= n and n >= 0")
    if n == 0:
        return {int(k): 0.0 for k in ks}

    result: Dict[int, float] = {}
    for k in ks:
        k_int = int(k)
        if k_int <= 0:
            result[k_int] = 0.0
            continue
        k_eff = k_int if k_int <= n else n
        if c == 0:
            result[k_int] = 0.0
            continue
        if c == n:
            result[k_int] = 1.0
            continue
        if k_eff == 0:
            result[k_int] = 0.0
            continue
        numerator = comb(n - c, k_eff) if (n - c) >= k_eff else 0
        denominator = comb(n, k_eff)
        result[k_int] = 1.0 - (numerator / denominator)
    return result


def format_pass_at_k(pass_at_k: Dict[int, float]) -> Dict[str, float]:
    """Convert int keys to strings for JSON serialization stability."""
    return {str(k): float(v) for k, v in sorted(pass_at_k.items(), key=lambda x: x[0])}


__all__ = ["compute_pass_at_k", "format_pass_at_k"]
