"""Tests for the WorkflowService state machine (integrations faked)."""
from __future__ import annotations

import asyncio
import json

import pytest

from app.config import Settings
from app.models import ParsedEvent, SessionRecord
from app.questionnaire import AnswerValidationError
from app.services.exceptions import (
    InvalidWorkflowStateError,
    WorkflowNotFoundError,
)
from app.services.github import Issue
from app.services.workflows import WorkflowService
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry


class _FakeGit:
    def __init__(self) -> None:
        self.pushed: list[str] = []
        self.diffs: list[str] = ["diff --git a/x b/x"]

    async def clone(self, remote_url: str, dest: str) -> None: ...
    async def checkout_branch(self, dest: str, branch: str) -> None: ...
    async def commit_all(self, dest: str, message: str) -> None: ...
    async def diff(self, dest: str) -> str:
        # Pop while more than one entry is queued; once down to the
        # last (or default single) entry, keep returning it so
        # tests that call diff() repeatedly without pre-loading a
        # long queue still see a stable, non-empty value.
        if len(self.diffs) > 1:
            return self.diffs.pop(0)
        return self.diffs[0] if self.diffs else ""
    async def push(self, dest: str, branch: str) -> None:
        self.pushed.append(branch)


class _FakeNotifier:
    """Records attention-worthy statuses, mirroring the filtering
    every real Notifier implementation is responsible for (see
    InAppNotifier._is_notifiable) rather than recording every
    call unconditionally."""

    def __init__(self) -> None:
        self.notified: list[str] = []

    def notify(self, run) -> None:
        if run.status in ("done", "failed") or run.status.startswith(
            "awaiting_"
        ):
            self.notified.append(run.status)


class _FakeGitHub:
    def __init__(self, body: str = "Please add a widget") -> None:
        self.body = body
        self.updated: str | None = None

    async def get_issue(self, repo: str, number: int) -> Issue:
        return Issue(number=number, title="Add widget", body=self.body)
    async def get_default_branch(self, repo: str) -> str:
        return "main"
    async def update_issue(self, repo: str, number: int, body: str) -> None:
        self.updated = body
    async def create_pull_request(self, repo, head, base, title, body,
                                  draft=True) -> str:
        return "https://github.com/o/r/pull/1"


class _FakeRunner:
    """Records a session with a canned final result text per call."""

    def __init__(self, sessions: SessionRegistry, outputs: list[str]) -> None:
        self.sessions = sessions
        self._outputs = list(outputs)
        self._n = 0

    async def run_blocking(self, prompt, cwd, permission_mode,
                           resume_id=None, on_session_id=None,
                           model=None) -> str:
        sid = resume_id or f"s{self._n}"
        self._n += 1
        self.calls = getattr(self, "calls", [])
        self.calls.append(
            {"resume_id": resume_id, "model": model,
             "permission_mode": permission_mode,
             "prompt": prompt}
        )
        text = self._outputs.pop(0)
        if self.sessions.get(sid) is None:
            self.sessions._records[sid] = SessionRecord(session_id=sid, cwd=cwd)
        rec = self.sessions.get(sid)
        rec.events.append(ParsedEvent("result", sid, {"result": text}))
        rec.status = "idle"
        if on_session_id:
            on_session_id(sid)
        return sid

    def terminate(self, session_id: str) -> bool:
        self.terminated = getattr(self, "terminated", [])
        self.terminated.append(session_id)
        return True


def _service(github, runner, git) -> WorkflowService:
    return WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        runner=runner,
        git=git,
        github=github,
        notifier=_FakeNotifier(),
    )


def _coord(ids: list[str]) -> str:
    """A coordinator PROFILES block naming the profiles to interview."""
    return f"<PROFILES>{json.dumps(ids)}</PROFILES>"


