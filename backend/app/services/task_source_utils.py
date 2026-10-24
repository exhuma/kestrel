"""Small utilities shared by the GitHub/Jira/local task-source and
code-host adapters: ownership markers on what kestrel writes, and tolerant
timestamp parsing.

Markers are :class:`~app.documents.Marker` blocks (constitution Principle
VI): adapters add them to the ``Document`` they were given and render the
result once, never by appending text after rendering.
"""
from __future__ import annotations

from datetime import datetime

from app.documents import Document, Marker

#: Every comment kestrel posts carries it, so kestrel never acts on its own
#: comments while it posts through the operator's account (feature 046).
POSTED = "posted"
#: Marks a ticket body kestrel has refined (feature 001).
REFINED = "refined"

#: Length of a bare numeric UTC-offset suffix, e.g. "+0000" or "-0500".
_OFFSET_LEN = 5


def with_marker(value: Document, name: str) -> Document:
    """*value* ending with the marker *name*, added at most once."""
    if name in value.markers():
        return value
    return Document((*value.blocks, Marker(name)))


def as_posted(value: Document, enabled: bool) -> Document:
    """A comment as kestrel posts it: with its ownership marker, unless
    comment marking is disabled for the source."""
    return with_marker(value, POSTED) if enabled else value


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
