"""Domain models: the canonical event vocabulary and session records.

Every agent backend (claude CLI, opencode, plain LLMs) maps its native
output onto :class:`CanonicalEvent` so the registry, persistence, wire
protocol, and UI never depend on any one backend's event shape. The
claude-specific mapping lives in :func:`map_claude_line`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
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
    """One backend-agnostic event in a session's timeline.

    Only the fields relevant to ``kind`` are populated; the rest stay
    ``None``. ``native`` preserves the original backend payload so the
    UI can still offer a raw-JSON view and nothing is lost.
    """

    kind: EventKind
    session_id: str | None
    text: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, object] | None = None
    tool_summary: str | None = None
    is_error: bool = False
    tokens: int | None = None
    subtype: str | None = None
    summary: str | None = None
    model: str | None = None
    tools: list[str] | None = None
    #: MCP servers reported on a system init event, each ``{name, status}``.
    mcp_servers: list[dict[str, object]] | None = None
    duration_ms: int | None = None
    status: str | None = None
    native: dict[str, object] = field(default_factory=dict)


@dataclass
class SessionRecord:
    """In-memory record of one dispatched session."""

    session_id: str
    cwd: str
    status: str = "running"
    events: list[CanonicalEvent] = field(default_factory=list)
    #: When the record was first created (session start). None for
    #: rows persisted before this column existed.
    created_at: datetime | None = None


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
    out = []
    for b in blocks:
        if b.get("type") == "text" and isinstance(b.get("text"), str):
            out.append(b["text"])
    return out


def _tool_summary(tool_input: object) -> str | None:
    """Summarise a tool call's input (file_path/path/command first)."""
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "command"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return json.dumps(tool_input) if tool_input else None


def _unknown(data: dict[str, object], sid: str | None) -> CanonicalEvent:
    """Wrap an unrecognised payload so it is preserved, not dropped."""
    return CanonicalEvent(kind=EventKind.UNKNOWN, session_id=sid, native=data)


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

    if ctype == "assistant":
        blocks = _content_blocks(data)
        if blocks is None:
            return _unknown(data, sid)
        tool = next((b for b in blocks if b.get("type") == "tool_use"), None)
        texts = _texts(blocks)
        if tool is not None and isinstance(tool.get("name"), str):
            return CanonicalEvent(
                kind=EventKind.TOOL_USE,
                session_id=sid,
                native=data,
                tool_name=tool["name"],
                tool_input=(
                    tool["input"]
                    if isinstance(tool.get("input"), dict)
                    else None
                ),
                tool_summary=_tool_summary(tool.get("input")),
                text=" ".join(texts) if texts else None,
            )
        if texts:
            return CanonicalEvent(
                kind=EventKind.ASSISTANT_TEXT,
                session_id=sid,
                native=data,
                text="\n".join(texts),
            )
        return _unknown(data, sid)

    if ctype == "user":
        blocks = _content_blocks(data)
        if blocks is None:
            return _unknown(data, sid)
        result = next(
            (b for b in blocks if b.get("type") == "tool_result"), None
        )
        if result is not None:
            content = result.get("content")
            text = content if isinstance(content, str) else json.dumps(content)
            return CanonicalEvent(
                kind=EventKind.TOOL_RESULT,
                session_id=sid,
                native=data,
                text=text,
                is_error=bool(result.get("is_error")),
            )
        texts = _texts(blocks)
        if texts:
            return CanonicalEvent(
                kind=EventKind.USER_TEXT,
                session_id=sid,
                native=data,
                text="\n".join(texts),
            )
        return _unknown(data, sid)

    if ctype == "system":
        raw_subtype = data.get("subtype")
        subtype = raw_subtype if isinstance(raw_subtype, str) else "unknown"
        if subtype == "thinking_tokens":
            tokens = data.get("estimated_tokens")
            return CanonicalEvent(
                kind=EventKind.THINKING,
                session_id=sid,
                native=data,
                tokens=tokens if isinstance(tokens, int) else 0,
            )
        hook = data.get("hook_name")
        category = data.get("status_category")
        summary = (
            (hook if isinstance(hook, str) and hook else None)
            or (category if isinstance(category, str) and category else None)
            or subtype
        )
        model = data.get("model")
        tools = data.get("tools")
        servers = data.get("mcp_servers")
        return CanonicalEvent(
            kind=EventKind.SYSTEM,
            session_id=sid,
            native=data,
            subtype=subtype,
            summary=summary,
            model=model if isinstance(model, str) else None,
            tools=tools if isinstance(tools, list) else None,
            mcp_servers=servers if isinstance(servers, list) else None,
        )

    if ctype == "result":
        duration = data.get("duration_ms")
        result = data.get("result")
        return CanonicalEvent(
            kind=EventKind.RESULT,
            session_id=sid,
            native=data,
            text=result if isinstance(result, str) else None,
            is_error=bool(data.get("is_error")),
            duration_ms=duration if isinstance(duration, int) else None,
        )

    if ctype == "rate_limit_event":
        info = data.get("rate_limit_info")
        status = info.get("status") if isinstance(info, dict) else None
        return CanonicalEvent(
            kind=EventKind.RATE_LIMIT,
            session_id=sid,
            native=data,
            status=status if isinstance(status, str) else "unknown",
        )

    return _unknown(data, sid)


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
