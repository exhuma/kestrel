"""Pure re-entry state-shaping for a review-feedback-driven resume.

Generalizes the driver's existing pre-mark trick (``drive()`` seeding
``steps[0]`` as done before a fresh ``continue_run`` when a ticket already
carries the refined sentinel) to an arbitrary target step (feature 013,
US3): every step *before* the target is marked done (its deliverable
untouched — nothing already produced is thrown away), the target itself
becomes ``pending`` (so ``continue_run``'s own per-step branching
re-enters it on the next drive cycle), and every step *after* it is reset
to ``pending`` with its ``session_id`` cleared (no stale resume-id from a
prior cycle survives into a step that hasn't actually run yet this
cycle).

Deliberately pure — no I/O, no persistence, no direct injection of
``instruction`` into any prompt. The caller (``driver/resume.py``) saves
the mutated run and is responsible for getting ``instruction`` in front of
the target step's own turn — for ``design``/``code`` that is the same
``FeedbackStore``-backed ``drain_feedback`` boundary US2 already
established (``driver/code_verify.py``'s round start, and the pre-design
boundary in ``continue_run``); ``refine`` gained the analogous boundary
in this feature. No new prompt-consumption path was needed.
"""
from __future__ import annotations

import logging

from app.models_workflow import Step, WorkflowRun

_logger = logging.getLogger(__name__)

#: Steps a review-feedback triage turn may re-enter at, in pipeline order.
#: ``gap_analysis`` is excluded: it is a fan-out/reconcile/critic turn, not
#: a single prompt like describe/refine/design, and it is gateless and
#: run-terminating on success (feature 012) — feeding drained feedback
#: into it is left for a follow-up rather than bolted on here. ``verify``
#: is excluded too: it is always reached by falling through ``code``,
#: never re-entered on its own.
REENTRY_STEPS = (Step.DESCRIBE, Step.REFINE, Step.DESIGN, Step.CODE)


def rewind_to(run: WorkflowRun, step: Step, instruction: str) -> None:
    """
    Rewind ``run`` in place so its next drive cycle re-enters at ``step``.

    :param run: The run to mutate. ``run.steps`` is assumed to already be
        in :meth:`Step.sequence` order (true for every run created by
        this codebase).
    :param step: The re-entry target — one of :data:`REENTRY_STEPS`.
    :param instruction: The triage-derived, normalized restatement of the
        feedback (never the raw comment body). Not consumed here (this
        function is pure) — logged for the audit trail; getting it in
        front of ``step``'s own turn is the caller's job.
    :raises ValueError: If ``step`` is not a legal re-entry target on this
        branch's ``Step`` enum.
    """
    if step not in REENTRY_STEPS:
        raise ValueError(f"not a legal re-entry step: {step!r}")
    _logger.debug(
        "rewind_to run=%s target=%s instruction=%s", run.id, step,
        instruction,
    )
    target_index = Step.sequence().index(step)
    for index, wf_step in enumerate(run.steps):
        if index < target_index:
            wf_step.status = "done"
        elif index == target_index:
            wf_step.status = "pending"
        else:
            wf_step.status = "pending"
            wf_step.session_id = None
            if wf_step.name == Step.VERIFY:
                wf_step.verify_round = 0
