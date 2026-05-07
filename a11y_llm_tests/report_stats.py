"""Pure statistics helpers for report rendering."""

from __future__ import annotations

from collections import defaultdict


def _compute_summary_simple(sub_results):
  pm = defaultdict(lambda: {
    "total": 0,
    "total_passes": 0,
    "total_axe_failures": 0,
    "total_assertion_failures": 0,
    "total_assertion_bp_failures": 0,
    "axe_bp_total": 0,
  })
  for result in sub_results:
    model = result.get("model_name")
    if not model:
      continue
    pm[model]["total"] += 1
    if result.get("result") == "PASS":
      pm[model]["total_passes"] += 1
    test_function = result.get("test_function") or {}
    pm[model]["total_assertion_failures"] += test_function.get("total_assertion_failures", 0)
    pm[model]["total_assertion_bp_failures"] += test_function.get("total_assertion_bp_failures", 0)
    axe = result.get("axe") or {}
    pm[model]["total_axe_failures"] += (axe.get("failure_count") or 0)
    pm[model]["axe_bp_total"] += (axe.get("best_practice_count") or 0)

  out = {}
  for model, stats in pm.items():
    total = stats["total"] or 0
    pass_rate = (stats["total_passes"] / total) if total else 0.0
    total_failures = stats["total_assertion_failures"] + stats["total_axe_failures"]
    out[model] = {
      "pass_rate": pass_rate,
      "avg_failures": (total_failures / total) if total else 0.0,
    }
  return out


def _compute_overall_stats(sub_results):
  total = 0
  total_passes = 0
  total_wcag_failures = 0
  for result in (sub_results or []):
    total += 1
    if result.get("result") == "PASS":
      total_passes += 1
    test_function = result.get("test_function") or {}
    axe = result.get("axe") or {}
    total_wcag_failures += (test_function.get("total_assertion_failures") or 0)
    total_wcag_failures += (axe.get("failure_count") or 0)
  return {
    "total": total,
    "pass_rate": (total_passes / total) if total else 0.0,
    "avg_wcag_failures": (total_wcag_failures / total) if total else 0.0,
  }


def _compute_test_stats(sub_results):
  by_test = defaultdict(lambda: {"total": 0, "passes": 0, "total_wcag_failures": 0})
  for result in (sub_results or []):
    test_name = result.get("test_name")
    if not test_name:
      continue
    stats = by_test[test_name]
    stats["total"] += 1
    if result.get("result") == "PASS":
      stats["passes"] += 1
    test_function = result.get("test_function") or {}
    axe = result.get("axe") or {}
    stats["total_wcag_failures"] += (test_function.get("total_assertion_failures") or 0)
    stats["total_wcag_failures"] += (axe.get("failure_count") or 0)
  out = {}
  for test_name, stats in by_test.items():
    total = stats["total"] or 0
    out[test_name] = {
      "total": total,
      "pass_rate": (stats["passes"] / total) if total else 0.0,
      "avg_wcag_failures": (stats["total_wcag_failures"] / total) if total else 0.0,
    }
  return out


def _compute_axe_rule_rates(sub_results):
  total = 0
  counts = defaultdict(int)
  meta = {}
  for result in (sub_results or []):
    total += 1
    axe = result.get("axe") or {}
    for failure in (axe.get("failures") or []):
      rule_id = failure.get("id")
      if not rule_id:
        continue
      counts[rule_id] += 1
      if rule_id not in meta:
        meta[rule_id] = {
          "impact": failure.get("impact"),
          "description": failure.get("description"),
        }
  out = {}
  for rule_id, count in counts.items():
    out[rule_id] = {
      "count": count,
      "rate": (count / total) if total else 0.0,
      "impact": (meta.get(rule_id) or {}).get("impact"),
      "description": (meta.get(rule_id) or {}).get("description"),
    }
  return {"total": total, "rules": out}


def _compute_assertion_stats(sub_results):
  by_test = defaultdict(lambda: defaultdict(lambda: {"applicable_total": 0, "fail": 0, "na": 0, "type": "R"}))
  for result in (sub_results or []):
    test_name = result.get("test_name")
    if not test_name:
      continue
    test_function = result.get("test_function") or {}
    for assertion in (test_function.get("assertions") or []):
      name = assertion.get("name")
      if not name:
        continue
      assertion_type = (assertion.get("type") or "R").upper()
      status = assertion.get("status")
      if status not in ("pass", "fail", "na"):
        continue
      stats = by_test[test_name][name]
      stats["type"] = assertion_type
      if status == "na":
        stats["na"] += 1
      else:
        stats["applicable_total"] += 1
      if status == "fail":
        stats["fail"] += 1
  return by_test


def _variant_id(result: dict) -> str:
  return result.get("prompt_variant_id") or "control"


def _build_skill_per_test_rows(
  vid,
  turns_meta,
  skill_models,
  all_test_names,
  test_stats_by_key,
  control_stats_by_test_model,
  model_display_names,
):
  rows = []
  for test_name in all_test_names:
    model_rows = []
    for model_name in skill_models:
      control = control_stats_by_test_model.get((test_name, model_name))
      ctrl_rate = (control["n_pass"] / control["n_samples"]) if (control and control["n_samples"] > 0) else None
      turn_rates = []
      has_data = False
      for turn in turns_meta:
        turn_id = turn.get("id")
        entry = test_stats_by_key.get((vid, turn_id, test_name, model_name))
        if entry and entry["n_samples"] > 0:
          has_data = True
          turn_rates.append({"pass_rate": entry["n_pass"] / entry["n_samples"]})
        else:
          turn_rates.append({"pass_rate": None})
      if not has_data:
        continue
      last_rate = turn_rates[-1]["pass_rate"] if turn_rates else None
      delta = None
      if last_rate is not None and ctrl_rate is not None:
        delta = last_rate - ctrl_rate
      model_rows.append({
        "model_name": model_name,
        "model_display": model_display_names.get(model_name, model_name),
        "control_pass_rate": ctrl_rate,
        "turn_pass_rates": turn_rates,
        "delta_last_vs_control": delta,
      })
    if model_rows:
      rows.append({"test_name": test_name, "models": model_rows})
  return rows


def _prepare_axe_list(src_dict, limit=10):
  total = 0
  for _rule_id, info in (src_dict or {}).items():
    try:
      total += int(info.get("count", 0) or 0)
    except (TypeError, ValueError):
      continue
  items = []
  for rule_id, info in src_dict.items():
    count = info.get("count", 0)
    try:
      count_int = int(count or 0)
    except (TypeError, ValueError):
      count_int = 0
    items.append({
      "id": rule_id,
      "count": count_int,
      "percent": (count_int / total) if total else None,
      "impact": info.get("impact"),
      "description": info.get("description"),
      "n_models": len(info.get("models") or []),
      "n_tests": len(info.get("tests") or []),
    })
  items.sort(key=lambda item: (-item["count"], item["id"]))
  return items[:limit]