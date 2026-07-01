"""Domain models for sessions and parsed CLI events."""
from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class ParsedEvent:
    """A single parsed event from the claude stream-json output."""

    type: str
    session_id: str | None
    raw: dict[str, object]


@dataclass
class SessionRecord:
    """In-memory record of one dispatched session."""

    session_id: str
    cwd: str
    status: str = "running"
    events: list[ParsedEvent] = field(default_factory=list)


def parse_event(line: str) -> ParsedEvent | None:
    """
    Parse one JSONL line from the claude stream.

    :param line: A raw line of stream-json output.
    :returns: The parsed event, or None for blank/invalid lines.
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
    raw_type = data.get("type")
    event_type = raw_type if isinstance(raw_type, str) else "unknown"
    session_id = data.get("session_id")
    return ParsedEvent(
        type=event_type,
        session_id=session_id if isinstance(session_id, str) else None,
        raw=data,
    )
