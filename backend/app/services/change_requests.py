"""Change-request identity shared by every code host (feature 043 moved it
out of :mod:`app.services.github`: GitLab URLs are matched too)."""
from __future__ import annotations

import re

#: Extracts a PR/MR number from the tail of a change-request URL —
#: GitHub's ``.../pull/123`` or GitLab's ``.../merge_requests/123``.
_CR_NUMBER_RE = re.compile(r"/(?:pull|merge_requests)/(\d+)(?:[/?#]|$)")


def change_request_number(url: str) -> int | None:
    """
    Extract a pull/merge-request number from a change-request URL — the
    location delivery reports for a freshly opened one. Never raises.

    :param url: A change-request URL, or ``""``/``None``/anything malformed.
    :returns: The trailing number, or ``None`` when ``url`` doesn't match.
    """
    if not url:
        return None
    match = _CR_NUMBER_RE.search(url)
    return int(match.group(1)) if match else None


def splice_section(description: str, section: str) -> str:
    """*description* with kestrel's section replaced by *section*.

    The section is recognised by its own first and last lines (a visible
    heading and closing line). The text before and after it is kept as
    it is; when the section is not found (a person removed it, or the
    description predates it), it is appended.
    """
    block = section.strip()
    lines = block.splitlines()
    first, last = lines[0].strip(), lines[-1].strip()
    start = _line_start(description, first, 0)
    end = (
        _line_start(description, last, start) if start is not None
        else None
    )
    if start is None or end is None:
        kept = description.rstrip()
        return f"{kept}\n\n{block}\n" if kept else f"{block}\n"
    after = description.find("\n", end)
    tail = description[after:] if after != -1 else ""
    return description[:start] + block + tail


def _line_start(text: str, line: str, since: int) -> int | None:
    """Where a line reading exactly *line* starts, at or after *since*."""
    match = re.compile(rf"^[ \t]*{re.escape(line)}[ \t]*$", re.M).search(
        text, since
    )
    return match.start() if match else None
