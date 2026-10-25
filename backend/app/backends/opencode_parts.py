"""Reading opencode's message payloads: tool-call inputs and assistant
errors. Pure; split out of ``opencode.py`` to keep it within the module
size limit."""
from __future__ import annotations

from app.models import CanonicalEvent, EventKind, tool_summary


def assistant_error(response: object) -> str | None:
    """Extract an OpenCode assistant error message from a message response."""
    if not isinstance(response, dict):
        return None
    info = response.get("info")
    if not isinstance(info, dict):
        return None
    error = info.get("error")
    if not isinstance(error, dict):
        return None
    data = error.get("data")
    if isinstance(data, dict) and isinstance(data.get("message"), str):
        return data["message"]
    name = error.get("name")
    return name if isinstance(name, str) else "unknown assistant error"


def part_events(part: object, session_id: str) -> list[CanonicalEvent]:
    """Map one opencode message part to canonical events (for logging).

    Structural parts (step-start, step-finish, snapshot, …) map to nothing.
    """
    if not isinstance(part, dict):
        return []
    ptype = part.get("type")
    text = part.get("text")
    if ptype == "text" and isinstance(text, str):
        return [CanonicalEvent(EventKind.ASSISTANT_TEXT, session_id, text)]
    if ptype == "reasoning" and isinstance(text, str):
        return [
            CanonicalEvent(
                EventKind.SYSTEM, session_id, subtype="reasoning", summary=text
            )
        ]
    if ptype == "tool":
        return _tool_events(part, session_id)
    return []


def _tool_events(part: dict, session_id: str) -> list[CanonicalEvent]:
    """The tool call, and its output when it has one."""
    raw_state = part.get("state")
    state = raw_state if isinstance(raw_state, dict) else {}
    tool = part.get("tool")
    events = [
        CanonicalEvent(
            EventKind.TOOL_USE,
            session_id,
            tool_name=tool if isinstance(tool, str) else None,
            tool_summary=tool_summary(state.get("input")),
        )
    ]
    output = state.get("output")
    if isinstance(output, str) and output:
        events.append(
            CanonicalEvent(
                EventKind.TOOL_RESULT,
                session_id,
                text=output,
                is_error=state.get("status") == "error",
            )
        )
    return events
