"""Tests for the canonical event mapping and domain models."""
from __future__ import annotations

from app.models import CanonicalEvent, EventKind, map_claude_line


def test_map_system_init_extracts_session_id_and_mcp() -> None:
    """Ensure the init event maps to a system event with model/tools/mcp."""
    line = (
        '{"type":"system","subtype":"init","session_id":"abc-123",'
        '"model":"sonnet","tools":["Read"],'
        '"mcp_servers":[{"name":"quartermaster","status":"connected"}]}'
    )
    ev = map_claude_line(line)
    assert isinstance(ev, CanonicalEvent)
    assert ev.kind is EventKind.SYSTEM
    assert ev.session_id == "abc-123"
    assert ev.subtype == "init"
    assert ev.model == "sonnet"
    assert ev.tools == ["Read"]
    assert ev.mcp_servers == [{"name": "quartermaster", "status": "connected"}]


def test_map_result_event_carries_text_and_duration() -> None:
    """Ensure a result event maps to RESULT with its deliverable text."""
    line = (
        '{"type":"result","subtype":"success","session_id":"abc-123",'
        '"is_error":false,"duration_ms":1200,"result":"all done"}'
    )
    ev = map_claude_line(line)
    assert ev is not None
    assert ev.kind is EventKind.RESULT
    assert ev.session_id == "abc-123"
    assert ev.text == "all done"
    assert ev.duration_ms == 1200
    assert ev.is_error is False


def test_map_assistant_text() -> None:
    """Ensure an assistant text message maps to ASSISTANT_TEXT."""
    ev = map_claude_line(
        '{"type":"assistant","message":{"content":'
        '[{"type":"text","text":"hello"}]}}'
    )
    assert ev is not None
    assert ev.kind is EventKind.ASSISTANT_TEXT
    assert ev.text == "hello"
    assert ev.session_id is None


def test_map_assistant_tool_use_summarises_input() -> None:
    """Ensure a tool_use block maps to TOOL_USE with a file summary."""
    ev = map_claude_line(
        '{"type":"assistant","message":{"content":['
        '{"type":"text","text":"editing"},'
        '{"type":"tool_use","name":"Edit","input":{"file_path":"a.py"}}]}}'
    )
    assert ev is not None
    assert ev.kind is EventKind.TOOL_USE
    assert ev.tool_name == "Edit"
    assert ev.tool_summary == "a.py"
    assert ev.text == "editing"  # preface text preserved


def test_map_user_tool_result() -> None:
    """Ensure a tool_result block maps to TOOL_RESULT with its error flag."""
    ev = map_claude_line(
        '{"type":"user","message":{"content":['
        '{"type":"tool_result","content":"boom","is_error":true}]}}'
    )
    assert ev is not None
    assert ev.kind is EventKind.TOOL_RESULT
    assert ev.text == "boom"
    assert ev.is_error is True


def test_map_thinking_tokens() -> None:
    """Ensure a thinking_tokens system event maps to THINKING."""
    ev = map_claude_line(
        '{"type":"system","subtype":"thinking_tokens","estimated_tokens":42}'
    )
    assert ev is not None
    assert ev.kind is EventKind.THINKING
    assert ev.tokens == 42


def test_map_rate_limit_event() -> None:
    """Ensure a rate_limit_event maps to RATE_LIMIT with its status."""
    ev = map_claude_line(
        '{"type":"rate_limit_event","rate_limit_info":{"status":"throttled"}}'
    )
    assert ev is not None
    assert ev.kind is EventKind.RATE_LIMIT
    assert ev.status == "throttled"


def test_map_blank_or_garbage_returns_none() -> None:
    """Ensure blank or non-JSON lines are ignored."""
    assert map_claude_line("") is None
    assert map_claude_line("   ") is None
    assert map_claude_line("not json") is None
    assert map_claude_line("[1,2,3]") is None


def test_map_unrecognised_type_is_preserved_as_unknown() -> None:
    """Ensure an unhandled event is preserved as UNKNOWN, not dropped."""
    ev = map_claude_line('{"type":123,"session_id":"s1"}')
    assert ev is not None
    assert ev.kind is EventKind.UNKNOWN
    assert ev.session_id == "s1"
    assert ev.native == {"type": 123, "session_id": "s1"}
