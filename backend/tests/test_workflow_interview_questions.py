"""Tests for question generation/reconciliation/critique.

Covers app.services.workflows.interview.questions.
"""
from __future__ import annotations

import asyncio

import pytest

from app.questionnaire import parse_envelope
from app.storage.registry import SessionRegistry
from tests.conftest import (
    _coord,
    _coverage,
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
async def test_malformed_questions_block_surfaces_as_soft_issue() -> None:
    """Ensure a profile whose generator output is malformed is recorded as
    a (retryable) soft issue rather than silently finalizing the run."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["developer"]),
        "<QUESTIONS>{not json}</QUESTIONS>",  # unparseable
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_refine_input"
    )
    envelope = parse_envelope(svc.get(wid).steps[0].deliverable or "")
    assert envelope is not None
    assert [i.severity for i in envelope.questionnaire.issues] == ["soft"]
    assert envelope.questionnaire.issues[0].profile == "developer"


@pytest.mark.asyncio
async def test_profiles_are_interviewed_concurrently() -> None:
    """Ensure the coordinator-selected profiles are interviewed at the
    same time (each in its own live session), not one after another."""

    class _BarrierRunner(_FakeRunner):
        """Holds every profile generator at a barrier until all have
        started, so the test can prove they overlap."""

        def __init__(self, sessions, outputs, expected) -> None:
            super().__init__(sessions, outputs)
            self.inflight = 0
            self.max_inflight = 0
            self._expected = expected
            self._all_in = asyncio.Event()

        async def run_turn(self, req, on_session_id=None):
            gen = "interviewing one stakeholder profile" in req.prompt
            if gen:
                self.inflight += 1
                self.max_inflight = max(self.max_inflight, self.inflight)
                if self.inflight >= self._expected:
                    self._all_in.set()
                await self._all_in.wait()
            result = await super().run_turn(req, on_session_id)
            if gen:
                self.inflight -= 1
            return result

    gh = _FakeGitHub(body="vague issue")
    runner = _BarrierRunner(SessionRegistry(), outputs=[
        _coord(["developer", "infosec"]),
        _qs(_q(prompt="Approach?",
               options=[{"value": "a", "label": "A"}])),
        _qs(_q(prompt="Threats?",
               options=[{"value": "b", "label": "B"}])),
        # Two distinct-audience questions: the reconciler runs and (here)
        # re-emits both unchanged, as they don't overlap.
        _qs(
            _q(qid="a", audience="developer", prompt="Approach?",
               options=[{"value": "a", "label": "A"}]),
            _q(qid="b", audience="infosec", prompt="Threats?",
               options=[{"value": "b", "label": "B"}]),
        ),
        _coord([]),
        _refined("done"),
    ], expected=2)
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")

    assert runner.max_inflight == 2  # both ran at once
    envelope = parse_envelope(svc.get(wid).steps[0].deliverable)
    audiences = {q.audience for q in envelope.questionnaire.questions}
    assert audiences == {"developer", "infosec"}


#: A two-profile round where Product and Eng ask the SAME accounts
#: decision with different framings — the reconciler's raison d'être.
def _overlapping_accounts_round() -> list[str]:
    return [
        _coord(["requester", "developer"]),
        _qs(_q(prompt="How should user accounts be created?",
               qtype="free_text", options=[])),
        _qs(_q(prompt="How are accounts created — open self-registration "
                      "or a fixed/seeded set of users?",
               options=[{"value": "signup", "label": "Self-service"},
                        {"value": "seeded", "label": "Seeded set"}])),
    ]


@pytest.mark.asyncio
async def test_reconciler_folds_overlap_into_one_simple_question() -> None:
    """Ensure the reconciler collapses a cross-profile overlap into a
    single, simply-phrased question owned by one profile."""
    gh = _FakeGitHub(body="let users sign in")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_overlapping_accounts_round(),
        # Reconciler folds both into ONE plain requester-owned question,
        # declaring the pool ids it absorbed so the coverage invariant
        # sees the developer question was folded, not silently dropped.
        _qs(_q(qid="x", audience="requester",
               prompt="How are accounts created?",
               folded_from=["requester:q0", "developer:q0"],
               options=[{"value": "signup", "label": "Self-service signup"},
                        {"value": "seeded", "label": "Fixed / seeded set"}])),
        _coord([]),
        _refined("Accounts are seeded"),
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")

    envelope = parse_envelope(svc.get(wid).steps[0].deliverable)
    questions = envelope.questionnaire.questions
    assert len(questions) == 1
    assert questions[0].prompt == "How are accounts created?"
    assert questions[0].audience == "requester"
    assert questions[0].id == "requester:r0"  # re-namespaced by the pass
    # Only the surviving audience yields a tab.
    assert [p.id for p in envelope.questionnaire.profiles] == ["requester"]


@pytest.mark.asyncio
async def test_reconciler_malformed_output_keeps_all() -> None:
    """Ensure a malformed reconciler block falls back to the full pool."""
    gh = _FakeGitHub(body="let users sign in")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_overlapping_accounts_round(),
        "<QUESTIONS>{not json}</QUESTIONS>",  # malformed: keep everything
        _coord([]),
        _refined("Accounts are seeded"),
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")

    envelope = parse_envelope(svc.get(wid).steps[0].deliverable)
    ids = {q.id for q in envelope.questionnaire.questions}
    assert ids == {"requester:q0", "developer:q0"}
    assert {p.id for p in envelope.questionnaire.profiles} == {
        "requester", "developer",
    }


@pytest.mark.asyncio
async def test_reconciler_unknown_audience_keeps_all() -> None:
    """Ensure a reconciled question naming a non-pool audience is
    rejected wholesale, falling back to the untouched pool."""
    gh = _FakeGitHub(body="let users sign in")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_overlapping_accounts_round(),
        # "martian" was never in the pool: unsafe → keep the pool.
        _qs(_q(qid="x", audience="martian",
               prompt="How are accounts created?",
               options=[{"value": "signup", "label": "Self-service"}])),
        _coord([]),
        _refined("Accounts are seeded"),
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")

    envelope = parse_envelope(svc.get(wid).steps[0].deliverable)
    ids = {q.id for q in envelope.questionnaire.questions}
    assert ids == {"requester:q0", "developer:q0"}


@pytest.mark.asyncio
async def test_reconciler_silent_audience_drop_keeps_all() -> None:
    """Ensure a rewrite that drops a whole audience WITHOUT declaring the
    fold is rejected — the coverage invariant keeps the full pool so no
    domain is silently lost (the cheap-model failure this guards)."""
    gh = _FakeGitHub(body="let users sign in")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_overlapping_accounts_round(),
        # Folds to one requester question but declares NO folded_from:
        # developer vanishes silently → invariant falls back to the pool.
        _qs(_q(qid="x", audience="requester",
               prompt="How are accounts created?",
               options=[{"value": "signup", "label": "Self-service"},
                        {"value": "seeded", "label": "Seeded set"}])),
        _coord([]),
        _refined("Accounts are seeded"),
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")

    envelope = parse_envelope(svc.get(wid).steps[0].deliverable)
    ids = {q.id for q in envelope.questionnaire.questions}
    assert ids == {"requester:q0", "developer:q0"}
    assert {p.id for p in envelope.questionnaire.profiles} == {
        "requester", "developer",
    }


@pytest.mark.asyncio
async def test_critic_reinjects_dropped_audience() -> None:
    """Ensure the completeness critic recovers a concern that a declared
    fold quietly softened away: the reconciler passes the invariant, the
    critic flags the audience, its pool question is re-injected."""
    gh = _FakeGitHub(body="let users sign in")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_overlapping_accounts_round(),
        # A declared fold: passes the coverage invariant (developer's id
        # is accounted for) — but the developer's concern is really gone.
        _qs(_q(qid="x", audience="requester",
               prompt="How are accounts created?",
               folded_from=["requester:q0", "developer:q0"],
               options=[{"value": "signup", "label": "Self-service"},
                        {"value": "seeded", "label": "Seeded set"}])),
        _coverage(requester=True, developer=False),  # critic: dev lost
        _coord([]),
        _refined("Accounts are seeded"),
    ])
    svc = _service(gh, runner, _FakeGit(),
                   settings=_settings(refine_critic=True))
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")

    envelope = parse_envelope(svc.get(wid).steps[0].deliverable)
    audiences = {q.audience for q in envelope.questionnaire.questions}
    assert audiences == {"requester", "developer"}  # developer recovered


@pytest.mark.asyncio
async def test_reconcile_mode_off_keeps_the_pool() -> None:
    """Ensure reconcile_mode='off' skips consolidation entirely and never
    calls a reconciler agent."""
    gh = _FakeGitHub(body="let users sign in")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_overlapping_accounts_round(),
        # No reconciler output supplied: if the pass ran, the fake would
        # pop the coordinator/writer blocks out of order and the run
        # would not reach the gate with both questions intact.
        _coord([]),
        _refined("Accounts are seeded"),
    ])
    svc = _service(gh, runner, _FakeGit(),
                   settings=_settings(reconcile_mode="off"))
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")

    envelope = parse_envelope(svc.get(wid).steps[0].deliverable)
    ids = {q.id for q in envelope.questionnaire.questions}
    assert ids == {"requester:q0", "developer:q0"}
    # No reconciler agent ran (its prompt's signature never appears).
    assert not any("interviewed in parallel" in c["prompt"].lower()
                   for c in runner.calls)


@pytest.mark.asyncio
async def test_one_failing_specialist_does_not_sink_the_refine() -> None:
    """Ensure a single profile's backend failure (e.g. an LLM timeout)
    doesn't fail the whole run — the panel proceeds on the survivors."""

    class _FlakyRunner(_FakeRunner):
        def __init__(self, sessions, outputs) -> None:
            super().__init__(sessions, outputs)
            self._failed_one = False

        async def run_turn(self, req, on_session_id=None):
            # Fail exactly one concurrent generator (atomic in asyncio:
            # no await between the check and the flag set).
            if ("interviewing one stakeholder profile" in req.prompt
                    and not self._failed_one):
                self._failed_one = True
                raise RuntimeError("simulated backend timeout")
            return await super().run_turn(req, on_session_id)

    gh = _FakeGitHub(body="vague issue")
    runner = _FlakyRunner(SessionRegistry(), outputs=[
        _coord(["requester", "infosec"]),   # coordinator selects two
        _qs(_q(qid="q1")),                   # the surviving profile's questions
    ])
    svc = _service(gh, runner, _FakeGit())

    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")
    assert svc.get(wid).status != "failed"


@pytest.mark.asyncio
async def test_optionless_select_is_coerced_to_free_text() -> None:
    """Ensure a select question with no options (weak model) becomes
    answerable free text — otherwise the UI renders no choices and the
    answer can only go to the optional note field, never registering."""
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["developer"]),
        _qs(_q(qid="q1", qtype="single_select", options=[])),  # no options
    ])
    svc = _service(_FakeGitHub(body="vague issue"), runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")

    env = parse_envelope(svc.get(wid).steps[0].deliverable or "")
    assert env is not None
    assert env.questionnaire.questions[0].type == "free_text"


@pytest.mark.asyncio
async def test_duplicate_question_ids_are_made_unique() -> None:
    """Ensure a weak model reusing a question id within one profile still
    yields unique namespaced ids, so the frontend answer map and v-for
    keys don't collide (some answers never registering)."""
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["developer"]),
        _qs(_q(qid="q1", prompt="A?"), _q(qid="q1", prompt="B?")),
    ])
    svc = _service(_FakeGitHub(body="vague issue"), runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")

    env = parse_envelope(svc.get(wid).steps[0].deliverable or "")
    assert env is not None
    ids = [q.id for q in env.questionnaire.questions]
    assert len(ids) == 2
    assert len(set(ids)) == 2  # unique despite the model reusing "q1"


@pytest.mark.asyncio
async def test_all_specialists_failing_is_retryable_not_fatal() -> None:
    """Ensure a round where every specialist fails is presented as soft
    issues (retryable on submit) rather than failing the whole run."""

    class _AllFlaky(_FakeRunner):
        async def run_turn(self, req, on_session_id=None):
            if "interviewing one stakeholder profile" in req.prompt:
                raise RuntimeError("simulated backend timeout")
            return await super().run_turn(req, on_session_id)

    runner = _AllFlaky(SessionRegistry(), outputs=[
        # coordinator ok; all generators fail
        _coord(["requester", "infosec"]),
    ])
    svc = _service(_FakeGitHub(body="vague"), runner, _FakeGit())

    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")
    assert svc.get(wid).status != "failed"
    envelope = parse_envelope(svc.get(wid).steps[0].deliverable or "")
    assert envelope is not None
    assert sorted(i.profile for i in envelope.questionnaire.issues) == [
        "infosec", "requester",
    ]
    assert all(
        i.severity == "soft" for i in envelope.questionnaire.issues
    )


@pytest.mark.asyncio
async def test_failed_specialist_recorded_in_questionnaire_issues() -> None:
    """Ensure a failed generator is recorded in the questionnaire's issues,
    surviving into the review gate after the live chips clear."""

    class _FlakyRunner(_FakeRunner):
        def __init__(self, sessions, outputs) -> None:
            super().__init__(sessions, outputs)
            self._failed_one = False

        async def run_turn(self, req, on_session_id=None):
            if ("interviewing one stakeholder profile" in req.prompt
                    and not self._failed_one):
                self._failed_one = True
                raise RuntimeError("simulated backend timeout")
            return await super().run_turn(req, on_session_id)

    runner = _FlakyRunner(SessionRegistry(), outputs=[
        _coord(["requester", "infosec"]),
        _qs(_q(qid="q1")),   # the surviving profile's questions
    ])
    svc = _service(_FakeGitHub(body="vague issue"), runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")

    envelope = parse_envelope(svc.get(wid).steps[0].deliverable or "")
    assert envelope is not None
    issues = envelope.questionnaire.issues
    assert len(issues) == 1
    assert "timeout" in issues[0].reason
    # The surviving profile still contributed; the failed one asked nothing.
    assert envelope.questionnaire.questions
    assert all(
        q.audience != issues[0].profile
        for q in envelope.questionnaire.questions
    )


@pytest.mark.asyncio
async def test_empty_generator_response_recorded_as_issue() -> None:
    """Ensure a profile that parses to no questionnaire is flagged, not
    silently dropped as a zero-question success."""
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["requester", "infosec"]),
        "I have no questions.",   # no <QUESTIONS> block -> unparseable
        _qs(_q(qid="q1")),        # the other profile answers
    ])
    svc = _service(_FakeGitHub(body="vague issue"), runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_input")

    envelope = parse_envelope(svc.get(wid).steps[0].deliverable or "")
    assert envelope is not None
    issues = envelope.questionnaire.issues
    assert len(issues) == 1
    assert "no response" in issues[0].reason
    assert envelope.questionnaire.questions
