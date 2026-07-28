"""Tests for the interview round loop and coordinator (interview/__init__)."""
from __future__ import annotations

import pytest

from app.backends.base import TurnResult
from app.questionnaire import parse_envelope
from app.storage.registry import SessionRegistry
from tests.conftest import (
    _coord,
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _q,
    _qs,
    _refined,
    _service,
    _settings,
    _wait,
)


@pytest.mark.asyncio
async def test_refine_question_visible_while_awaiting_input() -> None:
    """Ensure generated questions are surfaced in the interview envelope
    (tagged with their audience) so the UI can render the form."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["developer"]),
        _qs(_q(prompt="What should the widget look like?",
               qtype="free_text", options=[])),
        _coord([]),
        _refined("Build a blue widget"),
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)

    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")
    envelope = parse_envelope(svc.get(wid).steps[0].deliverable)
    question = envelope.questionnaire.questions[0]
    assert question.prompt == "What should the widget look like?"
    assert question.audience == "developer"
    assert question.id == "developer:q0"  # namespaced across profiles

    svc.submit_answers(wid, {"developer:q0": "A blue one"})
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    assert svc.get(wid).steps[0].deliverable == "Build a blue widget"


@pytest.mark.asyncio
async def test_questionnaire_deliverable_is_structured() -> None:
    """Ensure fan-out questions become an interview envelope and the
    finalized answers reach the writer."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["developer"]),
        _qs(_q(prompt="Which auth?",
               options=[{"value": "oidc", "label": "OIDC"}])),
        _coord([]),
        _refined("Use OIDC"),
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_refine_input"
    )
    envelope = parse_envelope(svc.get(wid).steps[0].deliverable)
    assert envelope.questionnaire.questions[0].id == "developer:q0"
    assert envelope.questionnaire.profiles[0].id == "developer"

    svc.submit_answers(wid, {"developer:q0": "oidc"})
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_refine_approval"
    )
    assert "ANSWERS SO FAR:" in runner.calls[-1]["prompt"]
    assert "OIDC" in runner.calls[-1]["prompt"]


@pytest.mark.asyncio
async def test_waiver_reason_lands_in_refined_issue() -> None:
    """Ensure a waived question's reason is written into the artifact as
    a deterministic 'Assumptions & accepted risks' section."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["infosec"]),
        _qs(_q(prompt="Encrypt at rest?", qtype="boolean",
               required=True, waiver_label="Accept this risk")),
        _coord([]),
        _refined("Store the widget data in S3"),
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_refine_input"
    )
    svc.submit_answers(wid, {
        "infosec:q0": {
            "waived": True,
            "reason": "Low sensitivity; risk accepted by owner",
        },
    })
    await _wait(
        lambda: svc.get(wid).status == "awaiting_refine_approval"
    )
    deliverable = svc.get(wid).steps[0].deliverable
    assert "Assumptions & accepted risks" in deliverable
    assert "risk accepted by owner" in deliverable
    assert "Store the widget data in S3" in deliverable

    # And on approval the whole artifact (risks included) is written back.
    svc.approve(wid)
    await _wait(lambda: gh.updated is not None)
    assert "Assumptions & accepted risks" in (gh.updated or "")


@pytest.mark.asyncio
async def test_coordinator_samples_union_across_runs() -> None:
    """Ensure refine_samples>1 UNIONs the coordinator's picks: a
    specialist named by only one sample is still summoned."""

    def _gen() -> str:
        return _qs(_q(prompt="Q?", options=[{"value": "a", "label": "A"}]))

    gh = _FakeGitHub(body="ship a user-facing, sensitive feature")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["uiux"]),               # coordinator sample 1
        _coord(["uiux", "infosec"]),    # coordinator sample 2 adds infosec
        _gen(), _gen(), _gen(), _gen(),  # 2 profiles x 2 samples
        # Reconciler re-emits one question per surviving audience.
        _qs(
            _q(qid="u", audience="uiux", prompt="Flow?",
               options=[{"value": "a", "label": "A"}]),
            _q(qid="s", audience="infosec", prompt="Threats?",
               options=[{"value": "b", "label": "B"}]),
        ),
    ])
    svc = _service(gh, runner, _FakeGit(),
                   settings=_settings(refine_samples=2))
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")

    envelope = parse_envelope(svc.get(wid).steps[0].deliverable)
    audiences = {q.audience for q in envelope.questionnaire.questions}
    assert audiences == {"uiux", "infosec"}


@pytest.mark.asyncio
async def test_failed_specialist_is_retried_then_hard_capped() -> None:
    """Ensure a persistently-failing specialist is retried on each submit,
    the round cap grows per retry, and it flips to hard after 3 retries."""

    class _RetryRunner(_FakeRunner):
        def __init__(self, sessions) -> None:
            super().__init__(sessions, outputs=[])
            self._coord_calls = 0

        async def run_turn(self, req, on_session_id=None):
            prompt = req.prompt
            if "refinement coordinator" in prompt:
                self._coord_calls += 1
                ids = ["infosec"] if self._coord_calls == 1 else []
                return TurnResult(session_id="c", final_text=_coord(ids))
            if "interviewing one stakeholder profile" in prompt:
                raise RuntimeError("simulated backend timeout")
            return TurnResult(session_id="w", final_text=_refined("done"))

    runner = _RetryRunner(SessionRegistry())
    svc = _service(_FakeGitHub(body="vague"), runner, _FakeGit())
    wid = await svc.create("o/r", 5)

    async def _round(n: int):
        await _wait(
            lambda: svc.get(wid).status == "awaiting_refine_input"
            and svc.get(wid).steps[0].refine_round == n
        )
        return parse_envelope(svc.get(wid).steps[0].deliverable or "")

    # Round 1: initial failure -> soft, base cap.
    env = await _round(1)
    assert env.attempts["infosec"] == 1
    assert env.round_cap == 3
    assert env.questionnaire.issues[0].severity == "soft"

    # Rounds 2-3: retried, still soft, cap grows one per retry round.
    for round_no, cap in ((2, 4), (3, 5)):
        svc.submit_answers(wid, {})
        env = await _round(round_no)
        assert env.attempts["infosec"] == round_no
        assert env.round_cap == cap
        assert env.questionnaire.issues[0].severity == "soft"

    # Round 4: the 3rd retry fails -> hard, cap at the ceiling.
    svc.submit_answers(wid, {})
    env = await _round(4)
    assert env.attempts["infosec"] == 4
    assert env.round_cap == 6
    assert env.questionnaire.issues[0].severity == "hard"

    # No longer retried: the run finalizes rather than looping.
    svc.submit_answers(wid, {})
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
