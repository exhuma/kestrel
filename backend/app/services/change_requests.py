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
