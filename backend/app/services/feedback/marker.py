"""The marker gate and author guard feedback intake converges through.

Two independent guards (feature 013, research.md R1/R6), both pure and
I/O-free so every transport (webhook, poll) can share the exact same
check: a comment/review must carry the configured trigger token to be
acted on at all, and even a marked one is discarded when it looks like
kestrel talking to itself.
"""
from __future__ import annotations

import re


def has_marker(body: str, marker: str) -> bool:
    """
    Whether ``body`` contains ``marker`` as a whole token.

    Case-insensitive; the marker must not be glued to surrounding word
    characters on either side, so ``"@kestrel"`` matches ``"@kestrel please
    look"`` but not ``"@kestrelbot"`` or ``"notkestrel"``.

    :param body: Raw comment/review text.
    :param marker: The configured trigger token (``settings.feedback_marker``).
    :returns: ``True`` iff the marker appears as a standalone token.
    """
    pattern = re.compile(rf"(?<!\w){re.escape(marker)}(?!\w)", re.IGNORECASE)
    return pattern.search(body) is not None


def is_ignored_author(
    author: str,
    ignore_authors: list[str],
    *,
    is_bot: bool = False,
) -> bool:
    """
    Whether feedback from ``author`` must be discarded (self-loop guard).

    ``Feedback.author`` is just a display string — it carries no notion of
    account type — so a caller with more context (e.g. the GitHub webhook
    payload's ``user.type``) passes ``is_bot`` in separately rather than
    this function trying to infer it from the name.

    :param author: The feedback's reported author.
    :param ignore_authors: Configured denylist
        (``settings.feedback_ignore_authors``).
    :param is_bot: Whether the source has already identified this author as
        a bot account (e.g. GitHub's ``user.type == "Bot"``).
    :returns: ``True`` iff this author's feedback must never be claimed.
    """
    if is_bot:
        return True
    lowered = author.casefold()
    return any(lowered == ignored.casefold() for ignored in ignore_authors)
