"""End-to-end regression tests (feature 013, T054) walking
``specs/013-feedback-intake/quickstart.md`` Scenarios 1-2 for real,
against the file-backed local task source — no real GitHub/Jira ticket
or LLM credentials needed, matching the quickstart's own "local task
source" prerequisite.

Unlike ``test_feedback_intake.py``/``test_feedback_dispatch.py``/
``test_feedback_poll.py`` (each of which exercises exactly one stage of
the pipeline behind a fake stand-in for its neighbours —
``FeedbackIntakeService`` behind a fake ``dispatch`` callback,
``FeedbackDispatcher`` behind a hand-built ``FeedbackItemRow``,
``FeedbackPollService`` behind a fake intake), these tests wire the
*real* ``FeedbackPollService`` -> real ``FeedbackIntakeService`` -> real
``FeedbackDispatcher`` -> real ``WorkflowService`` chain against a real
``LocalTaskSource`` reading and writing real files under ``tmp_path``
— the same file format an operator actually edits
(timestamped Markdown files). Only the LLM turns themselves are canned
(``_FakeRunner``), same as every other workflow test in this suite.

Scenarios 3-4 need a real GitHub PR (review comments, merge/close
lifecycle) that this sandboxed suite has no way to stand up; their
logical behaviour is covered instead by
``test_workflow_feedback_resume.py`` and the review-origin/terminal-run
branches of ``test_feedback_dispatch.py`` via fakes, per T054's own
scope note.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.models_workflow import WorkflowRun, WorkflowStep
from app.notifications import TaskSourceNotifier
from app.persistence.feedback_store import FeedbackStore
from app.persistence.review_request_store import ReviewRequestStore
from app.persistence.workflow_store import WorkflowStore
from app.services.feedback.dispatch import FeedbackDispatcher
from app.services.feedback.intake import FeedbackIntakeService
from app.services.feedback.poll import FeedbackPollService
from app.services.github import GitHubCodeHost
from app.services.local_task_source import LocalTaskSource
from app.services.workflows import WorkflowService
from app.services.workflows.driver.code_verify import code_and_verify
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry
from tests.conftest import (
    _coord,
    _FakeGit,
    _FakeGitHub,
    _FakeNotifier,
    _FakeRunner,
    _refined,
    _settings,
    _verdict,
    _wait,
)
from tests.local_task_helpers import write_local_task as _write_local_task


def _local_task_service(
    tmp_path, runner: _FakeRunner, fake_gh: _FakeGitHub, git=None,
    feedback_store: FeedbackStore | None = None,
) -> WorkflowService:
    """A real ``WorkflowService`` wired to a real, tmp_path-backed
    ``LocalTaskSource`` under the ``"local-task"`` source key —
    mirrors ``test_workflow_rerun.py``'s ``_private_service`` builder.

    :param feedback_store: Wired through to ``drain_feedback``'s round/
        step-boundary reads (feature 013, US2) — ``None`` (the default)
        is fine for Scenario 1, which never reaches a drain boundary.
    """
    local_source = LocalTaskSource(str(tmp_path))
    return WorkflowService(
        settings=_settings(workspace_root=str(tmp_path)),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=git or _FakeGit(),
        github=fake_gh,
        notifier=_FakeNotifier(),
        sources={"local-task": local_source},
        code_hosts={"local-task": GitHubCodeHost(fake_gh, "https://gh")},
        feedback_store=feedback_store,
    )


def _append_comment(tmp_path, slug: str, body: str, created: str) -> str:
    """Write local feedback and return its source-stable external id."""
    timestamp = datetime.fromisoformat(created).strftime("%Y-%m-%dT%H.%M.%S")
    path = tmp_path / slug / "comments" / f"{timestamp}.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(body)
    return f"local:{slug}:{path.name}"


def _stores(tmp_path) -> tuple[FeedbackStore, ReviewRequestStore]:
    """Build real stores against an isolated, migrated SQLite database."""
    database = tmp_path / "feedback.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")
    factory = sessionmaker(bind=create_engine(f"sqlite:///{database}"))
    return FeedbackStore(factory), ReviewRequestStore(factory)


def _pipeline(
    svc: WorkflowService,
    store: FeedbackStore,
    reviews: ReviewRequestStore | None = None,
) -> FeedbackPollService:
    """The real intake/dispatch/poll chain, wired the way
    ``feedback/bootstrap.py`` wires the process-wide singletons — just
    without an ``IngestionService`` (US4's successor path is untouched
    by Scenarios 1-2)."""
    dispatcher = FeedbackDispatcher(svc, store, review_requests=reviews)
    intake = FeedbackIntakeService(
        svc.settings, store, svc, dispatcher.dispatch
    )
    return FeedbackPollService(svc, store, intake)


def _persistent_local_task_service(
    tmp_path,
    runner: _FakeRunner,
    workflow_store: WorkflowStore,
    reviews: ReviewRequestStore,
) -> WorkflowService:
    """Build a local-task service whose state survives a restart."""
    local_source = LocalTaskSource(str(tmp_path))
    workflows = WorkflowRegistry(store=workflow_store)
    workflows.preload(workflow_store.load_all())
    return WorkflowService(
        settings=_settings(workspace_root=str(tmp_path)),
        sessions=runner.sessions,
        workflows=workflows,
        backends=runner,
        git=_FakeGit(),
        github=_FakeGitHub(),
        notifier=TaskSourceNotifier({"local-task": local_source}, "", reviews),
        sources={"local-task": local_source},
        code_hosts={"local-task": GitHubCodeHost(_FakeGitHub(), "https://gh")},
        review_requests=reviews,
    )


@pytest.mark.asyncio
async def test_scenario1_marked_comment_redirects_a_parked_run(
    tmp_path,
) -> None:
    """Quickstart Scenario 1, end-to-end against real local task files:
    a parked run + a marked timestamped Markdown comment -> the real
    poll/intake/dispatch chain re-parks it at the same gate with the
    feedback folded in; a second, unmarked comment changes nothing.
    """
    _write_local_task(tmp_path, "widget", body="Add a vague widget")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<UNDERSTANDING>Add a widget.</UNDERSTANDING>",
        _coord([]), _refined("v1"), _refined("v2 with feedback"),
    ])
    svc = _local_task_service(tmp_path, runner, _FakeGitHub())
    store, _reviews = _stores(tmp_path)
    poll = _pipeline(svc, store)

    wid = await svc.create(
        "me/sandbox", source="local-task", task_ref="local:widget",
    )
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")

    external_id = _append_comment(
        tmp_path, "widget", "@kestrel mention the API surface",
        "2026-01-01T00:00:00+00:00",
    )
    await poll.run_cycle()
    await _wait(
        lambda: svc.get(wid).steps[1].deliverable == "v2 with feedback"
    )

    assert svc.get(wid).status == "awaiting_refine_approval"
    item = store.get(external_id)
    assert item is not None and item.state == "applied"

    # An unmarked follow-up comment (Scenario 1 steps 5-6): no new item,
    # no change to the run at all.
    _append_comment(
        tmp_path, "widget", "just a normal remark",
        "2026-01-02T00:00:00+00:00",
    )
    await poll.run_cycle()

    assert svc.get(wid).steps[1].deliverable == "v2 with feedback"
    assert store.get(external_id) is not None


@pytest.mark.asyncio
async def test_scenario2_marked_comment_queues_then_drains_at_round_start(
    tmp_path,
) -> None:
    """Quickstart Scenario 2, end-to-end against real local task files: a
    marked comment left while a run is mid-``coding`` (no open gate) is
    queued — not applied immediately — by the real poll/intake/dispatch
    chain, then folded into the coder's prompt at the next round's start.
    """
    _write_local_task(tmp_path, "worker", body="Build a worker")
    runner = _FakeRunner(
        SessionRegistry(), outputs=["Implemented X", _verdict(accept=True)]
    )
    store, _reviews = _stores(tmp_path)
    svc = _local_task_service(
        tmp_path, runner, _FakeGitHub(), feedback_store=store,
    )
    run = WorkflowRun(
        id="wf-worker", repo="me/sandbox", task_ref="local:worker",
        source="local-task", base_branch="main", branch="kestrel/worker",
        workspace=str(tmp_path), status="coding",
        steps=[
            WorkflowStep(name="describe", status="done", deliverable="U"),
            WorkflowStep(name="refine", status="done", deliverable="PRD"),
            WorkflowStep(
                name="technical_analysis", status="done", deliverable=""
            ),
            WorkflowStep(name="design", status="done", deliverable="Design"),
            WorkflowStep(name="code", status="pending"),
            WorkflowStep(name="verify", status="pending"),
        ],
    )
    svc.workflows.create(run)
    poll = _pipeline(svc, store)

    external_id = _append_comment(
        tmp_path, "worker", "@kestrel also handle the empty-input case",
        datetime.now(timezone.utc).isoformat(),
    )
    await poll.run_cycle()

    queued = store.queued_for("wf-worker")
    assert len(queued) == 1 and queued[0].state == "queued"

    escalated = await code_and_verify(svc, run)

    assert escalated is False
    code_call = next(
        c for c in runner.calls if c["permission_mode"] == "acceptEdits"
    )
    assert "also handle the empty-input case" in code_call["prompt"]
    item = store.get(external_id)
    assert item is not None and item.state == "applied"


@pytest.mark.asyncio
async def test_local_feedback_queued_before_describe_gate_is_redispatched(
    tmp_path,
) -> None:
    """A queued local response reaches the active describe revision.

    It dispatches on the next poll after the describe gate becomes active.
    """
    _write_local_task(tmp_path, "recover", body="Build a recoverable task")
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>Build a recoverable task.</UNDERSTANDING>",
            "<UNDERSTANDING>Build it with local feedback.</UNDERSTANDING>",
        ],
    )
    store, reviews = _stores(tmp_path)
    svc = _local_task_service(tmp_path, runner, _FakeGitHub())
    dispatcher = FeedbackDispatcher(svc, store, review_requests=reviews)
    intake = FeedbackIntakeService(
        svc.settings, store, svc, dispatcher.dispatch
    )
    poll = FeedbackPollService(svc, store, intake)
    wid = await svc.create(
        "me/sandbox", source="local-task", task_ref="local:recover",
    )
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")

    external_id = _append_comment(
        tmp_path,
        "recover",
        "[kestrel-review:active] @kestrel include local feedback",
        "2026-01-01T00:00:00+00:00",
    )
    run = svc.get(wid)
    run.status = "coding"
    await poll.run_cycle()
    item = store.get(external_id)
    assert item is not None and item.state == "queued"

    run.status = "awaiting_describe_approval"
    reviews.create(wid, "awaiting_describe_approval", 1, "active")
    await poll.run_cycle()

    await _wait(
        lambda: svc.get(wid).steps[0].deliverable
        == "Build it with local feedback."
    )

    item = store.get(external_id)
    assert item is not None and item.state == "applied"


@pytest.mark.asyncio
async def test_tokenized_approval_publishes_a_decomposition_candidate(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A polled external approval advances the tokenized decomposition gate.

    This wires the real local feedback source, poller, intake, dispatcher,
    feedback ledger, review ledger, and asynchronous workflow driver. It
    protects the production path where a valid feedback row was marked
    ``applied`` while the run nevertheless remained parked.
    """
    _write_local_task(tmp_path, "decompose", body="Split the work")
    runner = _FakeRunner(
        SessionRegistry(),
        outputs=[
            "<UNDERSTANDING>Split the work.</UNDERSTANDING>",
            _coord([]),
            _refined("Approved requirements"),
            (
                "<TECH_ANALYSIS>analysis</TECH_ANALYSIS>"
                '<FOLLOWUP_TASKS>[{"title":"Implement it",'
                '"body":"Deliver the approved work."}]</FOLLOWUP_TASKS>'
            ),
            '<CONTAINMENT>{"verdicts": []}</CONTAINMENT>',
        ],
    )
    store, reviews = _stores(tmp_path)
    url = f"sqlite:///{tmp_path / 'feedback.db'}"
    workflow_store = WorkflowStore(sessionmaker(bind=create_engine(url)))
    svc = _persistent_local_task_service(
        tmp_path, runner, workflow_store, reviews
    )
    poll = _pipeline(svc, store, reviews)

    workflow_id = await svc.create(
        "me/sandbox", source="local-task", task_ref="local:decompose",
    )
    await _wait(
        lambda: svc.get(workflow_id).status == "awaiting_describe_approval"
    )
    svc.approve(workflow_id)
    await _wait(
        lambda: svc.get(workflow_id).status == "awaiting_refine_approval"
    )
    svc.approve(workflow_id)
    await _wait(
        lambda: svc.get(workflow_id).status
        == "awaiting_decomposition_approval"
    )
    await _wait(
        lambda: reviews.active_for(
            workflow_id, "awaiting_decomposition_approval"
        ) is not None
    )
    review = reviews.active_for(workflow_id, "awaiting_decomposition_approval")
    assert review is not None
    source = svc.task_source_for(svc.get(workflow_id))
    original_create_subtask = source.create_subtask
    publish_started = asyncio.Event()

    async def block_subtask_creation(parent_ref, title, body, markers=()):
        """Stop publication after the approved gate decision is consumed."""
        publish_started.set()
        await asyncio.Future()
        return await original_create_subtask(
            parent_ref, title, body, markers=markers
        )

    monkeypatch.setattr(source, "create_subtask", block_subtask_creation)
    external_id = _append_comment(
        tmp_path,
        "decompose",
        f"[kestrel-review:{review.token}] @kestrel approve",
        "2026-01-01T00:00:00+00:00",
    )

    await poll.run_cycle()
    item = store.get(external_id)
    assert item is not None and item.state == "applied"
    await publish_started.wait()
    driver = svc._tasks[workflow_id]
    driver.cancel()
    with pytest.raises(asyncio.CancelledError):
        await driver

    # The process dies after intake marks feedback applied but before the
    # asynchronously woken driver publishes the approved candidate.
    recovered = _persistent_local_task_service(
        tmp_path,
        _FakeRunner(SessionRegistry(), []),
        workflow_store,
        reviews,
    )
    await recovered.recover()
    await _wait(lambda: recovered.get(workflow_id).status == "decomposed")

    assert reviews.active_for(
        workflow_id, "awaiting_decomposition_approval"
    ) is None
