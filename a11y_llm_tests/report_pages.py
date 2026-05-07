"""Helpers for writing split report page artifacts."""

from __future__ import annotations

import shutil
from pathlib import Path

from jinja2 import Template

from .report_detail_assets import (
  CONVERSATION_FRAGMENT_TEMPLATE,
  DETAIL_FRAGMENT_TEMPLATE,
  DETAIL_PAGE_SCRIPT,
  DETAIL_PAGE_STYLE,
  DETAIL_PAGE_TEMPLATE,
)


def _prepare_report_pages(run_dir: Path) -> tuple[Path, Path, Path]:
  report_pages_dir = run_dir / "report_pages"
  detail_pages_dir = report_pages_dir / "details"
  conversation_pages_dir = report_pages_dir / "conversations"

  if report_pages_dir.exists():
    shutil.rmtree(report_pages_dir)
  detail_pages_dir.mkdir(parents=True, exist_ok=True)
  conversation_pages_dir.mkdir(parents=True, exist_ok=True)
  return report_pages_dir, detail_pages_dir, conversation_pages_dir


def _write_conversation_fragment(run_dir: Path, conversation_fragment_rel: str, turns: list[dict]) -> None:
  (run_dir / conversation_fragment_rel).write_text(
    Template(CONVERSATION_FRAGMENT_TEMPLATE).render(turns=turns),
    encoding="utf-8",
  )


def _write_detail_page_artifacts(
  *,
  run_dir: Path,
  detail_fragment_rel: str,
  detail_page_rel: str,
  test_name: str,
  test_data: dict,
  model_display_names: dict,
  prompt_variant_names: dict,
  include_generated_html_samples: bool,
  site_name: str,
) -> None:
  detail_body = Template(DETAIL_FRAGMENT_TEMPLATE).render(
    test_name=test_name,
    test_data=test_data,
    model_display_names=model_display_names,
    prompt_variant_names=prompt_variant_names,
    report_include_generated_html_samples=include_generated_html_samples,
    model_heading_tag="h4",
    sample_heading_tag="h5",
  )
  detail_page_body = Template(DETAIL_FRAGMENT_TEMPLATE).render(
    test_name=test_name,
    test_data=test_data,
    model_display_names=model_display_names,
    prompt_variant_names=prompt_variant_names,
    report_include_generated_html_samples=include_generated_html_samples,
    model_heading_tag="h2",
    sample_heading_tag="h3",
  )
  (run_dir / detail_fragment_rel).write_text(detail_body, encoding="utf-8")
  (run_dir / detail_page_rel).write_text(
    Template(DETAIL_PAGE_TEMPLATE).render(
      test_name=test_name,
      site_name=site_name,
      detail_page_style=DETAIL_PAGE_STYLE,
      detail_page_script=DETAIL_PAGE_SCRIPT,
      body=detail_page_body,
    ),
    encoding="utf-8",
  )