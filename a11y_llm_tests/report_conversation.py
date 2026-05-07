"""Conversation parsing helpers for report rendering."""

from __future__ import annotations

import re
from pathlib import Path

import orjson


def _read_json_for_report(path_str: str | None, run_dir: Path):
  """Read a JSON file for embedding in the report.

  Only files that resolve to a location under the run directory are read.
  Paths that escape the run directory are ignored to prevent local-file
  disclosure when results.json comes from an untrusted source.
  """
  if not path_str:
    return None
  raw_path = Path(path_str)
  resolved_run_dir = run_dir.resolve()

  if raw_path.is_absolute():
    candidates = [raw_path.resolve()]
  else:
    candidates = [
      (run_dir / raw_path).resolve(),
      (Path.cwd() / raw_path).resolve(),
    ]

  for candidate in candidates:
    try:
      candidate.relative_to(resolved_run_dir)
    except ValueError:
      continue
    try:
      if candidate.is_file():
        return orjson.loads(candidate.read_bytes())
    except Exception:
      continue
  return None


def _conversation_preview(conversation: dict | None) -> tuple[list[dict[str, str]], int, int | None]:
  if not isinstance(conversation, dict):
    return [], 0, None

  def _looks_like_html(text):
    normalized = text.lstrip().lower()
    return (
      normalized.startswith("<!doctype html")
      or normalized.startswith("<html")
      or normalized.startswith("<body")
    )

  def _text_value(value):
    if isinstance(value, str):
      text = value.strip()
      return text or None
    if isinstance(value, (int, float, bool)):
      return str(value)
    return None

  def _is_noise(text):
    lowered = text.lower()
    if len(text) > 1000:
      return True
    if "opaque" in lowered and "reasoning" in lowered:
      return True
    if "chain-of-thought" in lowered or "chain of thought" in lowered:
      return True
    if "here's the result of running `cat -n`" in lowered or lowered.startswith("```bash"):
      return True
    return False

  def _append_entry(entries, seen, kind, label, content):
    text = _text_value(content)
    if not text:
      return
    if _looks_like_html(text):
      return
    if _is_noise(text):
      return
    key = (kind, label, text)
    if key in seen:
      return
    seen.add(key)
    entries.append({"kind": kind, "label": label, "content": text})

  _BULKY_ARG_KEYS = {
    "file_text", "new_file_contents", "contents", "content",
    "diff", "patch", "input", "stdin", "body", "text",
  }
  _ARG_VALUE_PREVIEW_LIMIT = 200

  def _format_arg_value(value):
    if isinstance(value, str):
      text = value.strip()
      if len(text) > _ARG_VALUE_PREVIEW_LIMIT:
        return text[:_ARG_VALUE_PREVIEW_LIMIT].rstrip() + " ..."
      return text
    if isinstance(value, (int, float, bool)) or value is None:
      return str(value)
    try:
      rendered = orjson.dumps(value).decode("utf-8")
    except (TypeError, ValueError):
      rendered = str(value)
    if len(rendered) > _ARG_VALUE_PREVIEW_LIMIT:
      rendered = rendered[:_ARG_VALUE_PREVIEW_LIMIT].rstrip() + " ..."
    return rendered

  def _summarize_tool_call(call):
    if not isinstance(call, dict):
      return None
    function_name = (
      call.get("tool_name")
      or call.get("function")
      or call.get("name")
      or "tool"
    )
    arguments = call.get("arguments")
    intention = (
      _text_value(call.get("intention_summary"))
      or _text_value(call.get("intention"))
    )

    lines = [f"-> {function_name}"]
    if intention:
      lines.append(f"  why: {intention}")
    if isinstance(arguments, dict) and arguments:
      priority_keys = ("command", "cmd", "path", "file_name", "url", "intent", "query")
      seen_keys = set()
      for key in priority_keys:
        if key in arguments and arguments[key] not in (None, ""):
          value = _format_arg_value(arguments[key])
          if value:
            lines.append(f"  {key}: {value}")
            seen_keys.add(key)
      for key, value in arguments.items():
        if key in seen_keys or key in _BULKY_ARG_KEYS:
          continue
        if value in (None, "", [], {}):
          continue
        formatted = _format_arg_value(value)
        if formatted:
          lines.append(f"  {key}: {formatted}")
      bulky_present = sorted(k for k in arguments if k in _BULKY_ARG_KEYS and arguments[k])
      if bulky_present:
        lines.append(f"  ({', '.join(bulky_present)} omitted)")
    return "\n".join(lines)

  def _content_blocks(content):
    if content is None:
      return []
    if isinstance(content, str):
      text = content.strip()
      return [text] if text and not _looks_like_html(text) and not _is_noise(text) else []
    if isinstance(content, list):
      parts = []
      for item in content:
        if isinstance(item, str):
          text = item.strip()
          if text and not _looks_like_html(text) and not _is_noise(text):
            parts.append(text)
          continue
        if not isinstance(item, dict):
          continue
        item_type = item.get("type")
        if item_type == "reasoning":
          summary = _text_value(item.get("summary"))
          if summary and not _is_noise(summary):
            parts.append(summary)
          continue
        if item_type == "text":
          text = _text_value(item.get("text"))
          if text and not _looks_like_html(text) and not _is_noise(text):
            parts.append(text)
          continue
        if item_type == "tool_result":
          text = _text_value(item.get("content")) or _text_value(item.get("output")) or _text_value(item.get("result"))
          if text and not _looks_like_html(text) and not _is_noise(text):
            parts.append(text)
      return parts
    if isinstance(content, dict):
      text = _text_value(content.get("text")) or _text_value(content.get("content"))
      if text and not _looks_like_html(text) and not _is_noise(text):
        return [text]
    return []

  entries = []
  seen = set()
  messages = conversation.get("messages") or []
  for message in messages:
    if not isinstance(message, dict):
      continue
    role = str(message.get("role") or "message").lower()

    if role == "assistant":
      for call in message.get("tool_calls") or []:
        summary = _summarize_tool_call(call)
        if summary:
          _append_entry(entries, seen, "assistant", "Agent action", summary)

    blocks = _content_blocks(message.get("content"))
    if not blocks:
      blocks = _content_blocks(message.get("text"))
    if not blocks:
      blocks = _content_blocks(message.get("summary"))

    if not blocks:
      continue

    label = {
      "system": "Instructions",
      "user": "Prompt",
      "assistant": "Agent",
      "tool": "Tool result",
    }.get(role, role.capitalize())
    kind = role if role in {"system", "user", "assistant"} else "assistant"
    for block in blocks:
      _append_entry(entries, seen, kind, label, block)

  events = conversation.get("events") or []
  SDK_MESSAGE_TYPES = {
    "system.message": ("system", "Instructions"),
    "user.message": ("user", "Prompt"),
    "assistant.message": ("assistant", "Agent"),
  }
  SDK_SKIP_PREFIXES = (
    "session.", "pending.", "assistant.turn.", "assistant.usage",
    "assistant.reasoning", "hook.", "permission.completed",
    "tool.execution.partial",
  )
  _RESULT_PREVIEW_LIMIT = 400

  def _extract_tool_result_text(data):
    result = data.get("result")
    if isinstance(result, str):
      match = re.search(r"content=(['\"])(.*?)\1", result, flags=re.DOTALL)
      if match:
        return match.group(2)
      return result
    if isinstance(result, dict):
      return (
        _text_value(result.get("content"))
        or _text_value(result.get("output"))
        or _text_value(result.get("result"))
      )
    return None

  def _truncate(text, limit=_RESULT_PREVIEW_LIMIT):
    if not isinstance(text, str):
      return None
    stripped = text.strip()
    if not stripped:
      return None
    if len(stripped) > limit:
      return stripped[:limit].rstrip() + " ..."
    return stripped

  sdk_message_count = 0
  for event in events:
    if not isinstance(event, dict):
      continue
    ev_type = event.get("type") or event.get("event") or event.get("name")
    data = event.get("data") if isinstance(event.get("data"), dict) else None

    if isinstance(ev_type, str) and data is not None and "." in ev_type:
      if ev_type in SDK_MESSAGE_TYPES:
        kind, label = SDK_MESSAGE_TYPES[ev_type]
        content_text = _text_value(data.get("content"))
        for block in _content_blocks(content_text):
          _append_entry(entries, seen, kind, label, block)
          sdk_message_count += 1
        continue
      if ev_type == "tool.execution.start":
        summary = _summarize_tool_call(data)
        if summary:
          _append_entry(entries, seen, "assistant", "Agent action", summary)
        continue
      if ev_type == "tool.execution.complete":
        tool_name = data.get("tool_name") or "tool"
        if data.get("error"):
          err_text = _text_value(data.get("error")) or "tool execution failed"
          _append_entry(entries, seen, "assistant", f"{tool_name} error", _truncate(err_text))
        else:
          result_text = _extract_tool_result_text(data)
          preview = _truncate(result_text)
          if preview and not _looks_like_html(preview) and not _is_noise(preview):
            _append_entry(entries, seen, "assistant", f"{tool_name} result", preview)
        continue
      if ev_type == "permission.requested":
        req = data.get("permission_request")
        if isinstance(req, str):
          intention = re.search(r"intention=(['\"])(.*?)\1", req)
          file_name = re.search(r"file_name=(['\"])(.*?)\1", req)
          command = re.search(r"full_command_text=(['\"])(.*?)\1", req)
          kind_match = re.search(r"kind=<[^:]+:\s*(['\"])(.*?)\1", req)
          bits = []
          if kind_match:
            bits.append(f"[{kind_match.group(2)}]")
          if intention:
            bits.append(intention.group(2))
          target = (file_name.group(2) if file_name else None) or (
            command.group(2) if command else None
          )
          if target:
            bits.append(target)
          if bits:
            _append_entry(entries, seen, "assistant", "Permission requested", " ".join(bits))
        continue
      if ev_type in {"assistant.tool.use", "assistant.tool.call", "tool.call", "tool.use"}:
        summary = _summarize_tool_call(data) or f"Used {data.get('name') or ev_type}."
        _append_entry(entries, seen, "assistant", "Agent action", summary)
        continue
      if ev_type in {"assistant.tool.result", "tool.result"}:
        result_text = (
          _text_value(data.get("human_readable_result"))
          or _text_value(data.get("output"))
          or _text_value(data.get("content"))
          or _text_value(data.get("result"))
        )
        preview = _truncate(result_text)
        if preview and not _looks_like_html(preview) and not _is_noise(preview):
          _append_entry(entries, seen, "assistant", "Tool result", preview)
        continue
      if any(ev_type.startswith(p) for p in SDK_SKIP_PREFIXES):
        continue

    name = event.get("name") or event.get("tool") or ev_type or "event"
    args = event.get("arguments") or event.get("args") or event.get("input") or event.get("payload") or {}
    if not isinstance(args, dict):
      args = {}
    command = args.get("command") or event.get("command")
    path = args.get("path") or event.get("path")
    bits = []
    command_text = _text_value(command)
    path_text = _text_value(path)
    if command_text:
      bits.append(command_text)
    if path_text:
      bits.append(path_text)
    if bits:
      _append_entry(entries, seen, "assistant", "Agent action", f"Used {name}: {' | '.join(bits)}")
    else:
      _append_entry(entries, seen, "assistant", "Agent action", f"Used {name}.")

    result_text = (
      _text_value(event.get("human_readable_result"))
      or _text_value(event.get("message"))
      or _text_value(event.get("result"))
      or _text_value(event.get("summary"))
    )
    if result_text and not _looks_like_html(result_text) and not _is_noise(result_text):
      _append_entry(entries, seen, "assistant", f"{name} result", result_text)

  output = conversation.get("output") or {}
  if isinstance(output, dict):
    completion = _text_value(output.get("completion") or output.get("text") or output.get("content"))
    if completion:
      if _looks_like_html(completion):
        _append_entry(entries, seen, "assistant", "Final answer", "Submitted final HTML document.")
      else:
        _append_entry(entries, seen, "assistant", "Final answer", completion)

  event_count = len(events) if isinstance(events, list) else None
  message_count = len(messages) + sdk_message_count
  return entries, message_count, event_count


