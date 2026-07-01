"""Tests for event parsing and domain models."""
from __future__ import annotations

from app.models import ParsedEvent, parse_event


def test_parse_system_init_extracts_session_id() -> None:
    """Ensure the init event yields type and session id."""
    line = (
        '{"type":"system","subtype":"init",'
        '"session_id":"abc-123","tools":[]}'
    )
    ev = parse_event(line)
    assert isinstance(ev, ParsedEvent)
    assert ev.type == "system"
    assert ev.session_id == "abc-123"


def test_parse_result_event() -> None:
    """Ensure a result event parses with its session id."""
    line = (
        '{"type":"result","subtype":"success",'
        '"session_id":"abc-123","is_error":false}'
    )
    ev = parse_event(line)
    assert ev is not None
    assert ev.type == "result"
    assert ev.session_id == "abc-123"


def test_parse_event_without_session_id() -> None:
    """Ensure events without a session id parse with None."""
    ev = parse_event('{"type":"assistant","message":{}}')
    assert ev is not None
    assert ev.type == "assistant"
    assert ev.session_id is None


def test_parse_blank_or_garbage_returns_none() -> None:
    """Ensure blank or non-JSON lines are ignored."""
    assert parse_event("") is None
    assert parse_event("   ") is None
    assert parse_event("not json") is None


def test_parse_non_string_type_defaults_to_unknown() -> None:
    """Ensure a non-string type falls back to "unknown"."""
    ev = parse_event('{"type":123,"session_id":"s1"}')
    assert ev is not None
    assert ev.type == "unknown"


def test_parse_missing_type_defaults_to_unknown() -> None:
    """Ensure a missing type falls back to "unknown"."""
    ev = parse_event('{"session_id":"s1"}')
    assert ev is not None
    assert ev.type == "unknown"
