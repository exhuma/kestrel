"""Per-event demux for feedback-triggering GitHub webhook events.

Keeps ``routers/github_webhook.py`` thin (feature 013): this module owns
building a ``Feedback`` from a raw webhook payload and calling
:class:`~app.services.feedback.intake.FeedbackIntakeService`, so the
router stays limited to HTTP concerns (headers, HMAC, ack, delivery
dedup). Covers ``issue_comment`` (both branches — a plain ticket comment
and a PR-conversation comment), ``pull_request_review``, and
``pull_request_review_comment`` (feature 013, US1 + US3).
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
from typing import Callable

from app.config import Settings, get_settings
from app.ports import Feedback
from app.services import github_reviews
from app.services.feedback.intake import FeedbackIntakeService
from app.services.feedback.timeparse import parse_iso
from app.services.github import GitHubClient, GitHubCodeHost
from app.services.github_tasksource import GitHubTaskSource


def is_ticket_comment(payload: dict) -> bool:
    """
    Whether an ``issue_comment`` payload is a ticket comment, not a PR's.

    GitHub's ``issue_comment`` event fires for both issues and pull
    requests; a PR comment carries a ``pull_request`` key on ``issue``.
    """
    return "pull_request" not in (payload.get("issue") or {})


def _known_repo(payload: dict, settings: Settings) -> bool:
    repo = (payload.get("repository") or {}).get("full_name") or ""
    return settings.github_source_for(repo) is not None


def is_qualifying_comment(payload: dict, settings: Settings) -> bool:
    """
    Whether an ``issue_comment`` delivery is worth dispatching at all.

    A cheap, I/O-free pre-check the router runs synchronously (mirroring
    the ``issues`` event's own gating) so an unqualifying delivery is
    acknowledged honestly with ``"ignored"`` rather than always claiming
    ``"accepted"`` for a background task that will no-op. Covers both the
    ticket-comment and the PR-conversation-comment branch — which one
    applies is decided later, in :func:`handle_issue_comment`.
    """
    if payload.get("action") != "created":
        return False
    return _known_repo(payload, settings)


def is_qualifying_pr_event(payload: dict, settings: Settings) -> bool:
    """Whether a ``pull_request_review``/``pull_request_review_comment``
    delivery is worth dispatching at all (same shape as
    :func:`is_qualifying_comment`, minus the ``issue_comment``-specific
    ``action`` check — every action on these two events may carry a body
    worth reading, e.g. a review edited to add a summary)."""
    return _known_repo(payload, settings)


def _is_bot_author(payload: dict, item_key: str) -> bool:
    user = (payload.get(item_key) or {}).get("user") or {}
    return user.get("type") == "Bot"


def is_bot_author(payload: dict) -> bool:
    """Whether an ``issue_comment`` payload's author is a ``Bot`` account."""
    return _is_bot_author(payload, "comment")


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return parse_iso(value)


def _extract_repo_and_pr_number(
    payload: dict, pr_key: str
) -> tuple[str, int] | None:
    """``(repo, pr/issue number)`` from ``payload``'s ``repository`` and
    ``pr_key`` (``"issue"`` for ``issue_comment``, ``"pull_request"`` for
    the two ``pull_request_review*`` events)."""
    repo = (payload.get("repository") or {}).get("full_name")
    number = (payload.get(pr_key) or {}).get("number")
    if not repo or number is None:
        return None
    return repo, number


def _build_review_feedback(
    payload: dict, *, pr_key: str, item_key: str,
    external_id_fn: Callable[[str, int], str], time_key: str,
) -> tuple[Feedback, str] | None:
    """
    Shared builder for every review-origin ``Feedback`` shape.

    The three review-origin events (PR-conversation comment, review
    summary, inline review comment) differ only in *where* the PR number
    lives, *which* payload key carries the item, *how* its external_id is
    minted, and *which* field holds its timestamp — everything else
    (author/body extraction, the ``"owner/name#<pr-number>"`` routing ref)
    is identical, so it lives here once rather than three times over
    (this repo's jscpd copy-paste budget is thin).
    """
    located = _extract_repo_and_pr_number(payload, pr_key)
    if located is None:
        return None
    repo, number = located
    item = payload.get(item_key) or {}
    item_id = item.get("id")
    if item_id is None:
        return None
    user = item.get("user") or {}
    feedback = Feedback(
        external_id=external_id_fn(repo, item_id),
        origin="review",
        author=user.get("login", ""),
        body=item.get("body") or "",
        created_at=_parse_time(item.get(time_key)),
    )
    return feedback, f"{repo}#{number}"


def build_ticket_feedback(payload: dict) -> tuple[Feedback, str] | None:
    """
    Build a ``(Feedback, task_ref)`` pair from a ticket ``issue_comment``.

    :returns: ``None`` when a required field is missing.
    """
    comment = payload.get("comment") or {}
    issue = payload.get("issue") or {}
    repo = (payload.get("repository") or {}).get("full_name")
    number = issue.get("number")
    comment_id = comment.get("id")
    if not repo or number is None or comment_id is None:
        return None
    user = comment.get("user") or {}
    feedback = Feedback(
        external_id=f"gh-issue-comment:{repo}#{comment_id}",
        origin="ticket",
        author=user.get("login", ""),
        body=comment.get("body") or "",
        created_at=_parse_time(comment.get("created_at")),
    )
    return feedback, f"{repo}#{number}"


def build_pr_conversation_feedback(
    payload: dict,
) -> tuple[Feedback, str] | None:
    """Build review-origin ``Feedback`` from a PR-conversation comment
    (an ``issue_comment`` whose ``issue`` carries a ``pull_request`` key)."""
    return _build_review_feedback(
        payload, pr_key="issue", item_key="comment",
        external_id_fn=github_reviews.mint_conversation_id,
        time_key="created_at",
    )


def build_review_feedback(payload: dict) -> tuple[Feedback, str] | None:
    """Build review-origin ``Feedback`` from a ``pull_request_review``."""
    return _build_review_feedback(
        payload, pr_key="pull_request", item_key="review",
        external_id_fn=github_reviews.mint_review_id,
        time_key="submitted_at",
    )


def build_review_comment_feedback(
    payload: dict,
) -> tuple[Feedback, str] | None:
    """Build review-origin ``Feedback`` from a
    ``pull_request_review_comment`` (an inline, diff-anchored comment)."""
    return _build_review_feedback(
        payload, pr_key="pull_request", item_key="comment",
        external_id_fn=github_reviews.mint_review_comment_id,
        time_key="created_at",
    )


async def handle_issue_comment(
    payload: dict,
    settings: Settings,
    intake: FeedbackIntakeService,
    source: GitHubTaskSource,
) -> str:
    """
    Handle one ``issue_comment`` webhook delivery.

    ``settings`` is the request-scoped settings the router already
    resolved via ``Depends`` — passed in rather than re-fetched here, so
    a test's dependency-injected settings actually apply (mirrors how the
    ``issues`` event branch already uses the router's own ``settings``).
    Ticket comments and PR-conversation comments both acknowledge through
    the SAME ``GitHubTaskSource`` (the issues reactions endpoint is
    shared by both — see ``github_reviews.parse_review_external_id``).

    :returns: An outcome tag (``"ignored"`` | ``"accepted"``) for logging.
    """
    if not is_qualifying_comment(payload, settings):
        return "ignored"
    built = (
        build_ticket_feedback(payload) if is_ticket_comment(payload)
        else build_pr_conversation_feedback(payload)
    )
    if built is None:
        return "ignored"
    feedback, ref = built
    await intake.intake(
        feedback, task_ref=ref, source=source,
        is_bot=is_bot_author(payload),
    )
    return "accepted"


async def handle_pull_request_review(
    payload: dict,
    settings: Settings,
    intake: FeedbackIntakeService,
    code_host: GitHubCodeHost,
) -> str:
    """Handle one ``pull_request_review`` webhook delivery (feature 013,
    US3) — acknowledges through the ``GitHubCodeHost`` seam (this event's
    external_id has no reaction endpoint, so ``acknowledge`` is always a
    no-op here, but the port shape stays uniform)."""
    if not is_qualifying_pr_event(payload, settings):
        return "ignored"
    built = build_review_feedback(payload)
    if built is None:
        return "ignored"
    feedback, ref = built
    await intake.intake(
        feedback, task_ref=ref, source=code_host,
        is_bot=_is_bot_author(payload, "review"),
    )
    return "accepted"


async def handle_pull_request_review_comment(
    payload: dict,
    settings: Settings,
    intake: FeedbackIntakeService,
    code_host: GitHubCodeHost,
) -> str:
    """Handle one ``pull_request_review_comment`` webhook delivery
    (feature 013, US3) — an inline, diff-anchored review comment."""
    if not is_qualifying_pr_event(payload, settings):
        return "ignored"
    built = build_review_comment_feedback(payload)
    if built is None:
        return "ignored"
    feedback, ref = built
    await intake.intake(
        feedback, task_ref=ref, source=code_host,
        is_bot=_is_bot_author(payload, "comment"),
    )
    return "accepted"


@lru_cache
def get_feedback_github_source() -> GitHubTaskSource:
    """The process-wide GitHubTaskSource used to acknowledge feedback."""
    settings = get_settings()
    client = GitHubClient(settings.github_api_base, settings.github_token)
    return GitHubTaskSource(client, settings.public_base_url)


@lru_cache
def get_feedback_github_codehost() -> GitHubCodeHost:
    """The process-wide GitHubCodeHost used to read/acknowledge review
    feedback (feature 013, US3)."""
    settings = get_settings()
    client = GitHubClient(settings.github_api_base, settings.github_token)
    return GitHubCodeHost(client, settings.git_base)