def _build_turns(entries: list[dict[str, str]]) -> list[dict]:
  """Group flat entries into role-based turns for compact rendering."""
  turns: list[dict] = []
  current: dict | None = None
  for entry in entries:
    kind = entry["kind"]
    label = entry["label"]
    content = entry["content"]
    if current is None or current["role"] != kind:
      current = {
        "role": kind,
        "role_label": {"system": "System", "user": "User", "assistant": "Agent"}.get(kind, kind.capitalize()),
        "messages": [],
        "tool_calls": [],
      }
      turns.append(current)
    if label == "Agent action":
      current["tool_calls"].append(content)
    else:
      current["messages"].append({"label": label, "content": content})
  return turns


def _flatten_skill_conversation(conv: dict, turn_index: int | None) -> dict | None:
  """Extract one skill-turn conversation or merge all turns for aggregate views."""
  if not isinstance(conv, dict):
    return conv
  if "turns" not in conv or not isinstance(conv.get("turns"), list):
    return conv
  turns = conv["turns"]
  if turn_index is not None:
    for turn in turns:
      if isinstance(turn, dict) and turn.get("turn_index") == turn_index:
        inner = turn.get("conversation") or {}
        if isinstance(inner, dict):
          return inner
    return None

  merged_messages = []
  merged_events = []
  for turn in turns:
    inner = (turn or {}).get("conversation") or {}
    if not isinstance(inner, dict):
      continue
    merged_messages.extend(inner.get("messages") or [])
    merged_events.extend(inner.get("events") or [])
  return {"messages": merged_messages, "events": merged_events}