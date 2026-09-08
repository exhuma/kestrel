"""ISO-8601 timestamp parsing shared by every feedback-source adapter.

Centralizes tolerance for the minor format variations task sources emit
(GitHub's trailing ``Z``, Jira's offset with no colon) so the three
adapters (``github.py``/``jira.py``/``fixture.py``) don't each reimplement
the same few lines — avoids tripping the repo's copy-paste budget.
"""
from __future__ import annotations

from datetime import datetime

#: Length of a bare numeric UTC-offset suffix, e.g. "+0000" or "-0500".
_OFFSET_LEN = 5


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
