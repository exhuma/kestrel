"""Tests for FeedbackDispatcher's gate-branch (feature 013, US1),
review-origin routing (feature 013, US3), and terminal-run revive-vs-
successor / escalated-retry branches (feature 013, US4)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models_workflow import Step, WorkflowRun, WorkflowStep
from app.persistence.tables import FeedbackItemRow
from app.services.feedback.dispatch import FeedbackDispatcher
from app.storage.registry import SessionRegistry
from tests.conftest import (
    _coord,
    _FakeFeedbackStore,
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _service,
    _settings,
    _verdict,
    _wait,
)


class _ReviewRequests:
    """In-memory active-review lookup for dispatcher tests."""

    def __init__(self, token: str = "current") -> None:
        self.token = token
        self.superseded: list[str] = []

    def is_active(self, token: str, workflow_id: str, gate: str) -> bool:
        """Accept exactly the configured current token at a gate."""
        return (
            token == self.token
            and workflow_id == "wf-1"
            and gate.startswith("awaiting_")
        )

    def retire(self, workflow_id: str, gate: str) -> None:
        """Record that the active revision was retired."""
        del gate
        self.superseded.append(workflow_id)


def _item(
    external_id="a", workflow_id="wf-1", body="@kestrel feedback"
) -> FeedbackItemRow:
    return FeedbackItemRow(
        external_id=external_id,
        workflow_id=workflow_id,
        task_ref="o/r#5",
        origin="ticket",
        author="octocat",
        body=body,
        state="queued",
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_gate_branch_rejects_with_the_feedback_body() -> None:
    """A parked run gets the feedback applied exactly as a UI
    reject-with-feedback would, and the item is marked applied."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>Build a widget.</UNDERSTANDING>",
            _coord([]),
            "<REFINED_ISSUE>\nv1\n</REFINED_ISSUE>",
            "<REFINED_ISSUE>\nv2 with feedback\n</REFINED_ISSUE>",
        ],
    )
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")

    store = _FakeFeedbackStore()
    dispatcher = FeedbackDispatcher(svc, store)
    item = _item(workflow_id=wid, body="Mention the API surface")
    store.claim(item)

    dispatcher.dispatch(item)
    await _wait(lambda: svc.get(wid).steps[1].deliverable == "v2 with feedback")

    assert svc.get(wid).status == "awaiting_refine_approval"
    assert "Mention the API surface" in runner.calls[-1]["prompt"]
    assert store.items["a"].state == "applied"