def _q(qid="q1", prompt="Which auth?", qtype="single_select",
       required=True, options=None, waiver_label=None,
       audience=None) -> dict:
    """One question dict for a QUESTIONS block.

    ``audience`` is set only on reconciler output, where each
    consolidated question names the profile that owns it.
    """
    q: dict = {"id": qid, "prompt": prompt, "type": qtype,
               "required": required}
    if options is not None:
        q["options"] = options
    if waiver_label is not None:
        q["waiver_label"] = waiver_label
    if audience is not None:
        q["audience"] = audience
    return q


def _qs(*questions: dict) -> str:
    """A generator QUESTIONS block wrapping the given questions."""
    body = json.dumps({"questions": list(questions)})
    return f"<QUESTIONS>{body}</QUESTIONS>"


def _refined(text: str) -> str:
    """A writer REFINED_ISSUE block."""
    return f"<REFINED_ISSUE>\n{text}\n</REFINED_ISSUE>"


#: Simplest refine leg: coordinator needs nobody, writer emits the issue.
def _refine_noquestions(text: str) -> list[str]:
    return [_coord([]), _refined(text)]


async def _wait(pred, timeout=2.0) -> None:
    for _ in range(int(timeout / 0.02)):
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not reached")


@pytest.mark.asyncio
async def test_happy_path_refine_plan_implement_pr() -> None:
    """Ensure a run refines, plans, implements, and opens a PR."""
    gh = _FakeGitHub(body="vague issue")
    git = _FakeGit()
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("Build a clear widget"),              # refine
        "<PLAN>\nStep 1: do X\nStep 2: do Y\n</PLAN>",              # plan
        "Implemented X and Y",                                      # implement
    ])
    svc = _service(gh, runner, git)

    wid = await svc.create("o/r", 5)

    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    assert svc.get(wid).steps[0].deliverable == "Build a clear widget"
    svc.approve(wid)  # writes issue + sentinel, advances to plan

    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    assert svc.get(wid).steps[1].deliverable == "Step 1: do X\nStep 2: do Y"
    assert gh.updated is not None and "kestrel:refined" in gh.updated
    svc.approve(wid)

    await _wait(lambda: svc.get(wid).status == "awaiting_implement_approval")
    assert "diff" in svc.get(wid).steps[2].deliverable
    svc.approve(wid)

    await _wait(lambda: svc.get(wid).status == "done")
    assert svc.get(wid).pr_url == "https://github.com/o/r/pull/1"
    assert git.pushed == [svc.get(wid).branch]


