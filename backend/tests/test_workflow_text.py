"""Tests for workflow text helpers."""
from __future__ import annotations

from app.services.workflow_text import (
    SENTINEL,
    append_sentinel,
    extract_refined_issue,
    has_sentinel,
)


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