@pytest.mark.asyncio
async def test_gate_branch_approves_an_explicit_marker_command() -> None:
    """An explicit @kestrel approve resolves the parked describe gate."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>Build a widget.</UNDERSTANDING>",
            _coord([]),
            "<REFINED_ISSUE>\nv1\n</REFINED_ISSUE>",
        ],
    )
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    store = _FakeFeedbackStore()
    item = _item(workflow_id=wid, body="@kestrel approve")
    store.claim(item)

    FeedbackDispatcher(svc, store).dispatch(item)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")

    assert store.items["a"].state == "applied"


@pytest.mark.asyncio
async def test_gate_branch_accepts_tokenized_plain_language_approval() -> None:
    """A current token enables ordinary-language approval at a gate."""
    reviews = _ReviewRequests()
    svc = _service(
        _FakeGitHub(),
        _FakeRunner(SessionRegistry(), []),
        _FakeGit(),
        review_requests=reviews,
    )
    run = WorkflowRun(
        id="wf-1", repo="o/r", status="awaiting_describe_approval"
    )
    svc.workflows.create(run)
    svc._control[run.id] = svc._new_control()
    store = _FakeFeedbackStore()
    item = _item(body="[kestrel-review:current] Looks good to me.")
    store.claim(item)
    FeedbackDispatcher(svc, store, review_requests=reviews).dispatch(item)

    assert (await svc._await_gate(run.id)).approved
    assert reviews.superseded == [run.id]


@pytest.mark.asyncio
async def test_ui_gate_decision_retires_its_review_token() -> None:
    """A UI approval retires the token through the shared workflow service."""
    reviews = _ReviewRequests()
    svc = _service(
        _FakeGitHub(),
        _FakeRunner(SessionRegistry(), []),
        _FakeGit(),
        review_requests=reviews,
    )
    run = WorkflowRun(
        id="wf-1", repo="o/r", status="awaiting_describe_approval"
    )
    svc.workflows.create(run)
    svc._control[run.id] = svc._new_control()

    svc.approve(run.id)

    assert reviews.superseded == [run.id]


@pytest.mark.asyncio
async def test_gate_branch_ignores_a_stale_review_token() -> None:
    """A reply quoting a superseded revision cannot resolve the current gate."""
    svc = _service(
        _FakeGitHub(), _FakeRunner(SessionRegistry(), []), _FakeGit()
    )
    run = WorkflowRun(
        id="wf-1", repo="o/r", status="awaiting_describe_approval"
    )
    svc.workflows.create(run)
    svc._control[run.id] = svc._new_control()
    store = _FakeFeedbackStore()
    item = _item(body="[kestrel-review:old] @kestrel approve")
    store.claim(item)

    dispatcher = FeedbackDispatcher(
        svc, store, review_requests=_ReviewRequests()
    )
    dispatcher.dispatch(item)

    assert store.items["a"].state == "ignored"


@pytest.mark.asyncio
async def test_gate_branch_uses_active_token_after_a_stale_quote() -> None:
    """An active token later in a reply still resolves the intended gate."""
    svc = _service(
        _FakeGitHub(), _FakeRunner(SessionRegistry(), []), _FakeGit()
    )
    run = WorkflowRun(
        id="wf-1", repo="o/r", status="awaiting_describe_approval"
    )
    svc.workflows.create(run)
    svc._control[run.id] = svc._new_control()
    store = _FakeFeedbackStore()
    item = _item(
        body="[kestrel-review:old] quoted [kestrel-review:current] approve"
    )
    store.claim(item)

    dispatcher = FeedbackDispatcher(
        svc, store, review_requests=_ReviewRequests()
    )
    dispatcher.dispatch(item)

    assert (await svc._await_gate(run.id)).approved


@pytest.mark.asyncio
async def test_gate_branch_approves_decomposition_candidates() -> None:
    """An explicit approval resolves the decomposition gate too."""
    svc = _service(
        _FakeGitHub(), _FakeRunner(SessionRegistry(), []), _FakeGit()
    )
    run = WorkflowRun(
        id="wf-1",
        repo="o/r",
        issue_number=5,
        status="awaiting_decomposition_approval",
        steps=[
            WorkflowStep(name=Step.GAP_ANALYSIS, status="awaiting_approval")
        ],
    )
    svc.workflows.create(run)
    svc._control[run.id] = svc._new_control()
    store = _FakeFeedbackStore()
    item = _item(body="@kestrel approve")
    store.claim(item)

    FeedbackDispatcher(svc, store).dispatch(item)
    assert (await svc._await_gate(run.id)).approved
    assert store.items["a"].state == "applied"


@pytest.mark.asyncio
async def test_stale_redispatch_of_an_applied_item_is_idempotent() -> None:
    """A second marked comment claimed under a different external_id but
    while the run is already back at the gate still re-fires reject —
    the *dedup* itself (not re-claiming an already-processed row) is
    FeedbackStore.claim's job, exercised in test_feedback_store.py; this
    confirms the dispatcher's own idempotent behavior when handed an
    item whose row is already marked applied (a stale re-dispatch)."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>Build a widget.</UNDERSTANDING>",
            _coord([]),
            "<REFINED_ISSUE>\nv1\n</REFINED_ISSUE>",
        ],
    )
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")

    store = _FakeFeedbackStore()
    dispatcher = FeedbackDispatcher(svc, store)
    item = _item(workflow_id=wid)
    store.claim(item)
    store.mark("a", "applied")

    # A stale re-dispatch of an already-applied item is still a plain
    # gate-branch dispatch by today's contract (dedup happens at claim
    # time, upstream of dispatch) — assert it does not raise and still
    # marks the row applied (idempotent outcome).
    dispatcher.dispatch(item)

    assert store.items["a"].state == "applied"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        "coding",
        "verifying",
        "analyzing",
        "designing",
        "describing",
        "refining",
        "opening_pr",
    ],
)
async def test_transient_status_run_is_not_dispatched_to_reject(
    status: str,
) -> None:
    """Every transient, no-open-gate status (US2) is a dispatch no-op —
    the feedback stays queued for a later phase's drain_feedback, and
    WorkflowService.reject is never called."""
    gh = _FakeGitHub(body="issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5, source="github-issue")
    run = svc.get(wid)
    run.status = status

    reject_calls: list[str] = []
    svc.reject = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: reject_calls.append(status)
    )

    store = _FakeFeedbackStore()
    dispatcher = FeedbackDispatcher(svc, store)
    item = _item(workflow_id=wid)
    store.claim(item)

    dispatcher.dispatch(item)

    assert store.items["a"].state == "queued"
    assert reject_calls == []