@pytest.mark.asyncio
async def test_sentinel_skips_refine() -> None:
    """Ensure an already-refined issue jumps straight to plan."""
    gh = _FakeGitHub(body="clear issue\n\n<!-- kestrel:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "The plan", "Implemented",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    assert svc.get(wid).steps[0].status == "done"  # refine skipped
    # No <PLAN> tag emitted: falls back to the raw text rather than
    # leaving the deliverable empty (e.g. if the model doesn't comply).
    assert svc.get(wid).steps[1].deliverable == "The plan"


@pytest.mark.asyncio
async def test_refine_question_visible_while_awaiting_input() -> None:
    """Ensure generated questions are surfaced in the interview envelope
    (tagged with their audience) so the UI can render the form."""
    from app.questionnaire import parse_envelope

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
    assert question.id == "developer:q1"  # namespaced across profiles

    svc.submit_answers(wid, {"developer:q1": "A blue one"})
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")
    assert svc.get(wid).steps[0].deliverable == "Build a blue widget"


@pytest.mark.asyncio
async def test_reject_ends_run() -> None:
    """Ensure rejecting a gate ends the run as rejected."""
    gh = _FakeGitHub(body="x\n\n<!-- kestrel:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=["The plan"])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    svc.reject(wid)
    await _wait(lambda: svc.get(wid).status == "rejected")


@pytest.mark.asyncio
async def test_step_failure_is_logged_and_recorded(caplog) -> None:
    """Ensure a failing step logs the exception (not just swallows it)."""

    class _BrokenGitHub(_FakeGitHub):
        async def get_issue(self, repo: str, number: int) -> Issue:
            raise RuntimeError("boom: simulated GitHub failure")

    svc = _service(
        _BrokenGitHub(), _FakeRunner(SessionRegistry(), ["x"]), _FakeGit()
    )
    with caplog.at_level("ERROR", logger="app.services.workflows"):
        wid = await svc.create("o/r", 5)
        await _wait(lambda: svc.get(wid).status == "failed")

    assert svc.get(wid).error is not None
    assert "boom: simulated GitHub failure" in svc.get(wid).error
    assert any(
        wid in record.message
        and record.exc_info is not None
        and "boom" in str(record.exc_info[1])
        for record in caplog.records
    )


def test_get_unknown_raises() -> None:
    """Ensure get on an unknown id raises WorkflowNotFoundError."""
    svc = _service(_FakeGitHub(), _FakeRunner(SessionRegistry(), ["x"]),
                   _FakeGit())
    with pytest.raises(WorkflowNotFoundError):
        svc.get("nope")


@pytest.mark.asyncio
async def test_reply_wrong_state_raises() -> None:
    """Ensure reply outside the refine interview raises InvalidWorkflowState."""
    from app.models_workflow import WorkflowRun, WorkflowStep

    svc = _service(_FakeGitHub(), _FakeRunner(SessionRegistry(), ["x"]),
                   _FakeGit())
    run = WorkflowRun(id="wf", repo="o/r", issue_number=1,
                      steps=[WorkflowStep(name="refine", status="pending")])
    svc.workflows.create(run)
    svc._control["wf"] = svc._new_control()  # needs a running loop
    with pytest.raises(InvalidWorkflowStateError):
        svc.reply("wf", "an answer")


@pytest.mark.asyncio
async def test_steps_use_policy_models() -> None:
    """Ensure each phase passes its policy model to claude."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("Build it"),
        "<PLAN>\nDo it\n</PLAN>",
        "Implemented",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_refine_approval"
    )
    svc.approve(wid)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_plan_approval"
    )
    svc.approve(wid)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_implement_approval"
    )
    assert {c["model"] for c in runner.calls} == {"sonnet"}
    assert [s.model for s in svc.get(wid).steps] == [
        "sonnet", "sonnet", "sonnet",
    ]
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")


@pytest.mark.asyncio
async def test_reject_with_refinement_regenerates() -> None:
    """Ensure gate feedback regenerates the refined issue via the writer."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("v1"),
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
async def test_reject_plan_with_refinement_regenerates() -> None:
    """Ensure plan feedback resumes the plan session."""
    gh = _FakeGitHub(body="x\n\n<!-- kestrel:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "plan v1", "plan v2",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_plan_approval"
    )
    plan_sid = svc.get(wid).steps[1].session_id
    svc.reject(wid, refinement_prompt="Split into two phases")
    await _wait(
        lambda: svc.get(wid).steps[1].deliverable == "plan v2"
    )
    assert svc.get(wid).status == "awaiting_plan_approval"
    assert runner.calls[1]["resume_id"] == plan_sid
    assert "Split into two phases" in runner.calls[1]["prompt"]


@pytest.mark.asyncio
async def test_reject_implement_with_refinement_reruns() -> None:
    """Ensure implement feedback resumes the implement session."""
    gh = _FakeGitHub(body="x\n\n<!-- kestrel:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "plan", "impl v1", "impl v2",
    ])
    git = _FakeGit()
    svc = _service(gh, runner, git)
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_plan_approval"
    )
    svc.approve(wid)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_implement_approval"
    )
    impl_sid = svc.get(wid).steps[2].session_id
    svc.reject(wid, refinement_prompt="Add tests for X")
    await _wait(
        lambda: len(runner.calls) == 3
        and svc.get(wid).status
        == "awaiting_implement_approval"
    )
    assert runner.calls[2]["resume_id"] == impl_sid
    assert "Add tests for X" in runner.calls[2]["prompt"]
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")


