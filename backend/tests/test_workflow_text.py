"""Tests for workflow text helpers."""
from __future__ import annotations

from app.models import CanonicalEvent, EventKind
from app.services.workflow_text import (
    SENTINEL,
    activity_for,
    append_sentinel,
    extract_plan,
    extract_profiles,
    extract_questionnaire,
    extract_refined_issue,
    has_sentinel,
)


def _ev(kind: EventKind, tool_name: str | None = None) -> CanonicalEvent:
    return CanonicalEvent(kind=kind, session_id="s", tool_name=tool_name)


def test_activity_for_maps_kinds_and_tools() -> None:
    """Ensure event kinds and tools map to short activity verbs."""
    assert activity_for(_ev(EventKind.THINKING)) == "thinking"
    assert activity_for(_ev(EventKind.ASSISTANT_TEXT)) == "writing"
    assert activity_for(_ev(EventKind.RATE_LIMIT)) == "waiting"
    assert activity_for(_ev(EventKind.TOOL_USE, "Read")) == "reading"
    assert activity_for(_ev(EventKind.TOOL_USE, "Edit")) == "editing"
    assert activity_for(_ev(EventKind.TOOL_USE, "Bash")) == "running"
    # An MCP tool name is stripped to its bare verb-less tail.
    assert activity_for(_ev(EventKind.TOOL_USE, "mcp__x__frobnicate")) == (
        "frobnicate"
    )


def test_activity_for_silent_on_uninformative_events() -> None:
    """Ensure events with no activity signal return None (keep last)."""
    assert activity_for(_ev(EventKind.TOOL_RESULT)) is None
    assert activity_for(_ev(EventKind.RESULT)) is None
    assert activity_for(_ev(EventKind.USER_TEXT)) is None
    assert activity_for(_ev(EventKind.SYSTEM)) is None


def test_has_sentinel_detects_marker() -> None:
    """Ensure has_sentinel is true only when the marker is present."""
    assert has_sentinel(f"body\n{SENTINEL}") is True
    assert has_sentinel("plain body") is False


def test_append_sentinel_is_idempotent() -> None:
    """Ensure append_sentinel adds the marker once."""
    once = append_sentinel("body")
    twice = append_sentinel(once)
    assert has_sentinel(once)
    assert once == twice


def test_extract_refined_issue_between_delimiters() -> None:
    """Ensure the refined issue is extracted from the delimiter block."""
    text = "chatter\n<REFINED_ISSUE>\nThe refined text\n</REFINED_ISSUE>\nmore"
    assert extract_refined_issue(text) == "The refined text"


def test_extract_refined_issue_absent_returns_none() -> None:
    """Ensure output without the delimiter yields None (still questions)."""
    assert extract_refined_issue("Just a question?") is None


def test_extract_plan_between_delimiters() -> None:
    """Ensure the plan is extracted from its own delimiter block."""
    text = "chatter\n<PLAN>\nStep 1\nStep 2\n</PLAN>\nmore"
    assert extract_plan(text) == "Step 1\nStep 2"


def test_extract_plan_absent_returns_none() -> None:
    """Ensure output without the delimiter yields None."""
    assert extract_plan("no tags here") is None


def test_extract_questionnaire_parses_valid_block() -> None:
    """Ensure a well-formed QUESTIONS block parses."""
    text = (
        "Before I refine this, one question.\n"
        "<QUESTIONS>"
        '{"questions": [{"id": "q1", "prompt": "Which auth?", '
        '"type": "single_select", "required": true, '
        '"options": [{"value": "oidc", "label": "OIDC"}]}]}'
        "</QUESTIONS>"
    )
    q = extract_questionnaire(text)
    assert q is not None
    assert q.questions[0].id == "q1"


def test_extract_questionnaire_returns_none_without_tag() -> None:
    """Ensure plain prose (no tag) yields None, not an error."""
    assert extract_questionnaire("Just a question in prose.") is None


def test_extract_questionnaire_returns_none_on_bad_json() -> None:
    """Ensure a malformed block yields None, not an exception."""
    text = "<QUESTIONS>{not json}</QUESTIONS>"
    assert extract_questionnaire(text) is None


def test_extract_profiles_parses_array() -> None:
    """Ensure a PROFILES array of ids is extracted."""
    text = 'Picked:\n<PROFILES>["requester", "infosec"]</PROFILES>'
    assert extract_profiles(text) == ["requester", "infosec"]


def test_extract_profiles_empty_means_done() -> None:
    """Ensure an empty array is returned as [] (interview done)."""
    assert extract_profiles("<PROFILES>[]</PROFILES>") == []


def test_extract_profiles_accepts_object_form() -> None:
    """Ensure a {"profiles": [...]} object is also accepted."""
    text = '<PROFILES>{"profiles": ["developer"]}</PROFILES>'
    assert extract_profiles(text) == ["developer"]


def test_extract_profiles_absent_or_malformed_returns_none() -> None:
    """Ensure a missing or malformed block yields None."""
    assert extract_profiles("no tag here") is None
    assert extract_profiles("<PROFILES>{not json}</PROFILES>") is None
    assert extract_profiles("<PROFILES>[1, 2]</PROFILES>") is None
