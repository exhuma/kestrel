"""Single convergence point every feedback transport funnels through.

Both the GitHub webhook (``issue_comment``) and the poll backstop (Jira,
fixture, and GitHub's own missed-delivery recovery) call
:meth:`FeedbackIntakeService.intake` with one piece of raw ``Feedback`` —
this is the one place the marker gate, author guard, and cross-transport
dedup (feature 013,
``specs/013-feedback-intake/contracts/feedback-dispatch.md``) are
enforced, so no transport can bypass any of the three (research.md
R1/R3/R6).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from functools import lru_cache
from typing import Callable

from app.config import Settings, get_settings
from app.models_workflow import WorkflowRun
from app.persistence.feedback_store import FeedbackStore, get_feedback_store
from app.persistence.tables import FeedbackItemRow
from app.ports import Acknowledgeable, Feedback, FeedbackSource
from app.services.feedback.bootstrap import get_feedback_dispatcher
from app.services.feedback.marker import has_marker, is_ignored_author
from app.services.feedback.review import is_kestrel_review_request, review_token
from app.services.feedback.source import feedback_source_for
from app.services.github import change_request_number
from app.services.translation import Translator, get_translator
from app.services.workflows import WorkflowService, get_workflow_service

_log = logging.getLogger("kestrel.feedback.intake")


class FeedbackIntakeService:
    """Gates, dedups, routes, and persists one piece of raw feedback."""

    def __init__(
        self,
        settings: Settings,
        store: FeedbackStore,
        workflows: WorkflowService,
        dispatch: Callable[[FeedbackItemRow], str | None],
        translator: Translator | None = None,
    ) -> None:
        self._settings = settings
        self._store = store
        self._workflows = workflows
        self._dispatch = dispatch
        self._translator = translator

    async def intake(
        self,
        feedback: Feedback,
        *,
        task_ref: str,
        source: Acknowledgeable | FeedbackSource,
        is_bot: bool = False,
    ) -> None:
        """
        Run one piece of raw feedback through the full intake pipeline.

        Marker gate -> author guard -> claim -> route -> persist -> hand
        off to the dispatcher -> best-effort acknowledge. Anything that
        fails an earlier step returns silently — never persisted, never
        dispatched (FR-003's "never even recorded").

        :param feedback: The port-level read result (a webhook payload's
            comment, or a ``list_comments`` item).
        :param task_ref: The originating ticket's source-native ref —
            how ticket-origin feedback is routed to a run.
        :param source: The feedback source that read ``feedback``. Direct
            webhook ``TaskSource``/``CodeHost`` callers are adapted for
            compatibility.
        :param is_bot: Whether the caller has already identified the
            author as a bot account (GitHub's ``user.type == "Bot"``);
            transports with no such concept leave this ``False``.
        """
        if not self._is_review_response(feedback.body):
            return
        if is_kestrel_review_request(feedback.body):
            return
        if is_ignored_author(
            feedback.author,
            self._settings.feedback_ignore_authors,
            is_bot=is_bot,
        ):
            return
        run = self._route(feedback, task_ref)
        item = FeedbackItemRow(
            external_id=feedback.external_id,
            workflow_id=run.id if run else None,
            task_ref=task_ref,
            origin=feedback.origin,
            author=feedback.author,
            body=feedback.body,
            state="queued",
            created_at=datetime.now(timezone.utc),
        )
        if not self._store.claim(item):
            return  # dedup hit: a webhook/poll race, or a re-delivery
        feedback_source = feedback_source_for(source, task_ref)
        outcome = self._dispatch(item)
        await self._acknowledge(feedback_source, feedback)
        if outcome == "clarify":
            await feedback_source.reply(
                feedback,
                "Please reply with approve, reject, or request changes.",
            )
        await self._translate_and_reply(feedback_source, feedback)

    def _is_review_response(self, body: str) -> bool:
        """Whether ``body`` has the marker or a candidate revision token."""
        return (
            has_marker(body, self._settings.feedback_marker)
            or review_token(body) is not None
        )

    def _route(self, feedback: Feedback, task_ref: str) -> WorkflowRun | None:
        """
        The run this feedback targets, or ``None`` (not yet routable).

        Ticket-origin feedback goes to the newest run for ``task_ref``.
        Review-origin feedback (feature 013, US3) instead routes by the
        change request it was left on — ``task_ref`` then carries the
        PR's own identity ``"owner/name#<pr-number>"`` (minted by the
        webhook/poll caller, e.g. ``github_events.py``), NOT the run's
        ticket ``task_ref``: a run's ``task_ref`` is its *original*
        ticket, unrelated to whichever PR number it happened to open.
        """
        if feedback.origin == "ticket":
            return self._route_ticket(task_ref)
        if feedback.origin == "review":
            return self._route_review(task_ref)
        return None

    def _route_ticket(self, task_ref: str) -> WorkflowRun | None:
        matches = [r for r in self._workflows.list() if r.task_ref == task_ref]
        return matches[-1] if matches else None

    def _route_review(self, pr_ref: str) -> WorkflowRun | None:
        repo, _, num_str = pr_ref.rpartition("#")
        if not repo or not num_str.isdigit():
            return None
        number = int(num_str)
        matches = [
            r
            for r in self._workflows.list()
            if r.repo == repo and _run_pr_number(r) == number
        ]
        return matches[-1] if matches else None

    async def _acknowledge(
        self, source: FeedbackSource, feedback: Feedback
    ) -> None:
        try:
            if not await source.acknowledge(feedback):
                await source.reply(feedback, "Acknowledged.")
        except Exception:  # best-effort, never blocks intake
            _log.exception(
                "failed to acknowledge feedback %s", feedback.external_id
            )

    async def _translate_and_reply(
        self, source: FeedbackSource, feedback: Feedback
    ) -> None:
        """Post a translation disclaimer when a configured client needs one."""
        if self._translator is None:
            return
        try:
            translated = await self._translator.translate(feedback.body)
            if translated != feedback.body:
                await source.reply(
                    feedback,
                    _translation_reply(
                        translated, self._settings.feedback_marker
                    ),
                )
        except Exception:  # translation must not block workflow
            _log.exception(
                "failed to translate feedback %s", feedback.external_id
            )


def _run_pr_number(run: WorkflowRun) -> int | None:
    """A run's PR number: ``run.pr_number`` if set, else parsed from
    ``run.pr_url`` (a pre-migration row with no ``pr_number`` yet)."""
    return run.pr_number or change_request_number(run.pr_url or "")


def _translation_reply(translation: str, marker: str) -> str:
    """Render the visible warning accompanying automated English text."""
    quoted = re.sub(
        re.escape(marker), "", translation, flags=re.IGNORECASE
    ).strip()
    return (
        f"Automated English translation (may contain mistakes):\n\n> {quoted}"
    )


@lru_cache
def get_feedback_intake_service() -> FeedbackIntakeService:
    """Return the process-wide FeedbackIntakeService singleton."""
    return FeedbackIntakeService(
        get_settings(),
        get_feedback_store(),
        get_workflow_service(),
        get_feedback_dispatcher().dispatch,
        get_translator(),
    )
