"""Composition root for replies on the ticket (feature 046, User Story 3).

Kept apart from ``bootstrap.py`` for its module-length budget; it builds
on the singletons there.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from functools import lru_cache
from typing import Any

from app.config import get_settings
from app.models_board import WorkCard
from app.persistence.board_store import get_board_store
from app.persistence.comment_store import CommentStore, get_comment_store
from app.policy import get_specialist_backend_policy
from app.services.board.bootstrap import (
    get_announcement_service,
    get_gates_service,
    get_quarantine_service,
    get_specialist_roster,
    schedule_gate_followup,
)
from app.services.board.comment_poll import CommentPollService
from app.services.board.liaison import LiaisonService
from app.services.board.replies import ReplyDeps, ReplyService
from app.services.task_sources import get_task_source_registry

_logger = logging.getLogger(__name__)

#: The task sources whose tickets are read for replies, and the channel a
#: decision taken there is credited to.
REPLY_CHANNELS = {"jira-issue": "jira"}

_running: set[asyncio.Task[Any]] = set()


@lru_cache
def get_liaison_service() -> LiaisonService:
    """Return the process-wide LiaisonService singleton. Its turn is as
    short as a screening one, so it shares that timeout."""
    return LiaisonService(
        get_specialist_roster(),
        get_specialist_backend_policy(),
        get_settings().board_input_security_timeout_seconds,
    )


@lru_cache
def get_reply_service() -> ReplyService:
    """Return the process-wide ReplyService singleton."""
    return ReplyService(ReplyDeps(
        store=get_board_store(),
        gates=get_gates_service(),
        comments=get_comment_store(),
        quarantine=get_quarantine_service(),
        liaison=get_liaison_service(),
        announcements=get_announcement_service(),
        task_sources=get_task_source_registry(),
        channels=REPLY_CHANNELS,
        marker=get_settings().feedback_marker,
        on_decided=_after_decision,
    ))


@lru_cache
def get_comment_poll_service() -> CommentPollService:
    """Return the process-wide CommentPollService singleton."""
    settings = get_settings()
    return CommentPollService(
        get_board_store(),
        get_comment_store(),
        get_reply_service(),
        interval_seconds=settings.board_comment_poll_interval_seconds,
        enabled=settings.comment_sentinel_enabled,
    )


class HeldReplies:
    """Continues the replies security reviews held (feature 046)."""

    def __init__(self, comments: CommentStore, replies: ReplyService) -> None:
        self._comments = comments
        self._replies = replies

    def schedule(self, review_id: str, *, released: bool) -> bool:
        """Continue the reply review *review_id* held, in the background:
        act on it when *released*, else tell the ticket it was not acted
        on.

        :returns: Whether the review held a reply at all (``False`` leaves
            it to task intake).
        """
        if self._comments.held_for_review(review_id) is None:
            return False
        work = (
            self._replies.continue_released(review_id) if released
            else self._replies.discarded(review_id)
        )
        _spawn(work, review_id)
        return True


@lru_cache
def get_held_replies() -> HeldReplies:
    """Return the process-wide HeldReplies singleton."""
    return HeldReplies(get_comment_store(), get_reply_service())


def _after_decision(workflow_id: str, card: WorkCard, decision: str) -> None:
    """What the UI path does after a decision, for one taken on the
    ticket. The reply's own confirmation stands in for the "gate
    decided" comment."""
    schedule_gate_followup(workflow_id, card, decision)


def _spawn(work: Coroutine[Any, Any, bool], review_id: str) -> None:
    task = asyncio.create_task(work)
    _running.add(task)
    task.add_done_callback(
        lambda t, rid=review_id: _after_spawn(t, rid)
    )


def _after_spawn(task: asyncio.Task[Any], review_id: str) -> None:
    _running.discard(task)
    if not task.cancelled() and task.exception() is not None:
        _logger.error(
            "continuing held reply review %s failed", review_id,
            exc_info=task.exception(),
        )
