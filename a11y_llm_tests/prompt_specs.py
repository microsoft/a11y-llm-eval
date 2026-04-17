"""Structured prompt-spec loading and prompt-case composition."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PromptDimensionChoice:
    id: str
    label: str
    value_id: str
    value_label: str
    prompt_fragment: str


@dataclass(frozen=True)
class PromptCaseDefinition:
    base_test_name: str
    test_name: str
    prompt_case_id: str
    prompt_text: str
    prompt_dimensions: list[dict[str, str]]


@dataclass(frozen=True)
class PromptSpecSet:
    test_dirs: list[Path]
    prompt_cases: list[PromptCaseDefinition]
    prompts_map: dict[str, str]
    prompt_cases_meta: list[dict[str, Any]]
    base_test_names: list[str]


def _slugify(value: str) -> str:
    slug = []
    previous_dash = False
    for char in (value or "").strip().lower():
        if char.isalnum():
            slug.append(char)
            previous_dash = False
            continue
        if not previous_dash:
            slug.append("-")
            previous_dash = True
    return "".join(slug).strip("-") or "value"


def _humanize_name(name: str) -> str:
    return " ".join(part.capitalize() for part in name.replace("_", "-").split("-"))


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a mapping in {path}")
    return data


def _normalize_dimensions(raw_dimensions: Any, source: Path) -> list[tuple[str, dict[str, Any]]]:
    if raw_dimensions is None:
        return []
    if not isinstance(raw_dimensions, dict):
        raise ValueError(f"'dimensions' must be a mapping in {source}")
    normalized: list[tuple[str, dict[str, Any]]] = []
    for dimension_id, dimension in raw_dimensions.items():
        if not isinstance(dimension, dict):
            raise ValueError(f"Dimension '{dimension_id}' must be a mapping in {source}")
        label = str(dimension.get("label") or _humanize_name(str(dimension_id)))
        values = dimension.get("values")
        if not isinstance(values, dict) or not values:
            raise ValueError(f"Dimension '{dimension_id}' must define a non-empty 'values' mapping in {source}")
        normalized.append((str(dimension_id), {"label": label, "values": values}))
    return normalized


def _compose_prompt(
    base_prompt: str,
    common_requirements: list[str],
    dimension_choices: list[PromptDimensionChoice],
) -> str:
    lines = [base_prompt.strip()]
    requirements = [choice.prompt_fragment.strip() for choice in dimension_choices if choice.prompt_fragment.strip()]
    requirements.extend(req.strip() for req in common_requirements if str(req).strip())
    if requirements:
        lines.append("")
        lines.append("Requirements:")
        for requirement in requirements:
            lines.append(f"- {requirement}")
    return "\n".join(lines).strip()


def load_prompt_specs(
    test_cases_dir: str | Path,
    global_dimensions_file: str | Path,
    test_case_filter: list[str] | None = None,
) -> PromptSpecSet:
    test_cases_root = Path(test_cases_dir)
    global_config_path = Path(global_dimensions_file)

    if not global_config_path.exists():
        raise FileNotFoundError(f"Prompt dimensions config not found: {global_config_path}")

    global_config = _load_yaml(global_config_path)
    global_dimensions = _normalize_dimensions(global_config.get("dimensions"), global_config_path)

    test_dirs = sorted(
        p for p in test_cases_root.iterdir()
        if p.is_dir() and (p / "prompt.yaml").exists()
    )

    if test_case_filter is not None:
        available_names = {p.name for p in test_dirs}
        unknown = [name for name in test_case_filter if name not in available_names]
        if unknown:
            raise ValueError(
                f"Unknown test case(s): {', '.join(sorted(unknown))}. "
                f"Available: {', '.join(sorted(available_names))}"
            )
        filter_set = set(test_case_filter)
        test_dirs = [p for p in test_dirs if p.name in filter_set]

    prompt_cases: list[PromptCaseDefinition] = []
    prompt_cases_meta: list[dict[str, Any]] = []
    prompts_map: dict[str, str] = {}
    base_test_names: list[str] = []

    for test_dir in test_dirs:
        prompt_yaml_path = test_dir / "prompt.yaml"
        spec = _load_yaml(prompt_yaml_path)
        base_prompt = str(spec.get("base_prompt") or "").strip()
        if not base_prompt:
            raise ValueError(f"Missing non-empty 'base_prompt' in {prompt_yaml_path}")

        display_name = str(spec.get("name") or _humanize_name(test_dir.name)).strip()
        common_requirements = spec.get("common_requirements") or []
        if not isinstance(common_requirements, list):
            raise ValueError(f"'common_requirements' must be a list in {prompt_yaml_path}")

        local_dimensions = _normalize_dimensions(spec.get("dimensions"), prompt_yaml_path)
        all_dimensions = global_dimensions + local_dimensions
        base_test_names.append(test_dir.name)

        combinations = [()] if not all_dimensions else product(*[
            list(dimension[1]["values"].keys()) for dimension in all_dimensions
        ])

        for combination in combinations:
            dimension_choices: list[PromptDimensionChoice] = []
            id_parts = [test_dir.name]
            name_parts = [display_name]

            for (dimension_id, dimension), value_id in zip(all_dimensions, combination):
                raw_value = dimension["values"].get(value_id)
                if not isinstance(raw_value, dict):
                    raise ValueError(
                        f"Value '{value_id}' for dimension '{dimension_id}' must be a mapping in {prompt_yaml_path}"
                    )
                value_label = str(raw_value.get("label") or _humanize_name(str(value_id))).strip()
                prompt_fragment = str(raw_value.get("prompt_fragment") or "").strip()
                dimension_choices.append(PromptDimensionChoice(
                    id=str(dimension_id),
                    label=str(dimension["label"]),
                    value_id=str(value_id),
                    value_label=value_label,
                    prompt_fragment=prompt_fragment,
                ))
                id_parts.append(f"{_slugify(str(dimension_id))}-{_slugify(str(value_id))}")
                name_parts.append(value_label)

            prompt_case_id = "--".join(id_parts)
            test_name = " | ".join(name_parts)
            prompt_text = _compose_prompt(base_prompt, common_requirements, dimension_choices)
            prompt_dimensions = [
                {
                    "id": choice.id,
                    "label": choice.label,
                    "value_id": choice.value_id,
                    "value_label": choice.value_label,
                }
                for choice in dimension_choices
            ]

            prompt_case = PromptCaseDefinition(
                base_test_name=test_dir.name,
                test_name=test_name,
                prompt_case_id=prompt_case_id,
                prompt_text=prompt_text,
                prompt_dimensions=prompt_dimensions,
            )
            prompt_cases.append(prompt_case)
            prompts_map[test_name] = prompt_text
            prompt_cases_meta.append(
                {
                    "id": prompt_case_id,
                    "test_name": test_name,
                    "base_test_name": test_dir.name,
                    "prompt_dimensions": prompt_dimensions,
                }
            )

    return PromptSpecSet(
        test_dirs=test_dirs,
        prompt_cases=prompt_cases,
        prompts_map=prompts_map,
        prompt_cases_meta=prompt_cases_meta,
        base_test_names=base_test_names,
    )