"""Helpers for loading and normalizing models config for the harness."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_models_config(models_file: str) -> tuple[dict[str, Any], Path]:
    path = Path(models_file).resolve()
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("Models config must be a YAML mapping")
    return data, path


def get_model_provider(model_name: str) -> str:
    value = (model_name or "").strip()
    parts = [part.strip().lower() for part in value.split("/") if part.strip()]
    if len(parts) >= 2 and parts[1] == "azure":
        return "azure"
    if len(parts) >= 2:
        return parts[0] or "unknown"
    return "unknown"


def normalize_models_config(models_cfg: dict[str, Any]) -> dict[str, Any]:
    defaults_cfg = models_cfg.get("defaults") or {}
    providers_cfg = models_cfg.get("providers") or {}
    raw_models = models_cfg.get("models") or []

    normalized_models: list[dict[str, Any]] = []
    model_display_lookup: dict[str, str] = {}
    model_provider_lookup: dict[str, Any] = {}
    models_info: list[dict[str, str]] = []

    for model_entry in raw_models:
        if not isinstance(model_entry, dict):
            continue
        name = model_entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        display_name = model_entry.get("display_name") or name.split("/")[-1]
        provider_name = get_model_provider(name)
        provider_config = providers_cfg.get(provider_name) if isinstance(providers_cfg, dict) else None
        normalized = {
            "name": name,
            "display_name": display_name,
            "provider_name": provider_name,
            "provider_config": provider_config,
            "inspect_model": name,
        }
        normalized_models.append(normalized)
        model_display_lookup[name] = display_name
        model_provider_lookup[name] = provider_config
        models_info.append({"name": name, "display_name": display_name})

    return {
        "defaults": defaults_cfg,
        "providers": providers_cfg,
        "models": normalized_models,
        "model_names": [model["name"] for model in normalized_models],
        "model_display_lookup": model_display_lookup,
        "model_provider_lookup": model_provider_lookup,
        "models_info": models_info,
    }