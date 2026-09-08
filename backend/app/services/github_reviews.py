"""GitHub PR review-feedback merging (feature 013, US3).

Split out of ``services/github.py`` to keep that module under the repo's
500-line ceiling: the review-origin ``Feedback`` shape merges three
distinct GitHub resources — PR-conversation comments, review summaries,
and inline (diff-anchored) review comments — each with its own
origin-tagged ``external_id`` prefix so ``GitHubCodeHost.acknowledge`` can
recover which reaction endpoint a given item came from. This is
naturally more machinery than the single-resource ticket-comment case in
``github.py``.
"""
from __future__ import annotations

from datetime import datetime

from app.ports import Feedback
from app.services.feedback.timeparse import parse_iso

#: A PR-conversation comment lives on the very same issues endpoint a
#: ticket comment does, so it shares that reaction endpoint too.
_PR_COMMENT_PREFIX = "gh-pr-comment:"
#: A review's own summary comment — GitHub exposes no reaction endpoint
#: for this resource, so it is never acknowledge-able (falls through
#: ``parse_review_external_id``'s unmatched-prefix ``None`` by
#: construction).
_PR_REVIEW_PREFIX = "gh-pr-review:"
#: An inline (diff-anchored) review comment.
_PR_REVIEW_COMMENT_PREFIX = "gh-pr-review-comment:"


def _conversation_feedback(repo: str, comment: dict) -> Feedback | None:
    user = comment.get("user") or {}
    if user.get("type") == "Bot":
        return None
    return Feedback(
        external_id=f"{_PR_COMMENT_PREFIX}{repo}#{comment['id']}",
        origin="review",
        author=user.get("login", ""),
        body=comment.get("body") or "",
        created_at=parse_iso(comment["created_at"]),
    )


def _review_feedback(repo: str, review: dict) -> Feedback | None:
    body = review.get("body") or ""
    submitted = review.get("submitted_at")
    if not body.strip() or not submitted:
        return None
    user = review.get("user") or {}
    return Feedback(
        external_id=f"{_PR_REVIEW_PREFIX}{repo}#{review['id']}",
        origin="review",
        author=user.get("login", ""),
        body=body,
        created_at=parse_iso(submitted),
    )


def _review_comment_feedback(repo: str, comment: dict) -> Feedback | None:
    user = comment.get("user") or {}
    if user.get("type") == "Bot":
        return None
    return Feedback(
        external_id=f"{_PR_REVIEW_COMMENT_PREFIX}{repo}#{comment['id']}",
        origin="review",
        author=user.get("login", ""),
        body=comment.get("body") or "",
        created_at=parse_iso(comment["created_at"]),
    )


def merge_review_feedback(
    repo: str,
    conversation: list[dict],
    reviews: list[dict],
    review_comments: list[dict],
    cutoff: datetime | None,
) -> list[Feedback]:
    """Merge and origin-tag every reviewer-authored signal, cursor-filtered.

    :param repo: The ``owner/name`` the request lives in (minted into
        every ``external_id``).
    :param conversation: Raw PR-conversation comments (issues API shape).
    :param reviews: Raw review objects (may carry an empty ``body``).
    :param review_comments: Raw inline review comments.
    :param cutoff: Exclude items at or before this timestamp, or ``None``
        to include everything.
    :returns: Origin-tagged ``Feedback``, oldest first.
    """
    mapped = (
        [_conversation_feedback(repo, c) for c in conversation]
        + [_review_feedback(repo, r) for r in reviews]
        + [_review_comment_feedback(repo, c) for c in review_comments]
    )
    items = [
        item for item in mapped
        if item is not None and (cutoff is None or item.created_at > cutoff)
    ]
    items.sort(key=lambda item: item.created_at)
    return items


def parse_review_external_id(external_id: str) -> tuple[str, str, int] | None:
    """
    Recover ``(kind, repo, id)`` from a minted review ``Feedback.external_id``.

    :returns: ``kind`` is ``"comment"`` (PR-conversation — react via the
        issues reaction endpoint) or ``"review_comment"`` (inline — react
        via the pulls reaction endpoint); ``None`` when ``external_id``
        matches neither (including a review's own summary comment, which
        has no reaction endpoint at all).
    """
    for prefix, kind in (
        (_PR_COMMENT_PREFIX, "comment"),
        (_PR_REVIEW_COMMENT_PREFIX, "review_comment"),
    ):
        if external_id.startswith(prefix):
            repo, _, raw_id = external_id[len(prefix):].rpartition("#")
            if repo and raw_id.isdigit():
                return kind, repo, int(raw_id)
    return None


# ---- external_id minting (feature 013, US3 webhook wiring) -------------
#
# The webhook path (``feedback/github_events.py``) mints the SAME
# external_ids the poll path's own ``GitHubCodeHost.list_review_comments``
# already does above, so a webhook delivery and a later poll cycle
# observing the identical GitHub resource dedup on the identical
# ``external_id`` (feature 013, R3) — these are the one place both paths
# share, kept here (not duplicated in ``github_events.py``) precisely so
# they can never drift apart.


def mint_conversation_id(repo: str, comment_id: int) -> str:
    """The external_id for a PR-conversation comment."""
    return f"{_PR_COMMENT_PREFIX}{repo}#{comment_id}"


def mint_review_id(repo: str, review_id: int) -> str:
    """The external_id for a review's own summary comment."""
    return f"{_PR_REVIEW_PREFIX}{repo}#{review_id}"


def mint_review_comment_id(repo: str, comment_id: int) -> str:
    """The external_id for an inline (diff-anchored) review comment."""
    return f"{_PR_REVIEW_COMMENT_PREFIX}{repo}#{comment_id}"
