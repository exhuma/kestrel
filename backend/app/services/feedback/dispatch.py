"""Branches a claimed feedback item on its target run's current status.

The human-gate branch (feature 013, User Story 1) applies feedback to a
run parked at an approval gate exactly as a UI reject-with-feedback would
(``specs/013-feedback-intake/contracts/feedback-dispatch.md``). Every
transient, no-gate status (User Story 2) instead leaves the item
``queued`` for :func:`drain_feedback` to pick up at the next round/step
boundary the driver's own control flow reaches on its own — never by
interrupting a turn already in flight. An ``escalated`` run (User Story
4: it gave up, never delivering) is retried from its last usable
foundation. A ``done`` run (User Story 3's "the PR is still open" case,
and User Story 4's "it's since merged/closed/never existed" case)
resolves its change request's state and either resumes the same branch
or starts a linked successor — for either ticket- or review-origin
feedback alike, since a finished run has no gate of its own left for
either kind to land on more directly.

This module deliberately carries no *module-level* import of
``app.services.workflows`` (or of ``app.services.ingestion``, which
itself imports ``app.services.workflows``): that package's own
``__init__`` imports the ``driver`` subpackage during init, and the
driver submodules import :func:`drain_feedback` from here — a top-level
import back into either of those from this file would be a real
circular import, not just an architectural smell. ``WorkflowService``/
``WorkflowRun``/``IngestionService`` are therefore only referenced under
``TYPE_CHECKING`` (safe: with ``from __future__ import annotations``, an
annotation is never evaluated at runtime); every method on them is
called by name at runtime instead of importing a driver submodule
directly, for the same reason. The process-wide ``FeedbackDispatcher``
singleton — the one thing here that genuinely needs live instances of
both — lives in ``feedback/bootstrap.py`` instead, mirroring
``app.services.workflows.bootstrap``'s existing split.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.persistence.feedback_store import FeedbackStore
from app.persistence.tables import FeedbackItemRow
from app.services.exceptions import WorkflowNotFoundError
from app.services.github import change_request_number

if TYPE_CHECKING:
    from app.models_workflow import WorkflowRun
    from app.services.ingestion import IngestionService
    from app.services.workflows import WorkflowService

_log = logging.getLogger("kestrel.feedback.dispatch")

#: Statuses with an open human gate a reject-with-feedback can resolve.
#: ``awaiting_describe_approval`` is not yet a reachable status in this
#: codebase (feature 012's describe/decompose steps land separately) but
#: is included per the approved contract so no rewiring is needed once it
#: is — it is simply always-false until then.
_GATE_STATUSES = frozenset(
    {"awaiting_describe_approval", "awaiting_refine_approval"}
)

#: Fire-and-forget review-dispatch tasks, kept referenced so they are not
#: GC'd mid-flight (mirrors ``routers/github_webhook.py``'s own
#: ``_TASKS`` set) — :meth:`FeedbackDispatcher.dispatch` is a synchronous
#: call (``FeedbackIntakeService.intake`` never awaits it), but resolving
#: a review's change-request state is a real HTTP call.
_REVIEW_TASKS: set[asyncio.Task] = set()


def _fire_and_forget(coro) -> None:
    task = asyncio.create_task(coro)
    _REVIEW_TASKS.add(task)
    task.add_done_callback(_REVIEW_TASKS.discard)


class FeedbackDispatcher:
    """Applies or queues one claimed feedback item, by the run's status."""

    def __init__(
        self,
        workflows: "WorkflowService",
        store: FeedbackStore,
        ingestion: "IngestionService | None" = None,
    ) -> None:
        self._workflows = workflows
        self._store = store
        #: Backs the ``done``+merged/closed successor path (feature 013,
        #: US4). ``None`` is a safe no-op (logged, item stays queued) —
        #: unit tests that don't exercise that branch need not provide
        #: one; the real composition root (``feedback/bootstrap.py``)
        #: always wires the process-wide singleton.
        self._ingestion = ingestion

    def dispatch(self, item: FeedbackItemRow) -> None:
        """
        Act on ``item`` per its target run's *current* status.

        A no-op (stays ``queued``) when there is no target run yet, the
        run is unknown, or the run's status is not one this phase
        handles — including every transient, no-open-gate status
        (``describing``/``refining``/``analyzing``/``designing``/
        ``coding``/``verifying``/``opening_pr``), which
        :func:`drain_feedback` consumes later, at a boundary the run
        reaches on its own, and ``failed``/``rejected`` (ended for cause,
        not something feedback re-drives).

        :param item: The already-claimed, persisted feedback row.
        """
        run = self._target_run(item)
        if run is None:
            return
        if run.status in _GATE_STATUSES:
            self._dispatch_gate(item, run)
        elif run.status == "escalated":
            self._dispatch_escalated(item, run)
        elif run.status == "done":
            self._dispatch_done(item, run)

    def _dispatch_escalated(
        self, item: FeedbackItemRow, run: "WorkflowRun"
    ) -> None:
        """
        Retry a gave-up run with the feedback as guidance (US4).

        Escalation never pushes a branch, so there is nothing to check a
        change request's state against first — straight to
        ``resume_with_feedback``, whose own branch-resume path falls
        back to a fresh branch off ``base_branch`` because
        ``run.pr_number`` is unset for a run that reaches this branch
        (see ``driver/branch_resume.py``).
        """
        self._store.mark(item.external_id, "dispatched")
        self._workflows.resume_with_feedback(run.id, item.body)

    def _dispatch_done(
        self, item: FeedbackItemRow, run: "WorkflowRun"
    ) -> None:
        """
        Revive-vs-successor for a finished run (US3's open-PR case, and
        US4's merged/closed/never-existed case).

        Resolves ``run.pr_number`` — falling back to parsing it out of
        ``run.pr_url`` for a pre-migration row that predates that column
        (no data-fix migration; see ``change_request_number``'s own
        docstring). The actual HTTP call (when a PR number resolves at
        all) and everything after it happen in a background task since
        this method is called synchronously.
        """
        pr_number = run.pr_number or change_request_number(run.pr_url or "")
        _fire_and_forget(self._revive_or_start_successor(item, run, pr_number))

    async def _revive_or_start_successor(
        self, item: FeedbackItemRow, run: "WorkflowRun", pr_number: int | None,
    ) -> None:
        """Resume ``run``'s branch if its PR is open; else a successor."""
        if pr_number is not None:
            state = await self._change_request_state(run, pr_number)
            if state is None:
                return  # a failed read stays queued, retried later
            if state == "open":
                self._store.mark(item.external_id, "dispatched")
                self._workflows.resume_with_feedback(run.id, item.body)
                return
        await self._start_successor(item, run)

    async def _change_request_state(
        self, run: "WorkflowRun", pr_number: int
    ) -> str | None:
        """``run``'s change request's lifecycle state, or ``None`` on a
        failed read (never raises)."""
        code_host = self._workflows.code_host_for(run)
        try:
            change_request = await code_host.get_change_request(
                run.repo, pr_number
            )
        except Exception:  # noqa: BLE001 — a failed read stays queued
            _log.exception(
                "failed to read change request state for run %s", run.id
            )
            return None
        return change_request.state

    async def _start_successor(
        self, item: FeedbackItemRow, run: "WorkflowRun"
    ) -> None:
        """Start a linked successor run continuing ``run`` (US4)."""
        if self._ingestion is None:
            _log.warning(
                "no ingestion service wired; cannot start a successor "
                "for run %s", run.id,
            )
            return
        successor_id = await self._ingestion.start_successor_run(parent=run)
        self._store.mark(item.external_id, "applied")
        _log.info(
            "feedback %s started successor run %s from parent %s",
            item.external_id, successor_id, run.id,
        )

    def _target_run(self, item: FeedbackItemRow):
        if item.workflow_id is None:
            return None
        try:
            return self._workflows.get(item.workflow_id)
        except WorkflowNotFoundError:
            _log.warning(
                "feedback %s targets unknown run %s",
                item.external_id, item.workflow_id,
            )
            return None

    def _dispatch_gate(self, item: FeedbackItemRow, run) -> None:
        self._workflows.reject(run.id, refinement_prompt=item.body)
        self._store.mark(item.external_id, "applied")


