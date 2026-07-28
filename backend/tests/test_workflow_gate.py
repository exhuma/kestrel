"""Tests for app.services.workflows.gate (human-gate + interview replies)."""
from __future__ import annotations

import pytest

from app.models_workflow import WorkflowRun, WorkflowStep
from app.questionnaire import AnswerValidationError, parse_envelope
from app.services.exceptions import InvalidWorkflowStateError
from app.storage.registry import SessionRegistry
from tests.conftest import (
    _coord,
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _q,
    _qs,
    _service,
    _settings,
    _wait,
)


@pytest.mark.asyncio
async def test_reply_wrong_state_raises() -> None:
    """Ensure reply outside the refine interview raises InvalidWorkflowState."""
    svc = _service(_FakeGitHub(), _FakeRunner(SessionRegistry(), ["x"]),
                   _FakeGit())
    run = WorkflowRun(id="wf", repo="o/r", issue_number=1,
                      steps=[WorkflowStep(name="refine", status="pending")])
    svc.workflows.create(run)
    svc._control["wf"] = svc._new_control()  # needs a running loop
    with pytest.raises(InvalidWorkflowStateError):
        svc.reply("wf", "an answer")


@pytest.mark.asyncio
async def test_reject_with_refinement_regenerates() -> None:
    """Ensure gate feedback regenerates the refined issue via the writer."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord([]), "<REFINED_ISSUE>\nv1\n</REFINED_ISSUE>",
        "<REFINED_ISSUE>\nv2 with feedback\n</REFINED_ISSUE>",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_refine_approval"
    )
    svc.reject(wid, refinement_prompt="Mention the API surface")
    await _wait(
        lambda: svc.get(wid).steps[0].deliverable
        == "v2 with feedback"
    )
    assert svc.get(wid).status == "awaiting_refine_approval"
    # The writer sees the current body and the feedback.
    assert "Mention the API surface" in runner.calls[-1]["prompt"]
    assert "v1" in runner.calls[-1]["prompt"]


@pytest.mark.asyncio
async def test_submit_answers_validates() -> None:
    """Ensure invalid answers raise without resuming the interview."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["developer"]),
        _qs(_q(prompt="Which?",
               options=[{"value": "oidc", "label": "OIDC"}])),
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_refine_input"
    )
    with pytest.raises(AnswerValidationError):
        svc.submit_answers(wid, {"developer:q0": "saml"})
    assert len(runner.calls) == 2  # coordinator + one generator only


