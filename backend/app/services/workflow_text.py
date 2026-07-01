"""Sentinel and refined-issue extraction helpers for the workflow."""
from __future__ import annotations

import re

SENTINEL = "<!-- agent-dispatcher:refined -->"

_REFINED = re.compile(
    r"<REFINED_ISSUE>\s*(.*?)\s*</REFINED_ISSUE>", re.DOTALL
)


def has_sentinel(body: str) -> bool:
    """Return True if the issue body was already refined."""
    return SENTINEL in body


def append_sentinel(body: str) -> str:
    """Append the sentinel to a body, at most once."""
    if has_sentinel(body):
        return body
    return f"{body.rstrip()}\n\n{SENTINEL}\n"


def extract_refined_issue(text: str) -> str | None:
    """Return the refined issue if the agent emitted the delimiter block."""
    match = _REFINED.search(text)
    return match.group(1).strip() if match else None