@pytest.mark.asyncio
async def test_no_target_run_is_a_no_op() -> None:
    """An item with no workflow_id yet (unrouted ticket feedback) is a
    no-op — nothing to dispatch to."""
    store = _FakeFeedbackStore()
    dispatcher = FeedbackDispatcher(
        _service(_FakeGitHub(), _FakeRunner(SessionRegistry(), []), _FakeGit()),
        store,
    )
    item = _item(workflow_id=None)
    store.claim(item)

    dispatcher.dispatch(item)

    assert store.items["a"].state == "queued"


@pytest.mark.asyncio
async def test_unknown_workflow_id_is_a_no_op() -> None:
    """An item pointing at a workflow id the registry has no record of
    (e.g. a since-deleted run) is a no-op, not a crash."""
    store = _FakeFeedbackStore()
    dispatcher = FeedbackDispatcher(
        _service(_FakeGitHub(), _FakeRunner(SessionRegistry(), []), _FakeGit()),
        store,
    )
    item = _item(workflow_id="wf-does-not-exist")
    store.claim(item)

    dispatcher.dispatch(item)

    assert store.items["a"].state == "queued"


# ---- escalated-run retry (feature 013, US4) -----------------------------


def _triage(step: str, reason: str = "r", instruction: str = "do it") -> str:
    return (
        f'<TRIAGE>{{"step": "{step}", "reason": "{reason}", '
        f'"instruction": "{instruction}"}}</TRIAGE>'
    )


def _escalated_run(**overrides) -> WorkflowRun:
    defaults = dict(
        id="wf-esc",
        repo="o/r",
        task_ref="o/r#5",
        status="escalated",
        error="escalated: gave up after 3 rounds",
        branch="kestrel/issue-5",
        base_branch="main",
        steps=[
            WorkflowStep(
                name=Step.DESCRIBE, status="done", deliverable="understood"
            ),
            WorkflowStep(name=Step.REFINE, status="done", deliverable="PRD"),
            WorkflowStep(
                name=Step.GAP_ANALYSIS,
                status="done",
                deliverable="",
            ),
            WorkflowStep(name=Step.DESIGN, status="done", deliverable="design"),
            WorkflowStep(name=Step.CODE, status="failed"),
            WorkflowStep(name=Step.VERIFY, status="failed"),
        ],
    )
    defaults.update(overrides)
    return WorkflowRun(**defaults)


@pytest.mark.asyncio
async def test_escalated_run_falls_back_to_a_fresh_branch_off_base(
    tmp_path,
) -> None:
    """An escalated run never pushed a branch — resume must provision a
    FRESH branch off base_branch (add_worktree), not add_worktree_existing
    — and the triage instruction reaches the retried step's prompt."""
    gh, git = _FakeGitHub(), _FakeGit()
    fstore = _FakeFeedbackStore()
    instruction = "retry with a smaller batch size"
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            _triage("code", instruction=instruction),
            "fixed diff",
            _verdict(accept=True),
        ],
    )
    svc = _service(
        gh,
        runner,
        git,
        settings=_settings(workspace_root=str(tmp_path)),
        feedback_store=fstore,
    )
    run = _escalated_run(workspace=str(tmp_path / "wf-esc"))
    svc.workflows.create(run)

    seen_fresh: list[str] = []
    seen_existing: list[str] = []
    orig_fresh, orig_existing = git.add_worktree, git.add_worktree_existing

    async def _tracked_fresh(mirror_dir, dest, base_branch, new_branch):
        seen_fresh.append(new_branch)
        return await orig_fresh(mirror_dir, dest, base_branch, new_branch)

    async def _tracked_existing(mirror_dir, dest, branch):
        seen_existing.append(branch)
        return await orig_existing(mirror_dir, dest, branch)

    git.add_worktree = _tracked_fresh
    git.add_worktree_existing = _tracked_existing

    dispatcher = FeedbackDispatcher(svc, fstore)
    item = _item(workflow_id="wf-esc", body=f"@kestrel {instruction}")
    fstore.claim(item)

    dispatcher.dispatch(item)
    await _wait(lambda: svc.get("wf-esc").status == "done")

    assert seen_fresh == ["kestrel/issue-5"]
    assert seen_existing == []
    assert instruction in runner.calls[-2]["prompt"]
    assert fstore.items["a"].state == "dispatched"
