"""Reading replies on the tickets of active requests (feature 046,
research R8).

There is no webhook: every ``board_comment_poll_interval_seconds`` this
loop reads the new comments on the ticket of each request that is still
in progress and whose source has a reply channel, oldest first, and hands
each to :class:`~app.services.board.replies.ReplyService`. Where it got to
is kept per request (the adapter's opaque cursor); the boundary comment is
read again, and the comment store keeps each comment acted on at most
once.

kestrel recognises its own comments by the ownership marker it puts on
them. With comment marking turned off (``comment_sentinel_enabled =
false``) it could not, and would read its own announcements as replies,
so the loop then reads nothing.
"""
from __future__ import annotations

import asyncio
import logging

from app.models_board import TERMINAL_STATES, Workflow
from app.persistence.board_store import BoardStore
from app.persistence.comment_store import CommentStore
from app.ports import TaskSource
from app.services.board.replies import ReplyService

_logger = logging.getLogger("kestrel.board.comment_poll")


class CommentPollService:
    """Reads new ticket comments and hands them to the reply service."""

    def __init__(
        self,
        store: BoardStore,
        comments: CommentStore,
        replies: ReplyService,
        *,
        interval_seconds: float,
        enabled: bool = True,
    ) -> None:
        """
        :param enabled: ``False`` when kestrel's comments carry no
            ownership marker, so that it never answers itself.
        """
        self._store = store
        self._comments = comments
        self._replies = replies
        self._interval_seconds = interval_seconds
        self._enabled = enabled

    async def run_forever(self) -> None:
        """Read replies until cancelled; one bad cycle never stops the
        loop."""
        if not self._enabled:
            _logger.warning(
                "comment marking is off: kestrel cannot tell its own "
                "comments from replies, so ticket replies are not read"
            )
            return
        while True:
            try:
                await self.poll_once()
            except Exception:  # the loop must outlive a cycle
                _logger.exception("comment poll cycle failed")
            await asyncio.sleep(self._interval_seconds)

    async def poll_once(self) -> int:
        """Read every active request's new comments once.

        :returns: How many replies were taken on.
        """
        if not self._enabled:
            return 0
        taken = 0
        for workflow in self._store.list_workflows():
            source = self._replies.source_of(workflow)
            if source is None or not self._active(workflow):
                continue
            try:
                taken += await self._poll(workflow, source)
            except Exception:  # one ticket must not stop the others
                _logger.exception(
                    "workflow %s: reading ticket comments failed",
                    workflow.id,
                )
        return taken

    def _active(self, workflow: Workflow) -> bool:
        """Whether *workflow* is still in progress: a real request (not a
        quarantine placeholder) with a card that is not finished."""
        if workflow.state == "quarantined":
            return False
        return any(
            card.state not in TERMINAL_STATES
            for card in self._store.list_cards(workflow.id)
        )

    async def _poll(self, workflow: Workflow, source: TaskSource) -> int:
        """Hand *workflow*'s new comments over, oldest first, then move
        its read position on. A failure part-way leaves the position
        where it was; comments already taken on are not taken again."""
        cursor = self._comments.get_cursor(workflow.id)
        page = await source.list_comments(workflow.task_ref, cursor)
        taken = 0
        for feedback in sorted(page.comments, key=lambda f: f.created_at):
            if await self._replies.consider(workflow, feedback):
                taken += 1
        if page.cursor != cursor:
            self._comments.set_cursor(workflow.id, page.cursor)
        return taken
