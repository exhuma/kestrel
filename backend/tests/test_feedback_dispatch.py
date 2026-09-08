"""Tests for FeedbackDispatcher's gate-branch (feature 013, US1),
review-origin routing (feature 013, US3), and terminal-run revive-vs-
successor / escalated-retry branches (feature 013, US4)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models_workflow import Step, WorkflowRun, WorkflowStep
from app.persistence.tables import FeedbackItemRow
from app.services.feedback.dispatch import FeedbackDispatcher
from app.services.ingestion import IngestionService
from app.storage.registry import SessionRegistry
from tests.conftest import (
    _coord,
    _FakeDismissals,
    _FakeFeedbackStore,
    _FakeGit,
    _FakeGitHub,
    _FakeRunner,
    _service,
    _settings,
    _verdict,
    _wait,
)

_DONE_PR_NUMBER = 9


def _item(external_id="a", workflow_id="wf-1", body="@kestrel feedback") -> (
    FeedbackItemRow
):
    return FeedbackItemRow(
        external_id=external_id, workflow_id=workflow_id, task_ref="o/r#5",
        origin="ticket", author="octocat", body=body, state="queued",
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_gate_branch_rejects_with_the_feedback_body() -> None:
    """A parked run gets the feedback applied exactly as a UI
    reject-with-feedback would, and the item is marked applied."""
    gh = _FakeGitHub(body="vague issue")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord([]), "<REFINED_ISSUE>\nv1\n</REFINED_ISSUE>",
        "<REFINED_ISSUE>\nv2 with feedback\n</REFINED_ISSUE>",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5, source="github-issue")
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")

    store = _FakeFeedbackStore()
    dispatcher = FeedbackDispatcher(svc, store)
    item = _item(workflow_id=wid, body="Mention the API surface")
    store.claim(item)

    dispatcher.dispatch(item)
    await _wait(
        lambda: svc.get(wid).steps[0].deliverable == "v2 with feedback"
    )

    assert svc.get(wid).status == "awaiting_refine_approval"
    assert "Mention the API surface" in runner.calls[-1]["prompt"]
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
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _coord([]), "<REFINED_ISSUE>\nv1\n</REFINED_ISSUE>",
    ])
    svc = _service(gh, runner, _FakeGit())
    wid = await svc.create("o/r", 5, source="github-issue")
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
        "coding", "verifying", "analyzing", "designing",
        "describing", "refining", "opening_pr",
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


# ---- review-origin routing (feature 013, US3) --------------------------


def _review_item(workflow_id="wf-1", body="please fix the bug") -> (
    FeedbackItemRow
):
    return FeedbackItemRow(
        external_id="r1", workflow_id=workflow_id, task_ref="o/r#5",
        origin="review", author="reviewer", body=body, state="queued",
        created_at=datetime.now(timezone.utc),
    )


def _ingestion_for(svc) -> IngestionService:
    """A real IngestionService wired onto ``svc``'s own registry, for the
    successor-path tests: exercises the actual
    ``start_successor_run``/``WorkflowService.create`` machinery rather
    than a duplicate-logic fake."""
    return IngestionService(svc.settings, svc, _FakeDismissals())


def _done_run(**overrides) -> WorkflowRun:
    defaults = dict(
        id="wf-1", repo="o/r", task_ref="o/r#5", status="done",
        branch="kestrel/issue-5", base_branch="main",
        steps=[WorkflowStep(name=s, status="done") for s in Step.sequence()],
    )
    defaults.update(overrides)
    return WorkflowRun(**defaults)


@pytest.mark.asyncio
async def test_review_origin_open_pr_resumes_the_branch() -> None:
    """A done run whose PR is still open resumes via
    WorkflowService.resume_with_feedback, and the item is marked
    dispatched (not applied — the resume's own drive cycle continues the
    processing asynchronously)."""
    gh = _FakeGitHub()
    gh.pr_state = "open"
    svc = _service(gh, _FakeRunner(SessionRegistry(), []), _FakeGit())
    svc.workflows.create(_done_run(pr_number=_DONE_PR_NUMBER))
    resumed: list[tuple[str, str]] = []
    svc.resume_with_feedback = (
        lambda wid, body: resumed.append((wid, body))
    )
    store = _FakeFeedbackStore()
    dispatcher = FeedbackDispatcher(svc, store)
    item = _review_item()
    store.claim(item)

    dispatcher.dispatch(item)
    await _wait(lambda: resumed)

    assert resumed == [("wf-1", "please fix the bug")]
    assert store.items["r1"].state == "dispatched"


def _successor_of(svc, parent: WorkflowRun) -> WorkflowRun:
    """The one other run in ``svc``'s registry besides ``parent`` itself."""
    return next(r for r in svc.list() if r.id != parent.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("pr_state", ["merged", "closed"])
async def test_done_run_with_a_finished_pr_starts_a_linked_successor(
    pr_state: str,
) -> None:
    """A merged OR merely-closed PR is the same "can no longer be added
    to" case (US4) — a linked successor, not a revive. Also proves the
    revive-vs-successor decision is no longer review-origin-only: the
    same routing now applies regardless of ``item.origin`` (a done run
    has no gate of its own left for either kind of feedback to land on
    more directly)."""
    gh = _FakeGitHub()
    gh.pr_state = pr_state
    svc = _service(gh, _FakeRunner(SessionRegistry(), []), _FakeGit())
    parent = _done_run(pr_number=_DONE_PR_NUMBER)
    svc.workflows.create(parent)
    store = _FakeFeedbackStore()
    dispatcher = FeedbackDispatcher(svc, store, _ingestion_for(svc))
    item = _item(
        workflow_id=parent.id, body="@kestrel also handle the null case"
    )
    store.claim(item)

    dispatcher.dispatch(item)
    await _wait(lambda: len(svc.list()) > 1)

    successor = _successor_of(svc, parent)
    assert successor.parent_run_id == parent.id
    assert successor.task_ref == parent.task_ref
    assert successor.repo == parent.repo
    assert successor.branch != parent.branch  # never collides with parent's
    assert store.items["a"].state == "applied"


@pytest.mark.asyncio
async def test_done_merged_pr_with_no_ingestion_wired_stays_queued() -> None:
    """Without an ingestion service wired in, the successor path is a
    safe no-op (logged) rather than a crash — mirrors every other
    optional-dependency no-op in this module."""
    gh = _FakeGitHub()
    gh.pr_state = "merged"
    svc = _service(gh, _FakeRunner(SessionRegistry(), []), _FakeGit())
    svc.workflows.create(_done_run(pr_number=_DONE_PR_NUMBER))
    store = _FakeFeedbackStore()
    dispatcher = FeedbackDispatcher(svc, store)  # no ingestion passed
    item = _review_item()
    store.claim(item)

    dispatcher.dispatch(item)
    await _wait(lambda: True)

    assert len(svc.list()) == 1
    assert store.items["r1"].state == "queued"


@pytest.mark.asyncio
async def test_review_origin_falls_back_to_parsing_pr_url() -> None:
    """A pre-migration row with no pr_number yet still resolves it by
    parsing run.pr_url."""
    gh = _FakeGitHub()
    gh.pr_state = "open"
    svc = _service(gh, _FakeRunner(SessionRegistry(), []), _FakeGit())
    svc.workflows.create(
        _done_run(pr_number=None, pr_url="https://github.com/o/r/pull/9")
    )
    resumed: list[tuple[str, str]] = []
    svc.resume_with_feedback = (
        lambda wid, body: resumed.append((wid, body))
    )
    store = _FakeFeedbackStore()
    dispatcher = FeedbackDispatcher(svc, store)
    item = _review_item()
    store.claim(item)

    dispatcher.dispatch(item)
    await _wait(lambda: resumed)

    assert resumed == [("wf-1", "please fix the bug")]


@pytest.mark.asyncio
async def test_done_with_no_pr_at_all_starts_a_linked_successor() -> None:
    """A done run with neither pr_number nor a parseable pr_url — the
    request "never existed" case (US4, spec.md Scenario 2) — also gets a
    linked successor, with no HTTP round-trip needed to decide (there is
    no pr_number to check a state for)."""
    svc = _service(
        _FakeGitHub(), _FakeRunner(SessionRegistry(), []), _FakeGit()
    )
    parent = _done_run(pr_number=None, pr_url=None)
    svc.workflows.create(parent)
    store = _FakeFeedbackStore()
    dispatcher = FeedbackDispatcher(svc, store, _ingestion_for(svc))
    item = _review_item()
    store.claim(item)

    dispatcher.dispatch(item)
    await _wait(lambda: len(svc.list()) > 1)

    successor = _successor_of(svc, parent)
    assert successor.parent_run_id == parent.id
    assert store.items["r1"].state == "applied"


# ---- escalated-run retry (feature 013, US4) -----------------------------


def _triage(step: str, reason: str = "r", instruction: str = "do it") -> str:
    return (
        f'<TRIAGE>{{"step": "{step}", "reason": "{reason}", '
        f'"instruction": "{instruction}"}}</TRIAGE>'
    )


def _escalated_run(**overrides) -> WorkflowRun:
    defaults = dict(
        id="wf-esc", repo="o/r", task_ref="o/r#5", status="escalated",
        error="escalated: gave up after 3 rounds",
        branch="kestrel/issue-5", base_branch="main",
        steps=[
            WorkflowStep(name=Step.REFINE, status="done", deliverable="PRD"),
            WorkflowStep(
                name=Step.DESIGN, status="done", deliverable="design"
            ),
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
    runner = _FakeRunner(SessionRegistry(), outputs=[
        _triage("code", instruction=instruction),
        "fixed diff",
        _verdict(accept=True),
    ])
    svc = _service(
        gh, runner, git,
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
