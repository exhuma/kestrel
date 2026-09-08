"""Tests for reentry.rewind_to (feature 013, US3).

Runs against the real 6-step pipeline (feature 012):
describe(0) -> refine(1) -> gap_analysis(2) -> design(3) -> code(4) ->
verify(5).
"""
from __future__ import annotations

import pytest

from app.models_workflow import Step, WorkflowRun, WorkflowStep
from app.services.workflows.reentry import rewind_to


def _run() -> WorkflowRun:
    steps = [
        WorkflowStep(
            name=step, status="done", deliverable=f"{step}-deliverable",
            session_id=f"sess-{step}",
        )
        for step in Step.sequence()
    ]
    return WorkflowRun(
        id="wf-1", repo="o/r", task_ref="o/r#1", steps=steps,
    )


def test_rewind_to_describe_marks_everything_after_pending() -> None:
    """Rewinding to describe (the first step): nothing is "before" it, so
    every step becomes pending; the target (describe) keeps its
    session_id (it's the target, not "after" it), the rest clear theirs;
    deliverables survive everywhere."""
    run = _run()
    rewind_to(run, Step.DESCRIBE, "reconsider the whole approach")

    assert [s.status for s in run.steps] == ["pending"] * 6
    assert run.steps[0].session_id == "sess-describe"
    assert [s.session_id for s in run.steps[1:]] == [None] * 5
    assert [s.deliverable for s in run.steps] == [
        "describe-deliverable", "refine-deliverable",
        "gap_analysis-deliverable", "design-deliverable",
        "code-deliverable", "verify-deliverable",
    ]


def test_rewind_to_refine_marks_describe_done_and_rest_pending() -> None:
    """Rewinding to refine: describe stays done, refine becomes the
    pending target (session_id untouched), everything after it resets
    with session_id cleared."""
    run = _run()
    rewind_to(run, Step.REFINE, "the requirements need another look")

    describe, refine, gap_analysis, design, code, verify = run.steps
    assert describe.status == "done"
    assert describe.session_id == "sess-describe"  # before: untouched
    assert refine.status == "pending"
    assert refine.session_id == "sess-refine"  # target: session untouched
    for step in (gap_analysis, design, code, verify):
        assert step.status == "pending"
        assert step.session_id is None


def test_rewind_to_design_marks_before_done_target_and_after_pending() -> None:
    """Rewinding to design: describe/refine/gap_analysis stay done, design
    becomes the pending target (session_id untouched — it's the target,
    not "after" it), code/verify become pending with session_id cleared."""
    run = _run()
    rewind_to(run, Step.DESIGN, "the approach needs to change")

    describe, refine, gap_analysis, design, code, verify = run.steps
    for step in (describe, refine, gap_analysis):
        assert step.status == "done"
    assert design.status == "pending"
    assert design.session_id == "sess-design"  # target: session untouched
    assert code.status == "pending"
    assert code.session_id is None
    assert verify.status == "pending"
    assert verify.session_id is None
    # Deliverables are never touched by rewind_to itself.
    assert refine.deliverable == "refine-deliverable"
    assert design.deliverable == "design-deliverable"


def test_rewind_to_code_marks_earlier_steps_done() -> None:
    """Rewinding to code: describe/refine/gap_analysis/design stay done,
    code becomes the pending target, verify resets with session_id
    cleared."""
    run = _run()
    rewind_to(run, Step.CODE, "fix the implementation bug")

    describe, refine, gap_analysis, design, code, verify = run.steps
    for step in (describe, refine, gap_analysis, design):
        assert step.status == "done"
    assert code.status == "pending"
    assert code.session_id == "sess-code"
    assert verify.status == "pending"
    assert verify.session_id is None


def test_rewind_to_code_resets_verify_round() -> None:
    """Ensure verify_round resets to 0 when verify is rewound past (it is
    always "after" a code-or-earlier target)."""
    run = _run()
    run.steps[5].verify_round = 3  # verify is index 5, not 3, on this branch
    rewind_to(run, Step.CODE, "fix it")
    assert run.steps[5].verify_round == 0


def test_rewind_to_rejects_verify_as_a_target() -> None:
    """Ensure verify — reached only by falling through code, never
    re-entered on its own — is not a legal rewind target."""
    run = _run()
    with pytest.raises(ValueError):
        rewind_to(run, Step.VERIFY, "anything")


def test_rewind_to_rejects_gap_analysis_as_a_target() -> None:
    """Ensure gap_analysis — a fan-out/reconcile/critic turn, gateless and
    run-terminating on success — is not a legal rewind target; feeding
    drained feedback into it is a follow-up, not this mechanism."""
    run = _run()
    with pytest.raises(ValueError):
        rewind_to(run, Step.GAP_ANALYSIS, "anything")