def drain_feedback(service: "WorkflowService", run: "WorkflowRun") -> str:
    """
    Consume every item still queued for ``run``, folding it into one
    block of text for the caller's next prompt.

    Called only at a boundary the driver's control flow already reaches
    on its own — the top of a ``code_and_verify`` round
    (``driver/code_verify.py``), or a step boundary in ``continue_run``
    (``driver/__init__.py``) — never via interruption of a turn already
    in flight (FR-007). Each drained item is marked ``applied``
    immediately: this is at-most-once delivery into whatever prompt the
    caller builds next, not a durable retry queue.

    Reads through ``service.feedback_store`` (rather than the module-
    level singleton) so a ``WorkflowService`` built without one — most
    unit tests that never exercise feedback — gets a safe no-op instead
    of an unexpected DB dependency.

    :param service: The owning ``WorkflowService`` — its
        ``feedback_store`` is queried, and its ``_debug_log`` records
        what was drained, mirroring how ``driver/code_verify.py`` already
        logs every round's prompt.
    :param run: The run whose queue to drain.
    :returns: The queued bodies joined into one block, oldest first, or
        ``""`` when nothing was queued (including when the service has
        no feedback store configured).
    """
    store = service.feedback_store
    if store is None:
        return ""
    items = store.queued_for(run.id)
    if not items:
        return ""
    for item in items:
        store.mark(item.external_id, "applied")
    drained = "\n\n".join(item.body for item in items)
    service._debug_log(run, "DRAINED FEEDBACK", drained)
    return drained
