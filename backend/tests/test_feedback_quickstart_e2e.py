"""End-to-end regression tests (feature 013, T054) walking
``specs/013-feedback-intake/quickstart.md`` Scenarios 1-2 for real,
against the file-backed fixture task source — no real GitHub/Jira ticket
or LLM credentials needed, matching the quickstart's own "fixture task
source" prerequisite.

Unlike ``test_feedback_intake.py``/``test_feedback_dispatch.py``/
``test_feedback_poll.py`` (each of which exercises exactly one stage of
the pipeline behind a fake stand-in for its neighbours —
``FeedbackIntakeService`` behind a fake ``dispatch`` callback,
``FeedbackDispatcher`` behind a hand-built ``FeedbackItemRow``,
``FeedbackPollService`` behind a fake intake), these tests wire the
*real* ``FeedbackPollService`` -> real ``FeedbackIntakeService`` -> real
``FeedbackDispatcher`` -> real ``WorkflowService`` chain against a real
``FixtureTaskSource`` reading and writing real files under ``tmp_path``
— the same file format an operator actually edits
(``<slug>.comments.jsonl``). Only the LLM turns themselves are canned
(``_FakeRunner``), same as every other workflow test in this suite.

Scenarios 3-4 need a real GitHub PR (review comments, merge/close
lifecycle) that this sandboxed suite has no way to stand up; their
logical behaviour is covered instead by
``test_workflow_feedback_resume.py`` and the review-origin/terminal-run
branches of ``test_feedback_dispatch.py`` via fakes, per T054's own
scope note.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.models_workflow import WorkflowRun, WorkflowStep
from app.persistence.feedback_store import FeedbackStore
from app.services.feedback.dispatch import FeedbackDispatcher
from app.services.feedback.intake import FeedbackIntakeService
from app.services.feedback.poll import FeedbackPollService
from app.services.fixture import FixtureTaskSource
from app.services.github import GitHubCodeHost
from app.services.workflows import WorkflowService
from app.services.workflows.driver.code_verify import code_and_verify
from app.storage.registry import SessionRegistry
from app.storage.workflow_registry import WorkflowRegistry
from tests.conftest import (
    _coord,
    _FakeFeedbackStore,
    _FakeGit,
    _FakeGitHub,
    _FakeNotifier,
    _FakeRunner,
    _refined,
    _settings,
    _verdict,
    _wait,
    _write_fixture_task,
)


def _fixture_service(
    tmp_path, runner: _FakeRunner, fake_gh: _FakeGitHub, git=None,
    feedback_store: FeedbackStore | None = None,
) -> WorkflowService:
    """A real ``WorkflowService`` wired to a real, tmp_path-backed
    ``FixtureTaskSource`` under the ``"fixture-issue"`` source key —
    mirrors ``test_workflow_rerun.py``'s ``_private_service`` builder.

    :param feedback_store: Wired through to ``drain_feedback``'s round/
        step-boundary reads (feature 013, US2) — ``None`` (the default)
        is fine for Scenario 1, which never reaches a drain boundary.
    """
    fixture_source = FixtureTaskSource(str(tmp_path))
    return WorkflowService(
        settings=_settings(workspace_root=str(tmp_path)),
        sessions=runner.sessions,
        workflows=WorkflowRegistry(),
        backends=runner,
        git=git or _FakeGit(),
        github=fake_gh,
        notifier=_FakeNotifier(),
        sources={"fixture-issue": fixture_source},
        code_hosts={"fixture-issue": GitHubCodeHost(fake_gh, "https://gh")},
        feedback_store=feedback_store,
    )


def _append_comment(tmp_path, slug: str, body: str, created: str) -> None:
    """Append one line to a fixture task's real ``<slug>.comments.jsonl``
    — exactly what quickstart.md Scenario 1/2 tells an operator to do by
    hand."""
    path = tmp_path / f"{slug}.comments.jsonl"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"author": "a-reviewer", "body": body, "created_at": created}
            ) + "\n"
        )


def _pipeline(
    svc: WorkflowService, store: FeedbackStore
) -> FeedbackPollService:
    """The real intake/dispatch/poll chain, wired the way
    ``feedback/bootstrap.py`` wires the process-wide singletons — just
    without an ``IngestionService`` (US4's successor path is untouched
    by Scenarios 1-2)."""
    dispatcher = FeedbackDispatcher(svc, store)
    intake = FeedbackIntakeService(
        svc.settings, store, svc, dispatcher.dispatch
    )
    return FeedbackPollService(svc, store, intake)


@pytest.mark.asyncio
async def test_scenario1_marked_comment_redirects_a_parked_run(
    tmp_path,
) -> None:
    """Quickstart Scenario 1, end-to-end against real fixture files:
    a parked run + a marked ``<slug>.comments.jsonl`` line -> the real
    poll/intake/dispatch chain re-parks it at the same gate with the
    feedback folded in; a second, unmarked comment changes nothing.
    """
    _write_fixture_task(tmp_path, "widget", body="Add a vague widget")
    runner = _FakeRunner(SessionRegistry(), outputs=[
        "<UNDERSTANDING>Add a widget.</UNDERSTANDING>",
        _coord([]), _refined("v1"), _refined("v2 with feedback"),
    ])
    svc = _fixture_service(tmp_path, runner, _FakeGitHub())
    store = _FakeFeedbackStore()
    poll = _pipeline(svc, store)

    wid = await svc.create(
        "me/sandbox", source="fixture-issue", task_ref="fixture:widget",
    )
    await _wait(lambda: svc.get(wid).status == "awaiting_describe_approval")
    svc.approve(wid)
    await _wait(lambda: svc.get(wid).status == "awaiting_refine_approval")

    _append_comment(
        tmp_path, "widget", "@kestrel mention the API surface",
        "2026-01-01T00:00:00+00:00",
    )
    await poll.run_cycle()
    await _wait(
        lambda: svc.get(wid).steps[1].deliverable == "v2 with feedback"
    )

    assert svc.get(wid).status == "awaiting_refine_approval"
    applied = [i for i in store.items.values() if i.workflow_id == wid]
    assert len(applied) == 1 and applied[0].state == "applied"

    # An unmarked follow-up comment (Scenario 1 steps 5-6): no new item,
    # no change to the run at all.
    _append_comment(
        tmp_path, "widget", "just a normal remark",
        "2026-01-02T00:00:00+00:00",
    )
    await poll.run_cycle()

    assert svc.get(wid).steps[1].deliverable == "v2 with feedback"
    assert len(store.items) == 1


@pytest.mark.asyncio
async def test_scenario2_marked_comment_queues_then_drains_at_round_start(
    tmp_path,
) -> None:
    """Quickstart Scenario 2, end-to-end against real fixture files: a
    marked comment left while a run is mid-``coding`` (no open gate) is
    queued — not applied immediately — by the real poll/intake/dispatch
    chain, then folded into the coder's prompt at the next round's start.
    """
    _write_fixture_task(tmp_path, "worker", body="Build a worker")
    runner = _FakeRunner(
        SessionRegistry(), outputs=["Implemented X", _verdict(accept=True)]
    )
    store = _FakeFeedbackStore()
    svc = _fixture_service(
        tmp_path, runner, _FakeGitHub(), feedback_store=store,
    )
    run = WorkflowRun(
        id="wf-worker", repo="me/sandbox", task_ref="fixture:worker",
        source="fixture-issue", base_branch="main", branch="kestrel/worker",
        workspace=str(tmp_path), status="coding",
        steps=[
            WorkflowStep(name="describe", status="done", deliverable="U"),
            WorkflowStep(name="refine", status="done", deliverable="PRD"),
            WorkflowStep(name="gap_analysis", status="done", deliverable=""),
            WorkflowStep(name="design", status="done", deliverable="Design"),
            WorkflowStep(name="code", status="pending"),
            WorkflowStep(name="verify", status="pending"),
        ],
    )
    svc.workflows.create(run)
    poll = _pipeline(svc, store)

    _append_comment(
        tmp_path, "worker", "@kestrel also handle the empty-input case",
        datetime.now(timezone.utc).isoformat(),
    )
    await poll.run_cycle()

    queued = [i for i in store.items.values() if i.workflow_id == "wf-worker"]
    assert len(queued) == 1 and queued[0].state == "queued"

    escalated = await code_and_verify(svc, run)

    assert escalated is False
    code_call = next(
        c for c in runner.calls if c["permission_mode"] == "acceptEdits"
    )
    assert "also handle the empty-input case" in code_call["prompt"]
    assert queued[0].state == "applied"
