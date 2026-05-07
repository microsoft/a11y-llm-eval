"""Pure text formatting helpers for report rendering."""

from __future__ import annotations

import re
from pathlib import Path


def _shorten_sandbox(val: str | None) -> str | None:
  if not val or ":" not in val:
    return val
  provider, path_part = val.split(":", 1)
  if "/" in path_part or "\\" in path_part:
    return f"{provider}:{Path(path_part).name}"
  return val


def _split_message_items(text: str) -> list[str]:
  items = []
  current = []
  quote_char = None
  bracket_depth = 0

  for char in text:
    if quote_char:
      current.append(char)
      if char == quote_char:
        quote_char = None
      continue

    if char in {'"', "'"}:
      quote_char = char
      current.append(char)
      continue

    if char in "([{":
      bracket_depth += 1
      current.append(char)
      continue

    if char in ")]}":
      if bracket_depth > 0:
        bracket_depth -= 1
      current.append(char)
      continue

    if char == "," and bracket_depth == 0:
      item = "".join(current).strip()
      if item:
        items.append(item)
      current = []
      continue

    current.append(char)

  tail = "".join(current).strip()
  if tail:
    items.append(tail)

  return items


def _split_repeated_entity_items(text: str) -> list[str]:
  pattern = re.compile(r'(?i)\b(?:text input|checkbox group|radio group|checkbox|radio|input)\b\s')
  matches = list(pattern.finditer(text))
  if len(matches) < 2:
    return []

  items = []
  for index, match in enumerate(matches):
    start = match.start()
    end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
    item = text[start:end].strip()
    if item:
      items.append(item)
  return items


def _split_message_title(message: str) -> tuple[str, str] | None:
  quote_char = None
  bracket_depth = 0

  for index, char in enumerate(message):
    if quote_char:
      if char == quote_char:
        quote_char = None
      continue

    if char in {'"', "'"}:
      quote_char = char
      continue

    if char in "([{":
      bracket_depth += 1
      continue

    if char in ")]}":
      if bracket_depth > 0:
        bracket_depth -= 1
      continue

    if char == ":" and bracket_depth == 0:
      title = message[:index].strip()
      remainder = message[index + 1:].strip()
      if title and remainder:
        return title, remainder
      return None

  return None


def _format_assertion_message(message: str | None) -> dict | None:
  if not message:
    return None

  message = str(message).strip()
  if not message:
    return None

  split_message = _split_message_title(message)
  if not split_message:
    repeated_items = _split_repeated_entity_items(message)
    if repeated_items:
      return {
        "title": None,
        "items": repeated_items,
      }
    return None

  title, remainder = split_message

  items = [part.strip() for part in _split_message_items(remainder) if part.strip()]
  if len(items) <= 1:
    repeated_items = _split_repeated_entity_items(remainder)
    if repeated_items:
      items = repeated_items
  if not items:
    return None

  normalized_items = [re.sub(r"^and\s+", "", item, flags=re.IGNORECASE) for item in items]
  return {
    "title": f"{title}:" if title else None,
    "items": normalized_items,
  }