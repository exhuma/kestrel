"""Domain models: the canonical event vocabulary.

Every agent backend (claude CLI, opencode) maps its native
output onto :class:`CanonicalEvent` so the server log and the backends'
consumers never depend on any one backend's event shape. The
claude-specific mapping lives in :func:`map_claude_line`.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class EventKind(str, Enum):
    """The normalized event vocabulary shared by all backends."""

    ASSISTANT_TEXT = "assistant_text"
    USER_TEXT = "user_text"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    THINKING = "thinking"
    SYSTEM = "system"
    RATE_LIMIT = "rate_limit"
    RESULT = "result"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class CanonicalEvent:
    """One backend-agnostic event in an agent session.

    Only the fields relevant to ``kind`` are populated; the rest stay
    ``None``. Events are written to the server log (``kestrel.agent``),
    so they carry just what a log line shows.
    """

    kind: EventKind
    session_id: str | None
    text: str | None = None
    tool_name: str | None = None
    tool_summary: str | None = None
    is_error: bool = False
    subtype: str | None = None
    summary: str | None = None
    duration_ms: int | None = None


#: A mapper from one decoded claude stream-json object (and its session
#: id) to a canonical event.
_Mapper = Callable[[dict[str, object], str | None], CanonicalEvent]


def _content_blocks(data: dict[str, object]) -> list[dict[str, object]] | None:
    """Return the ``message.content`` block list, or None."""
    message = data.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    return [b for b in content if isinstance(b, dict)]


def _texts(blocks: list[dict[str, object]]) -> list[str]:
    """Collect the string text of every ``text`` block."""
    return [
        b["text"]
        for b in blocks
        if b.get("type") == "text" and isinstance(b.get("text"), str)
    ]


def _text_or_none(value: object) -> str | None:
    """``value`` when it is a non-empty string, else None."""
    return value if isinstance(value, str) and value else None


def tool_summary(tool_input: object) -> str | None:
    """Summarise a tool call's input (a file path or command first).

    :param tool_input: The tool's input object, as the backend sent it.
    :returns: The path or command, the input as JSON, or None.
    """
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "command", "filePath"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return json.dumps(tool_input) if tool_input else None


def _unknown(data: dict[str, object], sid: str | None) -> CanonicalEvent:
    """Keep an unrecognised payload, as JSON, instead of dropping it."""
    return CanonicalEvent(
        kind=EventKind.UNKNOWN, session_id=sid, text=json.dumps(data)
    )


def _map_assistant(data: dict[str, object], sid: str | None) -> CanonicalEvent:
    """An assistant message: a tool call, or plain text."""
    blocks = _content_blocks(data)
    if blocks is None:
        return _unknown(data, sid)
    texts = _texts(blocks)
    tool = next((b for b in blocks if b.get("type") == "tool_use"), None)
    if tool is not None and isinstance(tool.get("name"), str):
        return CanonicalEvent(
            kind=EventKind.TOOL_USE,
            session_id=sid,
            tool_name=tool["name"],
            tool_summary=tool_summary(tool.get("input")),
            text=" ".join(texts) if texts else None,
        )
    if texts:
        return CanonicalEvent(
            kind=EventKind.ASSISTANT_TEXT,
            session_id=sid,
            text="\n".join(texts),
        )
    return _unknown(data, sid)


def _map_user(data: dict[str, object], sid: str | None) -> CanonicalEvent:
    """A user message: a tool result, or plain text."""
    blocks = _content_blocks(data)
    if blocks is None:
        return _unknown(data, sid)
    result = next((b for b in blocks if b.get("type") == "tool_result"), None)
    if result is not None:
        content = result.get("content")
        return CanonicalEvent(
            kind=EventKind.TOOL_RESULT,
            session_id=sid,
            text=content if isinstance(content, str) else json.dumps(content),
            is_error=bool(result.get("is_error")),
        )
    texts = _texts(blocks)
    if texts:
        return CanonicalEvent(
            kind=EventKind.USER_TEXT, session_id=sid, text="\n".join(texts)
        )
    return _unknown(data, sid)


def _map_system(data: dict[str, object], sid: str | None) -> CanonicalEvent:
    """A system event: a thinking-token estimate, or a status notice."""
    subtype = _text_or_none(data.get("subtype")) or "unknown"
    if subtype == "thinking_tokens":
        tokens = data.get("estimated_tokens")
        return CanonicalEvent(
            kind=EventKind.THINKING,
            session_id=sid,
            summary=f"{tokens} tokens" if isinstance(tokens, int) else None,
        )
    summary = (
        _text_or_none(data.get("hook_name"))
        or _text_or_none(data.get("status_category"))
        or subtype
    )
    return CanonicalEvent(
        kind=EventKind.SYSTEM, session_id=sid, subtype=subtype, summary=summary
    )


def _map_result(data: dict[str, object], sid: str | None) -> CanonicalEvent:
    """The turn's result: its deliverable text, error flag and duration."""
    duration = data.get("duration_ms")
    result = data.get("result")
    return CanonicalEvent(
        kind=EventKind.RESULT,
        session_id=sid,
        text=result if isinstance(result, str) else None,
        is_error=bool(data.get("is_error")),
        duration_ms=duration if isinstance(duration, int) else None,
    )


def _map_rate_limit(data: dict[str, object], sid: str | None) -> CanonicalEvent:
    """A rate-limit notice, summarised by its status."""
    info = data.get("rate_limit_info")
    status = info.get("status") if isinstance(info, dict) else None
    return CanonicalEvent(
        kind=EventKind.RATE_LIMIT,
        session_id=sid,
        summary=_text_or_none(status) or "unknown",
    )


#: Stream-json ``type`` → its mapper; any other type maps to UNKNOWN.
_MAPPERS: dict[str, _Mapper] = {
    "assistant": _map_assistant,
    "user": _map_user,
    "system": _map_system,
    "result": _map_result,
    "rate_limit_event": _map_rate_limit,
}


def map_claude_dict(data: dict[str, object]) -> CanonicalEvent | None:
    """
    Map one decoded claude stream-json object to a canonical event.

    :param data: A decoded stream-json object.
    :returns: The canonical event, or None if ``data`` is not a dict.
    """
    if not isinstance(data, dict):
        return None
    raw_sid = data.get("session_id")
    sid = raw_sid if isinstance(raw_sid, str) else None
    ctype = data.get("type")
    mapper = _MAPPERS.get(ctype) if isinstance(ctype, str) else None
    return (mapper or _unknown)(data, sid)


def map_claude_line(line: str) -> CanonicalEvent | None:
    """
    Parse and map one JSONL line from the claude stream.

    :param line: A raw line of stream-json output.
    :returns: The canonical event, or None for blank/invalid lines.
    """
    stripped = line.strip()
    if not stripped:
        return None
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return map_claude_dict(data)