@pytest.mark.asyncio
async def test_questionnaire_deliverable_is_structured() -> None:
    """Ensure fan-out questions become an interview envelope and the
    finalized answers reach the writer."""
    from app.questionnaire import parse_envelope

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
    assert envelope.questionnaire.questions[0].id == "developer:q1"
    assert envelope.questionnaire.profiles[0].id == "developer"

    svc.submit_answers(wid, {"developer:q1": "oidc"})
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_refine_approval"
    )
    assert "ANSWERS SO FAR:" in runner.calls[-1]["prompt"]
    assert "OIDC" in runner.calls[-1]["prompt"]


@pytest.mark.asyncio
async def test_malformed_questions_block_is_skipped() -> None:
    """Ensure a profile whose generator output is malformed simply
    contributes no questions rather than blocking the run."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord(["developer"]),
        "<QUESTIONS>{not json}</QUESTIONS>",  # skipped
        _refined("ok"),
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status
        == "awaiting_refine_approval"
    )
    assert svc.get(wid).steps[0].deliverable == "ok"


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
        svc.submit_answers(wid, {"developer:q1": "saml"})
    assert len(runner.calls) == 2  # coordinator + one generator only


@pytest.mark.asyncio
async def test_draft_save_persists_without_resuming() -> None:
    """Ensure a partial draft is stored and the agent is not resumed."""
    from app.questionnaire import parse_envelope

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
    svc.save_draft(wid, {"developer:q1": "a"})
    # Still parked at the interview; no further agent call fired.
    assert svc.get(wid).status == "awaiting_refine_input"
    assert len(runner.calls) == 2
    envelope = parse_envelope(svc.get(wid).steps[0].deliverable)
    assert envelope.draft_answers == {"developer:q1": "a"}
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
        _refined("Use A then B"),
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_refine_input"
    )
    assert svc.get(wid).steps[0].refine_round == 1

    svc.submit_answers(wid, {"developer:q1": "a"})
    await _wait(
        lambda: svc.get(wid).steps[0].refine_round == 2
    )
    assert svc.get(wid).status == "awaiting_refine_input"

    svc.submit_answers(wid, {"developer:q1": "b"})
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
        "infosec:q1": {
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
async def test_save_publishes_to_bus() -> None:
    """Ensure every state transition ticks the SSE bus for that run."""

    class _Bus:
        def __init__(self) -> None:
            self.ticks: list[str] = []

        def publish(self, workflow_id: str) -> None:
            self.ticks.append(workflow_id)

    bus = _Bus()
    gh = _FakeGitHub(body="x\n\n<!-- kestrel:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=["plan", "impl"])
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        runner=runner,
        git=_FakeGit(),
        github=gh,
        notifier=_FakeNotifier(),
        bus=bus,
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    assert bus.ticks  # at least one push happened
    assert all(t == wid for t in bus.ticks)


@pytest.mark.asyncio
async def test_profiles_are_interviewed_concurrently() -> None:
    """Ensure the coordinator-selected profiles are interviewed at the
    same time (each in its own live session), not one after another."""
    from app.questionnaire import parse_envelope

    class _BarrierRunner(_FakeRunner):
        """Holds every profile generator at a barrier until all have
        started, so the test can prove they overlap."""

        def __init__(self, sessions, outputs, expected) -> None:
            super().__init__(sessions, outputs)
            self.inflight = 0
            self.max_inflight = 0
            self._expected = expected
            self._all_in = asyncio.Event()

        async def run_blocking(self, prompt, cwd, permission_mode,
                               resume_id=None, on_session_id=None,
                               model=None) -> str:
            gen = "interviewing one stakeholder profile" in prompt
            if gen:
                self.inflight += 1
                self.max_inflight = max(self.max_inflight, self.inflight)
                if self.inflight >= self._expected:
                    self._all_in.set()
                await self._all_in.wait()
            sid = await super().run_blocking(
                prompt, cwd, permission_mode, resume_id,
                on_session_id, model,
            )
            if gen:
                self.inflight -= 1
            return sid

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
    from app.questionnaire import parse_envelope

    gh = _FakeGitHub(body="let users sign in")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_overlapping_accounts_round(),
        # Reconciler folds both into ONE plain requester-owned question.
        _qs(_q(qid="x", audience="requester",
               prompt="How are accounts created?",
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
    from app.questionnaire import parse_envelope

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
    assert ids == {"requester:q1", "developer:q1"}
    assert {p.id for p in envelope.questionnaire.profiles} == {
        "requester", "developer",
    }


@pytest.mark.asyncio
async def test_reconciler_unknown_audience_keeps_all() -> None:
    """Ensure a reconciled question naming a non-pool audience is
    rejected wholesale, falling back to the untouched pool."""
    from app.questionnaire import parse_envelope

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
    assert ids == {"requester:q1", "developer:q1"}


@pytest.mark.asyncio
async def test_reply_targets_whichever_step_is_awaiting_input() -> None:
    """Ensure reply routes to a non-refine step awaiting input."""
    from app.models_workflow import WorkflowRun, WorkflowStep

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
async def test_submit_answers_targets_whichever_step_is_awaiting_input() -> None:
    """Ensure submit_answers validates against the active step."""
    from app.models_workflow import WorkflowRun, WorkflowStep

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


@pytest.mark.asyncio
async def test_implement_blocker_is_structured_and_resumable() -> None:
    """Ensure a mid-implementation blocker pauses and resumes."""
    gh = _FakeGitHub(body="x\n\n<!-- kestrel:refined -->")
    git = _FakeGit()
    # First implement call produces no diff (it's the blocker);
    # the second, post-answer call produces the real change.
    git.diffs = ["", "diff --git a/x b/x"]
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<PLAN>\nStep 1\n</PLAN>",
        "<QUESTIONS>"
        '{"questions": [{"id": "q1", "prompt": "Which file name?", '
        '"type": "single_select", "required": true, '
        '"options": [{"value": "a", "label": "config.yaml"}, '
        '{"value": "b", "label": "settings.yaml"}]}]}'
        "</QUESTIONS>",
        "Implemented using config.yaml",
    ])
    svc = _service(gh, runner, git)
    wid = await svc.create("o/r", 5)

    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    svc.approve(wid)

    await _wait(
        lambda: svc.get(wid).status == "awaiting_implement_input"
    )
    deliverable = svc.get(wid).steps[2].deliverable
    parsed = json.loads(deliverable)
    assert parsed["questions"][0]["id"] == "q1"
    blocked_sid = svc.get(wid).steps[2].session_id
    plan_sid = svc.get(wid).steps[1].session_id
    assert blocked_sid == plan_sid  # implement resumed the plan session

    svc.submit_answers(wid, {"q1": "a"})
    await _wait(
        lambda: svc.get(wid).status == "awaiting_implement_approval"
    )
    assert "ANSWERS:" in runner.calls[2]["prompt"]
    assert runner.calls[2]["resume_id"] == blocked_sid
    assert "diff" in svc.get(wid).steps[2].deliverable


@pytest.mark.asyncio
async def test_implement_malformed_blocker_falls_back_to_text_reply() -> None:
    """Ensure a non-compliant blocker message still allows a reply."""
    gh = _FakeGitHub(body="x\n\n<!-- kestrel:refined -->")
    git = _FakeGit()
    git.diffs = ["", "diff --git a/x b/x"]
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<PLAN>\nStep 1\n</PLAN>",
        "I'm not sure which approach — thoughts?",
        "Implemented",
    ])
    svc = _service(gh, runner, git)
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    svc.approve(wid)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_implement_input"
    )
    assert svc.get(wid).steps[2].deliverable == (
        "I'm not sure which approach — thoughts?"
    )
    svc.reply(wid, "Use approach B")
    await _wait(
        lambda: svc.get(wid).status == "awaiting_implement_approval"
    )


@pytest.mark.asyncio
async def test_notifier_fires_on_awaiting_and_done() -> None:
    """Ensure attention-worthy statuses reach the notifier."""
    gh = _FakeGitHub(body="x\n\n<!-- kestrel:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=["plan", "impl"])
    notifier = _FakeNotifier()
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        runner=runner,
        git=_FakeGit(),
        github=gh,
        notifier=notifier,
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_implement_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "done")
    assert "awaiting_plan_approval" in notifier.notified
    assert "awaiting_implement_approval" in notifier.notified
    assert "done" in notifier.notified
    assert "planning" not in notifier.notified
    assert "implementing" not in notifier.notified


@pytest.mark.asyncio
async def test_notifier_does_not_fire_on_reject() -> None:
    """Ensure a bare reject does not produce a notification."""
    gh = _FakeGitHub(body="x\n\n<!-- kestrel:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=["The plan"])
    notifier = _FakeNotifier()
    svc = WorkflowService(
        settings=Settings(git_base="https://github.com", github_token="t"),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        runner=runner,
        git=_FakeGit(),
        github=gh,
        notifier=notifier,
    )
    wid = await svc.create("o/r", 5)
    await _wait(lambda: svc.get(wid).status == "awaiting_plan_approval")
    svc.reject(wid)
    await _wait(lambda: svc.get(wid).status == "rejected")
    assert "rejected" not in notifier.notified


class _SpyGitHub(_FakeGitHub):
    """Records any *mutating* GitHub call so a test can assert none fire."""

    def __init__(self, body: str = "") -> None:
        super().__init__(body)
        self.mutations: list[str] = []

    async def update_issue(self, repo, number, body) -> None:
        self.mutations.append("update_issue")
        await super().update_issue(repo, number, body)

    async def create_pull_request(self, repo, head, base, title, body,
                                  draft=True) -> str:
        self.mutations.append("create_pull_request")
        return await super().create_pull_request(
            repo, head, base, title, body, draft
        )


@pytest.mark.asyncio
async def test_delete_drops_run_without_touching_github() -> None:
    """Ensure abandoning a run removes it and makes no GitHub calls."""
    gh = _SpyGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        *_refine_noquestions("v1"),
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_refine_approval"
    )
    before = list(gh.mutations)

    await svc.delete(wid)

    assert gh.mutations == before  # abandon touched nothing on GitHub
    assert wid not in svc._tasks  # the driver task was cancelled/cleared
    with pytest.raises(WorkflowNotFoundError):
        svc.get(wid)


@pytest.mark.asyncio
async def test_delete_removes_workspace_dir(tmp_path) -> None:
    """Ensure abandoning a run deletes its local workspace clone."""
    gh = _FakeGitHub(body="x\n\n<!-- kestrel:refined -->")
    runner = _FakeRunner(SessionRegistry(), outputs=["the plan"])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5)
    await _wait(
        lambda: svc.get(wid).status == "awaiting_plan_approval"
    )
    workspace = tmp_path / "clone"
    workspace.mkdir()
    (workspace / "file.txt").write_text("work")
    svc.get(wid).workspace = str(workspace)

    await svc.delete(wid)

    assert not workspace.exists()
    with pytest.raises(WorkflowNotFoundError):
        svc.get(wid)


@pytest.mark.asyncio
async def test_delete_unknown_raises_not_found() -> None:
    """Ensure abandoning an unknown run raises the domain error."""
    svc = _service(
        _FakeGitHub(), _FakeRunner(SessionRegistry(), ["x"]), _FakeGit()
    )
    with pytest.raises(WorkflowNotFoundError):
        await svc.delete("nope")
