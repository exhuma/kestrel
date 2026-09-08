"""Tests for reentry.rewind_to (feature 013, US3)."""
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


def test_rewind_to_refine_marks_everything_after_pending() -> None:
    """Rewinding to refine (the first step): nothing is "before" it, so
    every step becomes pending; the target (refine) keeps its session_id
    (it's the target, not "after" it), the rest clear theirs; deliverables
    survive everywhere."""
    run = _run()
    rewind_to(run, Step.REFINE, "reconsider the whole approach")

    assert [s.status for s in run.steps] == ["pending"] * 4
    assert run.steps[0].session_id == "sess-refine"
    assert [s.session_id for s in run.steps[1:]] == [None, None, None]
    assert [s.deliverable for s in run.steps] == [
        "refine-deliverable", "design-deliverable",
        "code-deliverable", "verify-deliverable",
    ]


def test_rewind_to_design_marks_before_done_target_and_after_pending() -> None:
    """Rewinding to design: refine stays done, design becomes pending
    (session_id untouched — it's the target, not "after" it), code/verify
    become pending with session_id cleared."""
    run = _run()
    rewind_to(run, Step.DESIGN, "the approach needs to change")

    refine, design, code, verify = run.steps
    assert refine.status == "done"
    assert refine.session_id == "sess-refine"  # before: untouched
    assert design.status == "pending"
    assert design.session_id == "sess-design"  # target: session untouched
    assert code.status == "pending"
    assert code.session_id is None
    assert verify.status == "pending"
    assert verify.session_id is None
    # Deliverables are never touched by rewind_to itself.
    assert refine.deliverable == "refine-deliverable"
    assert design.deliverable == "design-deliverable"


def test_rewind_to_code_marks_refine_and_design_done() -> None:
    """Rewinding to code: refine+design stay done, code becomes the
    pending target, verify resets with session_id cleared."""
    run = _run()
    rewind_to(run, Step.CODE, "fix the implementation bug")

    refine, design, code, verify = run.steps
    assert refine.status == "done"
    assert design.status == "done"
    assert code.status == "pending"
    assert code.session_id == "sess-code"
    assert verify.status == "pending"
    assert verify.session_id is None


def test_rewind_to_code_resets_verify_round() -> None:
    """Ensure verify_round resets to 0 when verify is rewound past (it is
    always "after" a code-or-earlier target)."""
    run = _run()
    run.steps[3].verify_round = 3
    rewind_to(run, Step.CODE, "fix it")
    assert run.steps[3].verify_round == 0


def test_rewind_to_rejects_verify_as_a_target() -> None:
    """Ensure verify — reached only by falling through code, never
    re-entered on its own — is not a legal rewind target."""
    run = _run()
    with pytest.raises(ValueError):
        rewind_to(run, Step.VERIFY, "anything")