@pytest.mark.asyncio
async def test_incomplete_submission_rejected_by_default() -> None:
    """Ensure a required question left blank is rejected without the flag."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["developer"]),
        _qs(_q(qid="q1", prompt="Which?",
               options=[{"value": "oidc", "label": "OIDC"}])),
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")
    with pytest.raises(AnswerValidationError):
        svc.submit_answers(wid, {})  # required question unanswered


@pytest.mark.asyncio
async def test_allow_incomplete_answers_accepts_partial_submission() -> None:
    """Ensure the safety-net flag lets a required question go through blank."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["developer"]),
        _qs(_q(qid="q1", prompt="Which?",
               options=[{"value": "oidc", "label": "OIDC"}])),
        _coord([]),            # next round: nothing more to ask
        "<REFINED_ISSUE>\ndone\n</REFINED_ISSUE>",
    ])
    svc = _service(
        gh, runner, _FakeGit(),
        settings=_settings(allow_incomplete_answers=True),
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")
    svc.submit_answers(wid, {})  # tolerated: the interview advances
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")


@pytest.mark.asyncio
async def test_draft_save_persists_without_resuming() -> None:
    """Ensure a partial draft is stored and the agent is not resumed."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["developer"]),
        _qs(_q(prompt="Which?",
               options=[{"value": "a", "label": "A"}])),
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_refine_input"
    )
    round_before = svc.get(wid).steps[0].refine_round
    svc.save_draft(wid, {"developer:q0": "a"})
    # Still parked at the interview; no further agent call fired.
    assert svc.get(wid).status == "awaiting_refine_input"
    assert len(runner.calls) == 2
    envelope = parse_envelope(svc.get(wid).steps[0].deliverable)
    assert envelope.draft_answers == {"developer:q0": "a"}
    # A draft save must never look like a genuine questionnaire change.
    assert svc.get(wid).steps[0].refine_round == round_before


@pytest.mark.asyncio
async def test_refine_round_increments_across_interview_rounds() -> None:
    """Ensure refine_round bumps only when a new questionnaire is
    genuinely produced, not on a draft save or an unrelated update."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["developer"]),
        _qs(_q(prompt="Which?",
               options=[{"value": "a", "label": "A"}])),
        _coord(["developer"]),
        _qs(_q(prompt="Which again?",
               options=[{"value": "b", "label": "B"}])),
        _coord([]),
        "<REFINED_ISSUE>\nUse A then B\n</REFINED_ISSUE>",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_refine_input"
    )
    assert svc.get(wid).steps[0].refine_round == 1

    svc.submit_answers(wid, {"developer:q0": "a"})
    await _wait(
        lambda: svc.get(wid).steps[0].refine_round == 2
    )
    assert svc.get(wid).status == "awaiting_refine_input"

    svc.submit_answers(wid, {"developer:q0": "b"})
    await _wait(
        lambda: svc.get(wid).status == "awaiting_refine_approval"
    )


@pytest.mark.asyncio
async def test_finalize_requires_completeness() -> None:
    """Ensure finalize refuses an incomplete answer set."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["developer"]),
        _qs(_q(prompt="Which?",
               options=[{"value": "a", "label": "A"}])),
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_refine_input"
    )
    with pytest.raises(AnswerValidationError):
        svc.submit_answers(wid, {})  # required question unanswered
    assert svc.get(wid).status == "awaiting_refine_input"


@pytest.mark.asyncio
async def test_reply_targets_whichever_step_is_awaiting_input() -> None:
    """Ensure reply routes to a non-refine step awaiting input."""
    svc = _service(
        _FakeGitHub(), _FakeRunner(SessionRegistry(), ["x"]), _FakeGit()
    )
    run = WorkflowRun(
        id="wf", repo="o/r", issue_number=1,
        steps=[
            WorkflowStep(name="refine", status="done"),
            WorkflowStep(name="plan", status="done"),
            WorkflowStep(
                name="implement", status="awaiting_input",
                deliverable="Which file name?",
            ),
        ],
    )
    svc.workflows.create(run)
    svc._control["wf"] = svc._new_control()

    svc.reply("wf", "config.yaml")
    queued = await svc._control["wf"].replies.get()
    assert queued == "config.yaml"


@pytest.mark.asyncio
async def test_submit_answers_targets_whichever_step_is_awaiting_input() -> (
    None
):
    """Ensure submit_answers validates against the active step."""
    questionnaire = (
        '{"questions": [{"id": "q1", "prompt": "Which?", '
        '"type": "single_select", "required": true, '
        '"options": [{"value": "a", "label": "A"}]}]}'
    )
    svc = _service(
        _FakeGitHub(), _FakeRunner(SessionRegistry(), ["x"]), _FakeGit()
    )
    run = WorkflowRun(
        id="wf", repo="o/r", issue_number=1,
        steps=[
            WorkflowStep(name="refine", status="done"),
            WorkflowStep(name="plan", status="done"),
            WorkflowStep(
                name="implement", status="awaiting_input",
                deliverable=questionnaire,
            ),
        ],
    )
    svc.workflows.create(run)
    svc._control["wf"] = svc._new_control()

    svc.submit_answers("wf", {"q1": "a"})
    queued = await svc._control["wf"].replies.get()
    assert "ANSWERS:" in queued
