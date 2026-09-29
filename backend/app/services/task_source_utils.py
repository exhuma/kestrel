"""Small utilities shared by the GitHub/Jira/local task-source and
code-host adapters.

Extracted from the old feedback-dispatch subsystem (retired at the
Phase 10 clean break) — these two functions are genuinely adapter-level
concerns (self-authored comment marking, tolerant timestamp parsing),
not feedback-dispatch-specific, so they moved here rather than being
deleted with the rest of that package.
"""
from __future__ import annotations

from datetime import datetime

from app.markers import SENTINEL

#: Length of a bare numeric UTC-offset suffix, e.g. "+0000" or "-0500".
_OFFSET_LEN = 5


def has_sentinel(body: str) -> bool:
    """Return True if the issue body was already refined."""
    return SENTINEL in body


def append_sentinel(body: str) -> str:
    """Append the sentinel to a body, at most once."""
    if has_sentinel(body):
        return body
    return f"{body.rstrip()}\n\n{SENTINEL}\n"


def append_comment_sentinel(body: str, enabled: bool, sentinel: str) -> str:
    """Append one self-identifying sentinel to an outbound Kestrel comment.

    An empty sentinel is never emitted. Repeated decoration is idempotent so
    composed comment paths cannot produce multiple ownership markers.
    """
    if not enabled or not sentinel or sentinel in body:
        return body
    return f"{body.rstrip()}\n\n{sentinel}"


def parse_iso(value: str) -> datetime:
    """
    Parse an ISO-8601 timestamp, tolerating source-specific quirks.

    :param value: A GitHub- (``...Z``), Jira- (``...+0000``), or
        Python-``isoformat()``-shaped timestamp string.
    :returns: The parsed datetime (timezone-aware unless ``value`` itself
        carried no offset).
    """
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    elif (
        len(text) >= _OFFSET_LEN
        and text[-_OFFSET_LEN] in "+-"
        and text[-4:].isdigit()
    ):
        text = f"{text[:-2]}:{text[-2:]}"
    return datetime.fromisoformat(text)
